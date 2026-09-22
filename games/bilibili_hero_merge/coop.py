"""Co-op: verified two-device setup and independent battle workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from autogame.platforms.mumu import MuMuPlatform
from coop_ui import Screen, setup_pair, unique_name
from policy import price_action, merge_pair
from tactics import load_tactics, choose_card


def board_cells(side):
    # Observed co-op tiles; seven starting cells, expansions above/below.
    xs=(77,111,146) if side=='host' else (285,320,355)
    return [(x,y) for y in (494,527) for x in xs]+[(xs[1],460),(xs[1],425),(xs[1],562)]


class Battle:
    def __init__(self, screen, side, args, stop):
        self.s=screen; self.side=side; self.args=args; self.stop=stop
        profile=args.host_tactics if side=='host' else args.guest_tactics
        self.cfg,_=load_tactics(profile)
        self.units={};self.pending=None;self.last_scan=0;self.last_action=0
        self.summons=0;self.previous_price=None;self.previous_upgrade=None;self.upgrade_stalls=0;self.status='waiting';self.deadline=time.monotonic()+args.minutes*60
        self.last_board=None;self.bad=0;self.full_until=0

    def log(self,event,**data):
        record={'time':time.strftime('%H:%M:%S'),'side':self.side,'event':event,**data}
        with (self.s.output/'events.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')
        print(json.dumps(record,ensure_ascii=False),flush=True)

    def croptext(self,box):
        return self.s.reader.text(self.s.raw,tuple(round(v*2.5) for v in box))

    def prices(self):
        boxes={'upgrade':(141,750,168,766),'summon':(277,750,304,766),'money':(134,646,171,667)}
        text={k:self.croptext(b) for k,b in boxes.items()}
        values={k:self.s.reader.number(v) for k,v in text.items()}
        if '免费' in text['summon']: values['summon']=0
        return values,text

    def battle(self):
        labels=self.s.labels
        return (any('波次' in p.text and 190<p.x<240 and 70<p.y<105 for p in labels)
                and unique_name(labels,self.args.host_name) is not None
                and unique_name(labels,self.args.guest_name) is not None
                and any(p.text==f'第{self.args.stage}层' and p.y<100 for p in labels))

    def buff(self):
        # Only act on a visible choice modal; never on three battlefield heroes.
        titles=[p for p in self.s.labels if 100<p.y<300]
        if not any(any(w in p.text for w in ('请选择','选择强化','强化选择','选择技能','选择祝福','选择增益','选择英雄','英雄强化','强化技能','选择能力','选择一个','强化')) for p in titles):
            return False
        cards=[self.s.reader.lines(self.s.raw,(x1,510,x2,1160)) for x1,x2 in [(30,356),(375,703),(725,1050)]]
        index=choose_card(cards,self.cfg)
        self.log('buff_choice',cards=cards,selected=index)
        self.s.tap([77,216,355][index],340);time.sleep(.5)
        return True

    def step(self):
        self.s.scan()
        text=' '.join(p.text for p in self.s.labels)
        if any(w in text for w in ('战斗胜利','挑战成功','挑战失败','战斗失败')) or ('返回' in text and ('胜利' in text or '失败' in text)):
            self.status='settled';self.log('settlement',text=text)
            import cv2
            cv2.imwrite(str(self.s.output/'result.png'),self.s.raw)
            return False
        # Topmost reward modal must be dismissed before the choice behind it.
        close=next((p for p in self.s.labels if '点击空白处关闭' in p.text),None)
        if close:
            self.log('close_reward',text=text)
            self.s.tap(216,628);time.sleep(.6)
            return True
        if self.buff():return True
        if not self.battle():
            self.bad+=1
            if self.bad==1:self.log('waiting_screen',text=text)
            if self.bad>=15:
                self.log('stopped_unknown',text=text);self.status='unknown';return False
            return True
        self.bad=0;self.status='battle'
        values,texts=self.prices()
        if any(v is None for v in values.values()):
            self.log('price_unreadable',texts=texts);return True
        e,s,m=values['upgrade'],values['summon'],values['money']
        if self.previous_price is not None and s != self.previous_price:
            self.summons+=1
        self.previous_price=None
        if self.previous_upgrade==e:self.upgrade_stalls+=1
        else:self.upgrade_stalls=0
        self.previous_upgrade=None
        action=price_action(e,s,self.cfg)
        if self.summons<5 or self.upgrade_stalls>=2:action='summon'
        if time.monotonic()<self.full_until:action='upgrade'
        if action=='summon' and self.pending==s:
            # A failed summon (full board) must not prevent all strengthening.
            self.full_until=time.monotonic()+15;action='upgrade'
        self.pending=None
        cost=s if action=='summon' else e
        if m<cost:return True
        self.log('purchase',action=action,prices=values)
        self.s.tap(290 if action=='summon' else 153,741)
        if action=='summon':self.pending=s;self.previous_price=s
        else:self.previous_upgrade=e
        time.sleep(.45)
        return True

    def run(self):
        self.log('worker_ready',cells=board_cells(self.side))
        try:
            while time.monotonic()<self.deadline and not self.stop():
                if not self.step():return self.status
                time.sleep(.2)
            self.status='stopped';self.log('stopped');return self.status
        except Exception as e:
            self.status='error';self.log('exception',error=str(e));raise


def main():
    sys.stdout.reconfigure(encoding='utf8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-device',default='127.0.0.1:16384')
    p.add_argument('--guest-device',default='127.0.0.1:16416')
    p.add_argument('--host-name',default='踏实的龙利鱼')
    p.add_argument('--guest-name',default='幽美的竹笋')
    p.add_argument('--stage',type=int,default=2)
    p.add_argument('--minutes',type=float,default=20)
    p.add_argument('--battle-only',action='store_true')
    p.add_argument('--only-side',choices=('host','guest'),help='Adopt one device without controlling the partner')
    p.add_argument('--host-tactics',type=Path,default=ROOT/'games/bilibili_hero_merge/tactics/beginner.json')
    p.add_argument('--guest-tactics',type=Path,default=ROOT/'games/bilibili_hero_merge/tactics/veteran.json')
    p.add_argument('--runtime',type=Path,default=ROOT/'runtime/coop')
    a=p.parse_args()
    if a.only_side and not a.battle_only:p.error('--only-side requires --battle-only')
    if a.host_device==a.guest_device:p.error('Two different devices required')
    a.runtime.mkdir(parents=True,exist_ok=True)
    stop=lambda:(a.runtime/'STOP').exists()
    if stop():raise SystemExit('STOP exists; inspect before restart')
    with ExitStack() as stack:
        for d in (a.host_device,a.guest_device):
            lockpath=a.runtime/('device-'+hashlib.sha256(d.encode()).hexdigest()[:16]+'.lock')
            lock=stack.enter_context(lockpath.open('a+b'));lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise SystemExit('Device already controlled by another co-op runner')
        screens=[]
        for side,device in [('host',a.host_device),('guest',a.guest_device)]:
            out=a.runtime/side/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True,exist_ok=True)
            screens.append(Screen(MuMuPlatform(device),out))
        bots=[Battle(s,side,a,stop) for s,side in zip(screens,('host','guest'))]
        if not a.battle_only:
            setup_pair(*screens,a.host_name,a.guest_name,a.stage,bots[0].log,stop)
            for s in screens:
                s.scan()
                if not s.room(a.host_name,a.guest_name,a.stage):raise RuntimeError('Team changed before start')
            challenge=screens[0].find('挑战')
            if challenge is None:raise RuntimeError('No unique host challenge button')
            screens[0].click(challenge)
            time.sleep(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(b.run) for b in bots if not a.only_side or b.side==a.only_side]
            for f in futures:print('worker_result',f.result(),flush=True)

if __name__=='__main__':main()

