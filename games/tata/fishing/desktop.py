"""Windows fishing runner: F8 or STOP file stops; foreground changes pause input."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

import numpy as np

from paths import ROOT,RUNTIME
sys.path.insert(0,str(ROOT/'src'))
from autogame.platforms.lease import device_lease
from windows import DesktopWindow,find_game_window,is_wechat_game,user
from desktop_vision import DesktopVision
from snapshots import SnapshotWriter
from aim import SliderAim


def main():
    ap=argparse.ArgumentParser(description='Desktop fishing: F8 / Ctrl+C to stop')
    ap.add_argument('--hwnd',type=int,help='Default: find the unique 塔塔冒险队 window')
    ap.add_argument('--seconds',type=float,default=1800)
    ap.add_argument('--casts',type=int,default=0)
    ap.add_argument('--lead-ms',type=float,default=40)
    ap.add_argument('--observe',action='store_true')
    ap.add_argument('--activate',action='store_true',help='Bring the game forward once at startup')
    ap.add_argument('--stop-file',type=Path,help='Additional per-session stop signal (used by the control panel)')
    args=ap.parse_args()
    if args.seconds<=0 or args.casts<0 or not 0<=args.lead_ms<=300:ap.error('Invalid duration, casts, or lead time')
    args.hwnd=args.hwnd or find_game_window()
    if not is_wechat_game(args.hwnd):raise RuntimeError('Selected window is not a WeChat game process.')
    w=DesktopWindow(args.hwnd);vision=DesktopVision()
    root=RUNTIME;root.mkdir(parents=True,exist_ok=True)
    stop=root/'STOP';run=root/datetime.now().strftime('%Y%m%d-%H%M%S-%f');run.mkdir()
    log=(run/'events.jsonl').open('w',encoding='utf8')
    snapshots=SnapshotWriter(run)
    motion=(run/'motion.csv').open('w',encoding='utf8');motion.write('time,x,left,right,speed,predicted\n')
    started=time.perf_counter();previous='';last_action=0.;idle_since=None;unknown_since=None
    aim=SliderAim();casts=shots=rewards=0;durations=[];hook_sent=False;reward_sent=False
    state_since=started;last_reward_click=0.
    in_minigame=False;recovery_tries=0;last_recovery=0.

    def event(kind,**data):
        row=dict(time=datetime.now().isoformat(timespec='milliseconds'),event=kind,**data)
        line=json.dumps(row,ensure_ascii=False);print(line,flush=True);log.write(line+'\n');log.flush()

    def stopped():
        return stop.exists() or (args.stop_file is not None and args.stop_file.exists()) or w.emergency_stop()

    with device_lease('windows-fishing-'+str(args.hwnd)):
        stop.unlink(missing_ok=True)
        try:
            if args.activate:
                user.SetForegroundWindow(args.hwnd)
                time.sleep(.5)
            started=time.perf_counter()
            event('start',hwnd=args.hwnd,observe=args.observe,lead_ms=args.lead_ms)
            while time.perf_counter()-started<args.seconds and not stopped():
                before=time.perf_counter();frame,stamp=w.grab();grabbed=time.perf_counter()
                sample_time=(stamp+grabbed)/2
                obs=vision.observe(frame);now=time.perf_counter()
                durations.append(now-before)
                if obs.state!=previous:
                    state_since=now
                    event('state',state=obs.state,score=round(obs.score,3))
                    snapshots.save(f'{now-started:08.3f}-{obs.state}.png',frame)
                    if obs.state in ('idle','waiting','slider','hook'):reward_sent=False
                    previous=obs.state
                action=None;projected=speed=None;delay=0.;target=obs.yellow
                if obs.state=='idle':
                    in_minigame=False;recovery_tries=0;aim.reset()
                    idle_since=idle_since or now
                    if now-idle_since>.12 and now-last_action>.28:
                        if args.casts and casts>=args.casts:
                            event('cast_limit');break
                        action='cast'
                else:idle_since=None
                if obs.state=='hook' and not in_minigame and not hook_sent and now-last_action>.3:action='hook'
                if obs.state in ('reward','rare_reward','record_reward','result_card') and now-state_since>.1 and now-last_action>.18:
                    # Click a recognized result immediately; retry only if its close animation did not complete.
                    if not reward_sent or now-last_reward_click>1.2:
                        action={'reward':'collect','rare_reward':'dismiss_rare','record_reward':'dismiss_record','result_card':'dismiss_card'}[obs.state]
                if obs.state=='slider':
                    in_minigame=True
                    estimate=aim.update(sample_time,obs.pointer,obs.yellow,now,args.lead_ms/1000,obs.track or (114.,296.))
                    if estimate:
                        speed=estimate.speed;projected=estimate.predicted;target=estimate.target
                        left,right=target
                        motion.write(f'{now-started:.4f},{obs.pointer},{left},{right},{speed:.2f},{projected:.2f}\n')
                        if estimate.delay is not None and now-last_action>.33:
                            action='reel';delay=estimate.delay
                if obs.state=='unknown':
                    unknown_since=unknown_since or now
                    if now-unknown_since>1.1 and recovery_tries<3 and now-last_recovery>1.4:
                        action='recover_blank'
                    if now-unknown_since>10 and recovery_tries>=3:event('stop_unknown');break
                else:unknown_since=None
                if action and not args.observe:
                    due=time.perf_counter()+delay
                    while time.perf_counter()<due and not stopped():
                        time.sleep(min(.003,max(0,due-time.perf_counter())))
                    if stopped():break
                    if time.perf_counter()-stamp>(.22 if action=='reel' else .14):continue
                    x,y=(200,658) if action=='collect' else ((300,675) if action in ('recover_blank','dismiss_card','dismiss_rare','dismiss_record') else (200,620))
                    click_start=time.perf_counter();w.click(x,y)
                    last_action=time.perf_counter()
                    if action=='cast':casts+=1;hook_sent=False;in_minigame=False;aim.reset()
                    if action=='hook':hook_sent=True
                    if action in ('collect','dismiss_rare','dismiss_record','dismiss_card'):
                        if not reward_sent:rewards+=1
                        reward_sent=True;last_reward_click=last_action
                    if action=='recover_blank':recovery_tries+=1;last_recovery=last_action
                    if action=='reel':shots+=1;aim.fired(last_action)
                    event('click',action=action,x=obs.pointer,yellow=target,speed=speed,predicted=projected,
                          scheduled_ms=round(delay*1000,2),recovery_attempt=recovery_tries if action=='recover_blank' else None,
                          click_ms=round((last_action-click_start)*1000,2),age_ms=round((click_start-stamp)*1000,2),
                          casts=casts,slider_clicks=shots,rewards=rewards)
                    snapshots.save(f'{now-started:08.3f}-click-{action}.png',frame)
                time.sleep(.003)
            event('finished',casts=casts,slider_clicks=shots,rewards=rewards,
                  frame_ms_p50=round(float(np.median(durations))*1000,2) if durations else None)
        finally:w.close();snapshots.close();log.close();motion.close()


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Stopped.',flush=True)
    except Exception as e:print(f'ERROR: {e}',file=sys.stderr,flush=True);sys.exit(1)
