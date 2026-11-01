"""Bounded supervision of explicitly listed background hunting accounts."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from hunt_paths import ROOT,RUNTIME,HERE
from model import write_json


def recoverable(reason):
    return not any(word in reason for word in ('账号','F8','用户停止','最小化','已关闭','余额不足','金猎币不足'))


class Supervisor:
    def __init__(self,jobs,until,folder):
        if len({j['hwnd'] for j in jobs})!=len(jobs):raise ValueError('不能重复配置同一窗口')
        for job in jobs:
            key=job['account_key']
            if len(key)!=24 or any(c not in '0123456789abcdef' for c in key):raise ValueError('账号哈希无效')
        self.jobs=[dict(config=j,process=None,phase='pending',failures=[],next_start=0,run_dir=None,stop=None,stream=None,
            history=[],electric_added=False,control=None) for j in jobs]
        self.until=until;self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        try:previous=json.loads((self.folder/'status.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):previous={}
        for job in self.jobs:
            old=next((j for j in previous.get('jobs',[]) if j['hwnd']==job['config']['hwnd'] and j['account_key']==job['config']['account_key']),{})
            observation=old.get('observation',{})
            job['resume_mode']=observation.get('mode') or ('farm' if observation.get('multiplier')==1 and observation.get('locks',0)<job['config'].get('stock',10) else None)

    def launch(self,job):
        cfg=job['config'];folder=self.folder/str(cfg['hwnd'])/uuid.uuid4().hex;folder.mkdir(parents=True)
        stop=folder/'STOP';stream=(folder/'worker.log').open('w',encoding='utf-8')
        seconds=max(1,min(86400,(self.until-datetime.now(timezone.utc)).total_seconds()))
        args=[sys.executable,'-X','utf8','-u',str(HERE/'desktop.py'),'--run','--background',
            '--hwnd',str(cfg['hwnd']),'--account-key',cfg['account_key'],'--stock',str(cfg.get('stock',10)),
            '--low','1','--rounds','1000','--seconds',str(seconds),'--reserve',str(cfg.get('reserve',0)),
            '--run-dir',str(folder),'--stop-file',str(stop)]
        control=self.folder/str(cfg['hwnd'])/'control.json'
        write_json(control,dict(targets=[2008,2007] if job['electric_added'] else cfg.get('targets',[2008])))
        args+=['--targets',','.join(str(t) for t in cfg.get('targets',[2008])),'--control-file',str(control)]
        if job.get('resume_mode') in ('farm','hunt'):args+=['--resume-mode',job['resume_mode']]
        if not cfg.get('use_rage',True):args.append('--no-rage')
        try:process=subprocess.Popen(args,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:stream.close();raise
        job.update(process=process,phase='running',run_dir=folder,stop=stop,stream=stream,control=control)

    def update_last_hour(self,job,now):
        observation=self.observation(job);balance=observation.get('bullets')
        if observation.get('mode') in ('farm','hunt'):job['resume_mode']=observation['mode']
        if type(balance) is not int:return
        history=job['history'];history.append((now,balance));job['history']=[row for row in history if now-row[0]<=1800]
        remaining=(self.until-datetime.now(timezone.utc)).total_seconds()
        if not job['config'].get('allow_electric_last_hour',False) or not 0<remaining<=3600 or job['electric_added'] or balance<=0:return
        first=job['history'][0];span=now-first[0]
        rate=max(0,(first[1]-balance)/span) if span>=60 else 0
        if rate>0 and balance<=rate*remaining*.9:return
        job['electric_added']=True
        write_json(job['control'],dict(targets=[2008,2007]))
        with (self.folder/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),event='electric_added',
                hwnd=job['config']['hwnd'],balance=balance,recent_rate=rate,seconds_left=remaining),ensure_ascii=False)+'\n')

    def observation(self,job):
        if not job['run_dir']:return {}
        try:return json.loads((job['run_dir']/'status.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}

    def tick(self):
        now=time.monotonic()
        for job in self.jobs:
            process=job['process']
            if process is not None and process.poll() is not None:
                job['stream'].close();job['process']=None;state=self.observation(job)
                reason=state.get('reason','未知进程退出')
                if process.returncode==0 or not recoverable(reason):job['phase']='finished' if process.returncode==0 else 'attention'
                else:
                    job['failures']=[t for t in job['failures'] if now-t<600]+[now]
                    job['phase']='attention' if len(job['failures'])>=3 else 'retrying'
                    job['next_start']=now+5
            if job['phase'] in ('pending','retrying') and now>=job['next_start']:self.launch(job)
            if job['phase']=='running':self.update_last_hour(job,now)
        self.publish()

    def publish(self):
        write_json(self.folder/'status.json',dict(until=self.until.isoformat(),updated_at=datetime.now(timezone.utc).isoformat(),
            jobs=[dict(hwnd=j['config']['hwnd'],account_key=j['config']['account_key'],phase=j['phase'],
                pid=j['process'].pid if j['process'] else None,observation=self.observation(j),
                electric_added=j['electric_added'],targets=[2008,2007] if j['electric_added'] else j['config'].get('targets',[2008]),
                run_dir=str(j['run_dir']) if j['run_dir'] else None) for j in self.jobs]))

    def stop(self):
        for job in self.jobs:
            if job['process'] is not None:job['stop'].touch()
        deadline=time.monotonic()+45
        while any(j['process'] is not None and j['process'].poll() is None for j in self.jobs) and time.monotonic()<deadline:
            time.sleep(.2)
        for job in self.jobs:
            process=job['process']
            if process is not None:
                if process.poll() is None:process.terminate()
                job['process']=None;job['phase']='stopped'
            if job['stream']:job['stream'].close()
        self.publish()

    def run(self):
        try:
            while datetime.now(timezone.utc)<self.until and not (self.folder/'STOP').exists():
                self.tick()
                if all(j['phase'] in ('finished','attention') for j in self.jobs):break
                time.sleep(2)
        finally:self.stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=Path,required=True);parser.add_argument('--until',required=True)
    parser.add_argument('--folder',type=Path,default=RUNTIME/'supervised')
    args=parser.parse_args();until=datetime.fromisoformat(args.until)
    if until.tzinfo is None:parser.error('结束时间必须包含时区')
    Supervisor(json.loads(args.jobs.read_text(encoding='utf-8')),until.astimezone(timezone.utc),args.folder).run()


if __name__=='__main__':main()
