"""Tata hunt automation. Default mode observes only; --run explicitly enables input."""
import argparse
from datetime import datetime,timezone
import json
import os
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
    p.add_argument('--test-fish',action='store_true',help='实机验收：在2倍场用鱼怪臭臭替代200倍萨满，不手动射击或刷道具')
    p.add_argument('--background',action='store_true',help='后台窗口截图与消息输入，不激活游戏或移动鼠标；窗口不可最小化')
    p.add_argument('--hwnd',type=int,help='明确选择游戏窗口；双开时必须指定')
    p.add_argument('--list-windows',action='store_true',help='列出游戏窗口编号与屏幕位置后退出')
    p.add_argument('--hunt-only',action='store_true',help='锁定用完后停止，不进入低倍刷道具')
    p.add_argument('--account-key',help='按UID哈希确认所选窗口账号，切换账号即停止')
    p.add_argument('--targets',default='2008',help='允许锁定的配置ID列表，默认仅2008；可选2007')
    p.add_argument('--control-file',type=Path,help='托管任务的目标配置文件，仅接受已支持的目标编号')
    p.add_argument('--resume-mode',choices=('farm','hunt'),help='异常恢复时继续补货或消耗阶段')
    a=p.parse_args()
    if a.background and a.activate:p.error('--background 与 --activate 不能同时使用')
    if a.list_windows:
        from window_binding import window_choices
        print(json.dumps([dict(hwnd=h,bounds=b) for h,b in window_choices()],ensure_ascii=False));return
    options=Options(a.stock,a.low,not a.no_rage,a.rounds,a.seconds,a.reserve,a.test_fish,a.hunt_only,
        tuple(int(v) for v in a.targets.split(','))).validate()
    folder=a.run_dir or RUNTIME/'runs'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
    publishing=False;last_metrics={}
    def event(kind,**data):
        if 'bullets' in data:last_metrics.update({k:v for k,v in data.items() if k in ('bullets','locks','rage','multiplier','completed','lock_active','lock_target','mode')})
        value=dict(last_metrics,time=datetime.now(timezone.utc).isoformat(),event=kind,pid=os.getpid(),
            run_dir=str(folder.resolve()),stop_file=str(a.stop_file.resolve()) if a.stop_file else None,
            control_file=str(a.control_file.resolve()) if a.control_file else None,**data)
        if a.account_key:value['account_key']=a.account_key
        write_json(folder/'status.json',value)
        with (folder/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')
        print(json.dumps(value,ensure_ascii=False),flush=True)
        if publishing and a.hwnd is not None:write_json(RUNTIME/'windows'/str(a.hwnd)/'status.json',value)
    live=None
    try:
        event('initializing',reason='连接围猎只读模型' if not a.run else '准备围猎自动化')
        from hunt_live import HuntLive
        if not a.run:
            if a.hwnd is not None:
                from window_binding import bound_renderers
                live=HuntLive(pids=bound_renderers(a.hwnd))
            else:live=HuntLive()
            end=time.monotonic()+a.seconds
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
        hwnd=find_game_window(a.hwnd) if a.hwnd is not None else find_game_window()
        a.hwnd=hwnd
        if a.stop_file is None:
            a.stop_file=RUNTIME/'windows'/str(hwnd)/'STOP';a.stop_file.unlink(missing_ok=True)
        with device_lease('windows-fishing-'+str(hwnd),check_processes=False):
            publishing=True
            from window_binding import bound_renderers
            pids=bound_renderers(hwnd)
            if a.background:
                from background_input import BackgroundHuntInput
                controls=BackgroundHuntInput(hwnd)
            else:controls=HuntInput(hwnd=hwnd)
            if a.activate:controls.focus()
            else:controls.stop_check()
            try:
                # Do not clear global stop signals after the panel has launched us.
                live=HuntLive(pids=pids)
                if a.account_key and live.snapshot()['account_key']!=a.account_key:raise RuntimeError('所选窗口账号已切换，未启动输入')
                event('bound',hwnd=hwnd,background=a.background,account_key=getattr(live,'account',None))
                Runner(options,live,controls,Layout(),event,a.stop_file,evidence_dir=folder,control_path=a.control_file,initial_mode=a.resume_mode).run()
            finally:controls.release()
    except Exception as exc:
        event('error',reason=str(exc));raise
    finally:
        if live:live.close()


if __name__=='__main__':main()
