"""Tata hunt automation. Default mode observes only; --run explicitly enables input."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import uuid
from hunt_paths import ROOT,RUNTIME
from hunt_policy import Options
from model import write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--run',action='store_true');mode.add_argument('--observe',action='store_true')
    p.add_argument('--activate',action='store_true');p.add_argument('--stock',type=int,default=10)
    p.add_argument('--low',type=int,choices=(1,2,5),default=1);p.add_argument('--no-rage',action='store_true')
    p.add_argument('--rounds',type=int,default=10);p.add_argument('--seconds',type=float,default=3600)
    p.add_argument('--reserve',type=int,default=0);p.add_argument('--stop-file',type=Path);p.add_argument('--run-dir',type=Path)
    a=p.parse_args()
    options=Options(a.stock,a.low,not a.no_rage,a.rounds,a.seconds,a.reserve).validate()
    folder=a.run_dir or RUNTIME/'runs'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
    def event(kind,**data):
        value=dict(time=datetime.now(timezone.utc).isoformat(),event=kind,**data)
        write_json(folder/'status.json',value)
        with (folder/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')
        print(json.dumps(value,ensure_ascii=False),flush=True)
    live=None
    try:
        event('initializing',reason='连接围猎只读模型' if not a.run else '准备围猎自动化')
        from hunt_live import HuntLive
        if not a.run:
            live=HuntLive();end=time.monotonic()+a.seconds
            while time.monotonic()<end:
                if a.stop_file and a.stop_file.exists():break
                value=live.snapshot();write_json(folder/'observation.json',value)
                event('observation',screen=value['screen'],locks=value['locks'],rage=value['rage'],bullets=value['bullets'],
                    shamans=[e['id'] for e in value.get('enemies',[]) if e['tid']==2008 and e['active']])
                time.sleep(.25)
            event('finished',reason='只读观察结束，未移动鼠标或激活游戏');return
        from autogame.platforms.lease import device_lease
        from desktop_input import find_game_window
        from hunt_input import HuntInput
        from hunt_layout import Layout
        from hunt_engine import Runner
        hwnd=find_game_window()
        with device_lease('windows-fishing-'+str(hwnd),check_processes=False):
            controls=HuntInput()
            if a.activate:controls.focus()
            else:controls.stop_check()
            try:
                # Do not clear global stop signals after the panel has launched us.
                live=HuntLive();Runner(options,live,controls,Layout(),event,a.stop_file,evidence_dir=folder).run()
            finally:controls.release()
    except Exception as exc:
        event('error',reason=str(exc));raise
    finally:
        if live:live.close()


if __name__=='__main__':main()
