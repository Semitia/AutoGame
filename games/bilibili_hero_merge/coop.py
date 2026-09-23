"""Single-run co-op coordinator; offline inspection never connects to a device."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from autogame.platforms.mumu import MuMuPlatform
from autogame.platforms.lease import device_lease
from coop_ui import Screen, setup_pair
from coop_engine import Engine, Observation
from coop_tracking import Tracker
from coop_vision import BoardVision, read_prices, layer, wave_number, modal_token, BUTTONS, owner_side
from tactics import load_tactics, choose_card


def jsonable(value):
    if isinstance(value,dict):return {str(k):jsonable(v) for k,v in value.items()}
    if isinstance(value,(set,tuple,list)):return [jsonable(v) for v in value]
    return value


class Battle:
    def __init__(self, screen, side, args, stop):
        self.s,self.side,self.args,self.stop=screen,side,args,stop
        self.device=getattr(args,side+'_device')
        self.cfg,self.fingerprint=load_tactics(getattr(args,side+'_tactics'))
        self.engine=Engine(self.cfg,side,max_checks=8)
        self.vision=BoardVision()
        self.tracker=Tracker()
        self.status='ready'
        self.deadline=time.monotonic()+args.minutes*60
        self.invalid_since=None
        self.last_board=None
        self.action_number=0
        self.last_obs=None
        self.run_id=uuid.uuid4().hex
        self.resume=None
        self.pending_log=None
        self.state_path=self.s.output/'state.json'
        path=getattr(args,side+'_state',None)
        if path:
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            identity=self.identity()
            if any(data.get(k)!=v for k,v in identity.items()):
                raise ValueError('Checkpoint belongs to another device, side, floor, team or tactics')
            if data.get('pending') or data.get('status')=='settled':
                raise ValueError('Cannot restore an in-flight action or settled run')
            if not 0<=time.time()-data.get('saved_at',0)<=120:
                raise ValueError('Checkpoint older than 120 seconds; stale ranks will not be reused')
            self.resume=data['tracker']
            self.run_id=data['run_id']

    def identity(self):
        return {'device':self.device,'side':self.side,'stage':self.args.stage,
                'host':self.args.host_name,'guest':self.args.guest_name,'tactics':self.fingerprint}

    def log(self,event,**data):
        record={'time':time.strftime('%H:%M:%S'),'side':self.side,'event':event,**jsonable(data)}
        with (self.s.output/'events.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')
        print(json.dumps(record,ensure_ascii=False),flush=True)

    def save(self):
        data={**self.identity(),'version':2,'run_id':self.run_id,'saved_at':time.time(),
              'status':self.status,'tracker':self.tracker.state(),'pending':self.engine.pending}
        temp=self.state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(jsonable(data),ensure_ascii=False,indent=2),encoding='utf8')
        temp.replace(self.state_path)  # failure stops before dispatching any action

    def capture(self,label):
        import cv2
        path=self.s.output/f'{self.action_number:04d}-{label}.png'
        if not cv2.imwrite(str(path),self.s.raw):
            raise OSError(f'Could not save action evidence: {path}')

    def top(self):
        return layer(self.s.labels,self.args.host_name,self.args.guest_name,self.args.stage)

    def observe(self):
        self.s.scan()
        top=self.top()
        if top!='battle':
            return Observation(top,token=modal_token(self.s.labels))
        if owner_side(self.s.raw)!=self.side:
            self.log('device_side_mismatch',expected=self.side,observed=owner_side(self.s.raw))
            return Observation('unknown')
        prices,texts=read_prices(self.s.reader,self.s.raw)
        board=self.vision.read(self.s.raw,self.side)
        # Reject dimmed background UI under an unrecognized overlay.
        bright=float(self.s.raw[1780:1900,300:420].mean())>65
        obs=Observation('battle',prices=prices,cells=board.cells,occupied=board.occupied,
                        board_verified=board.verified and bright)
        self.log('observation',prices=prices,texts=texts,cells=sorted(board.cells),
                 occupied=sorted(board.occupied),uncertain=sorted(board.uncertain),
                 board_verified=obs.board_verified)
        return obs

    def identify(self,pos):
        # Called only after two matching unobstructed board observations.
        if self.stop():raise RuntimeError('Stopped before unit inspection')
        if not self.last_obs or pos not in self.last_obs.occupied:
            raise ValueError('Unit inspection outside observed occupied cells')
        self.s.tap(*pos)
        time.sleep(.25)
        self.s.scan()
        name=self.s.reader.text(self.s.raw,(115,319,280,366))
        matches=[key for key,hero in self.cfg['heroes'].items() if hero['name'] in name]
        self.capture('unit-detail')
        self.log('identify_unit',cell=pos,text=name,heroes=matches)
        # Reuse the single-player detail-name crop and outside-close gesture.
        # Do not click through a reward/choice that appeared during inspection.
        if self.top() in ('reward','choice','settled','paused'):
            raise RuntimeError('Foreground changed during unit inspection; saved evidence')
        if len(matches)!=1:
            raise RuntimeError('Unit detail does not match configured lineup')
        if self.stop():raise RuntimeError('Stopped during unit inspection')
        self.s.tap(15,400)
        time.sleep(.25)
        self.s.scan()
        if self.top()!='battle':
            raise RuntimeError('Unit detail did not close to the same battle')
        return matches[0]

    def ready_observation(self,obs):
        if obs.layer!='battle':
            self.last_board=None
            return True
        if not obs.board_verified or any(v is None for v in obs.prices.values()):
            self.last_board=None
            return False
        signature=(frozenset(obs.cells),frozenset(obs.occupied),
                   obs.prices['upgrade'],obs.prices['summon'])
        stable=self.last_board==signature
        self.last_board=signature
        return stable

    def step(self):
        obs=self.observe()
        if self.stop():return self.halt('stop_requested')
        if obs.layer=='paused':return self.halt('user_paused')
        # Bound unknown/OCR/animation waiting without dispatching any inputs.
        if obs.layer=='unknown' or not self.ready_observation(obs):
            if self.invalid_since is None:self.invalid_since=time.monotonic()
            if time.monotonic()-self.invalid_since>20:
                return self.halt('observation_did_not_stabilize')
            return True
        self.invalid_since=None
        self.last_obs=obs
        if obs.layer=='battle':
            current_wave=wave_number(self.s.labels)
            if self.resume:
                if current_wave is None or current_wave<(self.resume.get('wave') or 0):
                    return self.halt('checkpoint_wave_mismatch')
                self.tracker.restore(self.resume,obs,self.identify)
                self.resume=None
            elif self.tracker.summons is None:
                self.tracker.initialize(obs)
            pending=self.engine.pending
            while pending and pending['kind'] in ('close_reward','choose_buff'):
                pending=pending['previous']
            obs=self.tracker.reconcile(obs,pending,self.identify)
            self.tracker.wave=current_wave
            if self.tracker.summons==0 and not self.engine.pending:
                self.tracker.commit(obs)
        action=self.engine.next(obs)
        row=asdict(obs)
        row['units']=[dict(pos=list(pos),**u) for pos,u in obs.units.items()]
        row['expected']=action['kind']
        with (self.s.output/'observations.jsonl').open('a',encoding='utf8') as f:
            f.write(json.dumps(jsonable(row),ensure_ascii=False)+'\n')
        self.log('decision',**action)
        kind=action['kind']
        if kind in ('stop','settled'):
            return self.halt(action.get('reason',kind),status=kind)
        if kind=='verified':
            self.tracker.commit(obs)
            self.capture('verified')
            self.pending_log=None
        elif kind not in ('wait',):
            if obs.layer=='battle' and self.engine.pending:
                # Retain the before state until the engine confirms its delta.
                self.tracker.cells=set(obs.cells)
            self.action_number+=1
            self.capture('before-'+kind)
            self.pending_log=kind
            self.save()
            if self.stop():return self.halt('stop_before_action')
            if kind=='choose_buff':
                cards=[self.s.reader.lines(self.s.raw,(a,510,b,1160))
                       for a,b in [(30,356),(375,703),(725,1050)]]
                words=[w for h in self.cfg['heroes'].values() for w in [h['name'],*h['buff_keywords']]]
                if not any(w in t for t in cards for w in words):
                    return self.halt('tactics_do_not_match_cards')
                selected=choose_card(cards,self.cfg)
                self.log('buff_choice',cards=cards,selected=selected)
                self.s.tap([77,216,355][selected],340)
            elif kind=='close_reward':self.s.tap(216,628)
            elif kind in BUTTONS:self.s.tap(*BUTTONS[kind])
            elif kind=='merge':
                if action['source'] not in obs.occupied or action['target'] not in obs.occupied:
                    raise RuntimeError('Merge endpoints no longer occupied')
                self.s.swipe(action['source'],action['target'])
            else:raise RuntimeError(f'Unsupported action: {kind}')
            self.last_board=None
        self.status='active'
        self.save()
        return True

    def halt(self,reason,status='stopped'):
        self.status=status
        self.save()
        if getattr(self.s,'raw',None) is not None:self.capture(status)
        self.log('stopped',reason=reason,status=status,state=str(self.state_path))
        return False

    def run(self):
        self.deadline=time.monotonic()+self.args.minutes*60
        self.log('worker_ready',tactics=self.fingerprint,device=self.device)
        try:
            while time.monotonic()<self.deadline and not self.stop():
                if not self.step():return self.status
                time.sleep(.5)
            self.halt('stop_requested' if self.stop() else 'time_limit')
            return self.status
        except Exception as error:
            self.status='error'
            self.log('exception',error=str(error))
            self.save()
            if getattr(self.s,'raw',None) is not None:self.capture('error')
            raise


def inspect_image(path,side,output):
    import cv2
    raw=cv2.imread(str(path))
    if raw is None or abs(raw.shape[1]/raw.shape[0]-9/16)>.01:
        raise ValueError('Inspect a cropped portrait game image, not a desktop screenshot')
    raw=cv2.resize(raw,(1080,1920),interpolation=cv2.INTER_AREA)
    board=BoardVision().read(raw,side)
    output.mkdir(parents=True,exist_ok=True)
    for x,y in board.cells:
        color=(0,0,255) if (x,y) in board.uncertain else (0,200,255) if (x,y) in board.occupied else (0,255,0)
        cv2.rectangle(raw,(round((x-14)*2.5),round((y-15)*2.5)),
                      (round((x+14)*2.5),round((y+24)*2.5)),color,2)
    cv2.imwrite(str(output/f'{side}-board.png'),raw)
    data={'cells':sorted(board.cells),'occupied':sorted(board.occupied),
          'uncertain':sorted(board.uncertain),'verified':board.verified,'scores':board.scores}
    (output/f'{side}-board.json').write_text(json.dumps(jsonable(data),indent=2),encoding='utf8')
    print(json.dumps(jsonable(data)),flush=True)


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-device');p.add_argument('--guest-device')
    p.add_argument('--host-name',default='踏实的龙利鱼');p.add_argument('--guest-name',default='幽美的竹笋')
    p.add_argument('--stage',type=int,default=2);p.add_argument('--minutes',type=float,default=20)
    p.add_argument('--battle-only',action='store_true')
    p.add_argument('--only-side',choices=('host','guest'))
    p.add_argument('--host-tactics',type=Path);p.add_argument('--guest-tactics',type=Path)
    p.add_argument('--host-state',type=Path);p.add_argument('--guest-state',type=Path)
    p.add_argument('--inspect-image',type=Path,help='Offline board detection only; no device construction')
    p.add_argument('--runtime',type=Path,default=ROOT/'runtime/coop')
    a=p.parse_args()
    if a.inspect_image:
        inspect_image(a.inspect_image,a.only_side or 'host',a.runtime)
        return
    if a.only_side and not a.battle_only:p.error('--only-side requires --battle-only')
    if (a.host_state or a.guest_state) and not a.battle_only:p.error('Checkpoint restore requires --battle-only')
    selected=[(side,getattr(a,side+'_device')) for side in ('host','guest') if not a.only_side or a.only_side==side]
    for side,device in selected:
        if not device:p.error('--'+side+'-device is required; query current ADB serials first')
        profile=getattr(a,side+'_tactics')
        if profile is None:p.error('--'+side+'-tactics is required')
        load_tactics(profile)
    if a.minutes<=0 or a.stage<1:p.error('minutes and stage must be positive')
    if len(selected)==2 and a.host_device==a.guest_device:p.error('Two different devices required')
    a.runtime.mkdir(parents=True,exist_ok=True)
    aborted=threading.Event()
    stop=lambda:aborted.is_set() or (a.runtime/'STOP').exists()
    if stop():raise SystemExit('STOP exists; inspect before restart')
    with ExitStack() as stack:
        for _,device in selected:stack.enter_context(device_lease(device))
        screens={}
        stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        for side,device in selected:
            out=a.runtime/side/stamp;out.mkdir(parents=True,exist_ok=True)
            screens[side]=Screen(MuMuPlatform(device),out)
        bots={side:Battle(screen,side,a,stop) for side,screen in screens.items()}
        if not a.battle_only:
            host,guest=screens['host'],screens['guest']
            setup_pair(host,guest,a.host_name,a.guest_name,a.stage,bots['host'].log,stop)
            for screen in screens.values():
                screen.scan()
                if not screen.room(a.host_name,a.guest_name,a.stage):raise RuntimeError('Team changed before challenge')
            button=host.find('挑战')
            if button is None:raise RuntimeError('No unique host challenge button')
            if stop():raise RuntimeError('Stopped before challenge')
            host.click(button)  # exactly one new run; never auto retry a ticket
            time.sleep(2)
        def worker(bot):
            try:
                result=bot.run()
                if result!='settled':aborted.set()
                return result
            except Exception:
                aborted.set()
                raise
        with ThreadPoolExecutor(max_workers=len(bots)) as pool:
            futures=[pool.submit(worker,bot) for bot in bots.values()]
            for future in futures:print('worker_result',future.result(),flush=True)


if __name__=='__main__':main()
