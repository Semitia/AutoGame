"""Role-configured battle runner: single battle, bounded repeat, or stamina farm."""
import argparse
from collections import Counter
import json
import msvcrt
from pathlib import Path
import re
import sys
import time
from strategic import StrategicBot, ROOT, RUNTIME, cv2
from tactics import load_tactics, choose_card
from vision import Reader


class TacticalReader(Reader):
    def prices(self, image):
        values, texts = super().prices(image)
        # The old wide crop sometimes reads 90 as 9. Require agreement between
        # independent crops; never multiply an uncertain number by ten.
        if values['money'] is None or values['money'] < 100:
            alternatives = [self.text(image, box) for box in
                            [(163,1670,245,1717), (160,1665,250,1725)]]
            votes = Counter(v for v in [values['money'], *map(self.number, alternatives)] if v is not None)
            if votes:
                number, count = votes.most_common(1)[0]
                if count >= 2:
                    values['money'] = number
            texts['money_checks'] = alternatives
        return values, texts


class TacticalBot(StrategicBot):
    def __init__(self, args):
        # Never load the legacy runner's shared state.
        super().__init__(args)
        self.cfg, self.fingerprint = load_tactics(args.tactics)
        self.stage = args.stage
        self.cfg['stage'] = self.stage
        self.reader = TacticalReader()
        self.state_path = self.out/'state.json'
        self.battle_template = None
        self.completed = 0
        self.status = 'active'
        self.rounds = 0
        if args.resume_state:
            state = json.loads(Path(args.resume_state).read_text(encoding='utf-8-sig'))
            self.validate_resume(state, args.device, self.stage, self.fingerprint)
            self.units = {tuple(u['pos']): {k:v for k,v in u.items() if k!='pos'} for u in state['units']}
            self.available = {tuple(p) for p in state['available']}
            self.summons = state['summons']
            self.pending_action = state['pending']
            self.repair_mode = state.get('repair_mode',False)
            self.rounds = 1

    @staticmethod
    def validate_resume(state, device, stage, fingerprint):
        expected = {'device':device, 'stage':stage, 'tactics':fingerprint}
        if any(state.get(k)!=v for k,v in expected.items()):
            raise ValueError('Resume state belongs to a different device, stage or tactics')
        if state.get('status') not in ('active','paused'):
            raise ValueError('Cannot resume a completed battle')

    def save(self):
        data = {'version':1, 'device':self.args.device, 'stage':self.stage,
                'tactics':self.fingerprint, 'status':self.status,
                'units':[dict(pos=p,**u) for p,u in self.units.items()],
                'available':sorted(self.available), 'summons':self.summons,
                'rounds':self.rounds, 'pending':self.pending_action,
                'repair_mode':self.repair_mode}
        tmp = self.state_path.with_suffix('.tmp')
        for attempt in range(3):
            try:
                tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
                tmp.replace(self.state_path)
                self.save_pending=False
                return True
            except OSError as error:
                if attempt<2:time.sleep(.15)
                else:
                    self.save_pending=True;self.save_retry_at=time.monotonic()+10
                    self.log('state_save_deferred',error=str(error));return False

    def stage_number(self, home=False):
        box=(300,350,830,520) if home else (300,10,800,110)
        title=self.reader.lines(self.raw,box)
        match=re.search(r'(\d+)\s*(?:[.、．]\s*)?(?=[\u4e00-\u9fff])',title)
        return (int(match[1]) if match else None),title

    def battle(self):
        patch=self.im[5:38,140:305]
        if self.battle_template is not None:
            if cv2.matchTemplate(patch,self.battle_template,cv2.TM_CCOEFF_NORMED).max()>.90:return True
        number,title=self.stage_number()
        if number==self.stage:
            self.battle_template=patch.copy()
            self.log('stage_verified',title=title)
            return True
        return False

    def home(self):
        return self.has('start',(133,585,169,55)) or ('开始挑战' in self.reader.lines(self.raw,(325,1440,770,1590)))

    def identify(self,pos):
        self.tap(*pos);time.sleep(.2);self.shot()
        name=self.reader.text(self.raw,(115,319,280,366))
        hero=next((k for k,v in self.cfg['heroes'].items() if v['name'] in name),None)
        self.tap(15,400);time.sleep(.5)
        self.log('identify_unit',cell=pos,read_name=name,hero=hero)
        return hero

    def repair_one(self):
        # Repair occupied known wall cells only. Empty/off-wall scans used to
        # consume several seconds each while the battle continued underneath.
        now=time.monotonic()
        if now-self.last_repair<12:return False
        candidates=[p for p in self.available
                    if now-self.repair_due.get(p,-1000)>20
                    and ((p not in self.units and self.occupied(*p))
                         or self.units.get(p,{}).get('uncertain'))]
        if not candidates:
            unresolved=any(p not in self.units and self.occupied(*p) for p in self.available)
            if not unresolved and not any(u.get('uncertain') for u in self.units.values()):
                self.repair_mode=False;self.save()
            return False
        pos=min(candidates,key=lambda p:self.repair_due.get(p,-1000))
        self.last_repair=now;self.repair_due[pos]=now
        old=self.units.get(pos);hero=self.identify(pos);self.shot()
        if hero:
            tier=old['tier'] if old and old['hero']==hero and not old.get('uncertain') else 0
            self.units[pos]={'hero':hero,'tier':tier}
            self.log('cell_repaired',cell=pos,hero=hero,tier=tier)
        elif old and self.battle() and not self.occupied(*pos):
            old['empty_checks']=old.get('empty_checks',0)+1
            if old['empty_checks']>=2:self.units.pop(pos)
        self.save();return True

    def choose_buff(self,extra=False):
        cards=[self.reader.lines(self.raw,(x1,510,x2,1160))
               for x1,x2 in [(30,356),(375,703),(725,1050)]]
        index=choose_card(cards,self.cfg)
        self.log('buff_choice',cards=cards,selected=index,extra=extra)
        self.tap([77,216,355][index],340);time.sleep(.4)

    def close_unit_details(self):
        name=self.reader.text(self.raw,(115,319,280,366))
        if any(hero['name'] in name for hero in self.cfg['heroes'].values()):
            self.tap(15,400);time.sleep(.5)
            self.log('close_unit_details',name=name)
            return True
        return False

    def pause_stop(self,reason):
        self.shot()
        if not self.battle() and self.close_unit_details():self.shot()
        if self.has('pause',(145,525,155,58)):
            self.status='paused'
        elif self.battle() and not self.has('choice',(160,125,120,80),.83) and not self.has('extra_choice',(120,125,195,65),.83):
            self.tap(32,104);time.sleep(.3);self.shot()
            self.status='paused' if self.has('pause',(145,525,155,58)) else 'active'
        self.save();self.log('stopped',reason=reason,status=self.status,state=str(self.state_path))

    def reset_board(self):
        self.units={};self.available={(x,603) for x in [87,130,173,216,259,302,345]}
        self.summons=0;self.pending_action=None;self.blocked_pairs={};self.bad_prices=0
        self.repair_mode=False;self.repair_due={};self.last_repair=0
        self.battle_template=None;self.status='active';self.rounds+=1
        self.save()

    def start_home(self, deadline):
        self.shot()
        overlay=self.reader.lines(self.raw,(200,250,1000,650))
        if '变强攻略' in overlay:
            self.tap(395,180);time.sleep(.8);self.shot()
            self.log('close_growth_guide')
        if not self.home():
            self.log('stopped',reason='home_not_recognized');return False
        number,title=self.stage_number(home=True)
        # Only replay the immediately previous stage using its visible arrow.
        # More complex selection is left to the supervising agent.
        if number==self.stage+1:
            self.tap(90,616);time.sleep(.6);self.shot()
            number,title=self.stage_number(home=True)
        if number!=self.stage or not self.home():
            self.log('stopped',reason='wrong_home_stage',title=title);return False
        stamina=self.reader.text(self.raw,(865,95,1065,150))
        match=re.search(r'(\d+)\s*/\s*(\d+)',stamina)
        if not match:
            stamina=self.reader.text(self.raw,(925,163,1060,212))
            match=re.search(r'(\d+)\s*/\s*(\d+)',stamina)
        if not match:
            self.log('stopped',reason='stamina_unreadable',text=stamina);return False
        if int(match[1])<10:
            self.log('stamina_exhausted',remaining=int(match[1]));return False
        if time.monotonic()>=deadline:return False
        self.reset_board()
        self.log('start_stage',stage=self.stage,stamina=int(match[1]),round=self.rounds)
        self.tap(216,610)
        transition=min(deadline,time.monotonic()+20)
        while time.monotonic()<transition:
            time.sleep(.3);self.shot()
            if (RUNTIME/'STOP').exists():self.pause_stop('stop_file');return False
            if self.battle():return True
            if self.has('repeat',(45,400,155,55)):
                self.tap(124,429);time.sleep(.8)
        self.pause_stop('start_transition_timeout');return False

    def prepare(self,deadline):
        if self.args.start_home:return self.start_home(deadline)
        self.shot()
        number,title=self.stage_number()
        if number!=self.stage:
            self.log('refused',reason='wrong_battle_stage',title=title);return False
        paused=self.has('pause',(145,525,155,58))
        if getattr(self.args,'adopt_paused',False):
            if not paused:
                self.log('refused',reason='adopt_requires_pause');return False
            self.reset_board()
            self.tap(308,659);time.sleep(.5);self.shot()
            count=self.reader.lines(self.raw,(470,1800,640,1915))
            match=re.search(r'(\d+)\s*/\s*5',count)
            if not match:
                self.pause_stop('adopt_counter_unreadable');return False
            self.summons=int(match[1])
            self.discover()
            occupied=[p for p in sorted(self.available) if self.occupied(*p)]
            for pos in occupied:
                hero=self.identify(pos)
                if hero:self.units[pos]={'hero':hero,'tier':0}
            self.shot();self.repair_mode=True;self.save()
            self.log('adopted_live_board',summons=self.summons,units=list(self.units.values()))
            return True
        if self.args.resume_state:
            if not paused:
                self.log('refused',reason='resume_requires_paused_battle');return False
            # Preserve only state the same device/stage/tactics produced.
            self.log('resume_battle',source=str(self.args.resume_state),summons=self.summons)
        else:
            if any(self.occupied(x,603) for x in [87,130,173,216,259,302,345]):
                self.log('refused',reason='starting_board_not_empty');return False
            self.reset_board()
        if paused:self.tap(308,659);time.sleep(.3)
        self.battle_template=None
        return True

    @staticmethod
    def should_repeat(completed,runs,until_stamina,victory,stop_on_loss):
        return not (stop_on_loss and not victory) and (until_stamina or completed<runs)

    def run(self):
        self.log('start_tactical',device=self.args.device,stage=self.stage,
                 tactics=str(self.args.tactics),config=self.cfg)
        deadline=time.monotonic()+self.args.minutes*60
        if not self.prepare(deadline):return
        unknown=0
        while time.monotonic()<deadline:
            self.shot()
            if (RUNTIME/'STOP').exists():self.pause_stop('stop_file');return
            if getattr(self,'save_pending',False) and time.monotonic()>=self.save_retry_at:self.save()
            if self.has('pause',(145,525,155,58)):
                self.status='paused';self.save();self.log('stopped',reason='user_paused');return
            if self.has('return',(100,640,240,125),.86):
                title=self.reader.lines(self.raw,(220,230,860,420))
                if not ('胜利' in title or '失败' in title):
                    self.log('stopped',reason='settlement_unreadable',title=title);return
                victory='胜利' in title
                detail=self.reader.lines(self.raw,(220,420,900,610))
                self.completed+=1;self.status='settled';self.pending_action=None;self.save()
                cv2.imwrite(str(self.out/f'result-{self.completed}.png'),self.raw)
                self.log('settlement',title=title,detail=detail,victory=victory,completed=self.completed)
                if not self.should_repeat(self.completed,self.args.runs,self.args.until_stamina,victory,self.args.stop_on_loss):return
                self.tap(215,710);time.sleep(1)
                if not self.start_home(deadline):return
                unknown=0;continue
            extra=self.has('extra_choice',(120,125,195,65),.83)
            if self.has('choice',(160,125,120,80),.83) or extra:
                self.choose_buff(extra);unknown=0;continue
            if self.has('loot_close',(130,600,180,55),.84) and '关闭' in self.reader.lines(self.raw,(325,1500,775,1638)):
                if self.pending_action:self.pending_action['bonus_seen']=True
                self.tap(15,400);time.sleep(.4);continue
            if self.battle():
                unknown=0
                if not self.decide():return
            else:
                if self.close_unit_details():
                    unknown=0;continue
                unknown+=1
                if unknown>=4:self.pause_stop('unknown_screen');return
            time.sleep(.15)
        self.pause_stop('time_limit')


def main():
    sys.stdout.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',required=True)
    parser.add_argument('--stage',type=int,required=True)
    parser.add_argument('--tactics',type=Path,required=True)
    parser.add_argument('--minutes',type=float,default=20)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--start-home',action='store_true')
    mode.add_argument('--empty-board',action='store_true')
    mode.add_argument('--adopt-paused',action='store_true')
    mode.add_argument('--resume-state',type=Path)
    count=parser.add_mutually_exclusive_group()
    count.add_argument('--runs',type=int,default=1)
    count.add_argument('--until-stamina',action='store_true')
    parser.add_argument('--stop-on-loss',action='store_true')
    args=parser.parse_args()
    if args.stage<1 or args.minutes<=0 or args.runs<1:parser.error('stage, minutes and runs must be positive')
    args.resume=False;args.hide=False
    lock=(RUNTIME/'runner.lock').open('a+b');lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:raise SystemExit('Another farmer is running')
    try:
        if (RUNTIME/'STOP').exists():raise SystemExit('STOP exists; inspect before restarting')
        bot=TacticalBot(args)
        try:bot.run()
        except Exception as error:
            bot.log('exception',error=str(error));bot.pause_stop('exception');raise
    finally:lock.close()

if __name__=='__main__':main()


