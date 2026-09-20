"""Configurable local strategy runner; ranks are tracked from verified actions."""
import argparse,json,subprocess,time,sys,msvcrt,re
from pathlib import Path
from farmer import Bot,ROOT,RUNTIME,cv2,np
from policy import price_action,merge_pair
from vision import Reader,tile_scores

class StrategicBot(Bot):
 def __init__(self,args):
  super().__init__(args)
  self.cfg=json.loads((ROOT/'strategy.json').read_text(encoding='utf8'))
  self.reader=Reader();self.units={};self.available={(x,603) for x in [87,130,173,216,259,302,345]}
  self.summons=0;self.pending_action=None;self.bad_prices=0;self.stage=self.cfg['stage'];self.last_wait=0;self.wait_settlement=False
  self.state_path=RUNTIME/'state.json';self.blocked_pairs={};self.repair_due={};self.last_repair=0;self.repair_mode=False
  if args.resume and self.state_path.exists():
   s=json.loads(self.state_path.read_text(encoding='utf8'))
   self.units={tuple(u['pos']):{k:v for k,v in u.items() if k!='pos'} for u in s['units']}
   self.available={tuple(p) for p in s['available']};self.summons=s['summons'];self.rounds=s['rounds'];self.pending_action=s['pending']
   self.repair_mode=s.get('repair_mode',False) or s.get('wait_settlement',False)
 def save(self):
  data={'units':[dict(pos=p,**u) for p,u in self.units.items()],'available':sorted(self.available),'summons':self.summons,'rounds':self.rounds,'pending':self.pending_action}
  data['repair_mode']=self.repair_mode
  tmp=self.state_path.with_suffix('.tmp')
  for attempt in range(3):
   try:
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(self.state_path)
    self.save_pending=False;return True
   except OSError as error:
    if attempt<2:time.sleep(.15*(attempt+1))
    else:
     self.save_pending=True;self.save_retry_at=time.monotonic()+10
     self.log('state_save_deferred',error=str(error));return False
 def shot(self):
  t=time.monotonic();b=self.platform.screenshot()
  self.raw=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR)
  if self.raw.shape[:2]!=(1920,1080):raise RuntimeError('Expected 1080x1920')
  self.im=cv2.resize(self.raw,(432,768),interpolation=cv2.INTER_AREA);self.frame+=1
  cv2.imwrite(str(self.out/'latest.png'),self.im)
  if self.frame%10==0:cv2.imwrite(str(self.out/f'frame-{self.frame:05d}.png'),self.im)
  return time.monotonic()-t
 def battle(self):return self.has(f'battle{self.stage}',(140,5,165,38),.84)
 def home(self):return self.has(f'home{self.stage}',(145,157,158,45),.84) and self.has('start',(133,585,169,55))
 def pause_stop(self,reason):
  self.shot()
  if self.battle():
   self.tap(216,405);self.tap(32,104);time.sleep(.3);self.shot()
  self.save();self.log('stopped',reason=reason,units=list(self.units.values()),summons=self.summons)
 def discover(self):
  expected=7+self.summons//5
  if len(self.available)>=expected:return
  for _,pos,corr,error in tile_scores(self.im,self.templates['tile_frame']):
   if pos not in self.available and corr>.35 and error<38:
    self.available.add(pos);self.log('wall_expanded',cell=pos,correlation=round(corr,2));self.save()
    if len(self.available)>=expected:break
 def recover_battle(self,reason):
  if not self.args.until_stamina:
   self.pause_stop(reason);return False
  p=self.pending_action
  if p and p['kind']=='merge':
   for pos in (tuple(p['a']),tuple(p['b'])):
    if pos in self.units:self.units[pos]['uncertain']=True
  self.repair_mode=True;self.pending_action=None;self.save()
  self.log('partial_recovery',reason=reason)
  return True
 def repair_one(self):
  now=time.monotonic()
  if now-self.last_repair<12:return False
  candidates=set(self.available)
  if self.repair_mode:candidates.update(pos for _,pos,_,_ in tile_scores(self.im,self.templates['tile_frame']))
  candidates=[p for p in candidates if now-self.repair_due.get(p,-1000)>45]
  if not candidates:return False
  def priority(pos):
   u=self.units.get(pos)
   return (0 if u and u.get('uncertain') else 1 if pos not in self.units and pos in self.available else 2 if pos not in self.available else 3,self.repair_due.get(pos,-1000),pos)
  pos=min(candidates,key=priority);self.last_repair=now;self.repair_due[pos]=now
  old=self.units.get(pos);hero=self.identify(pos)
  self.shot() # identify() leaves its captured frame showing the detail panel.
  if hero:
   tier=old['tier'] if old and old['hero']==hero and not old.get('uncertain') else 0
   self.units[pos]={'hero':hero,'tier':tier};self.available.add(pos)
   self.log('cell_repaired',cell=pos,hero=hero,tier=tier)
  elif old and self.battle() and not self.occupied(*pos):
   # Require two spaced empty observations before forgetting a tracked unit.
   old['empty_checks']=old.get('empty_checks',0)+1
   if old['empty_checks']>=2:self.units.pop(pos);self.log('empty_cell_repaired',cell=pos)
  elif old:old['empty_checks']=0
  self.save();return True
 def identify(self,pos):
  self.tap(*pos);time.sleep(.2);self.shot()
  name=self.reader.text(self.raw,(115,319,280,366))
  hero=next((k for k,v in self.cfg['heroes'].items() if v['name'] in name),None)
  if hero:
   cv2.imwrite(str(ROOT/'assets'/f'portrait_{hero}.png'),self.raw[128:292,111:275])
  self.tap(15,400);time.sleep(.1)
  self.log('identify_unit',cell=pos,read_name=name,hero=hero)
  return hero
 def finish_pending(self):
  p=self.pending_action
  if p['kind']=='summon':
   before={tuple(q) for q in p.get('occupied_before',[])}
   candidates=[q for q in self.available if q not in self.units and q not in before and self.occupied(*q)]
   candidates.sort(key=lambda q:float(cv2.cvtColor(self.im[q[1]-20:q[1]+4,q[0]-14:q[0]+14],cv2.COLOR_BGR2GRAY).std()),reverse=True)
   for pos in candidates[:2]:
    hero=self.identify(pos)
    if hero:
     self.units[pos]={'hero':hero,'tier':1};self.summons+=1;self.pending_action=None;self.save()
     self.log('summon_verified',hero=hero,cell=pos,total=self.summons);return True
   self.shot();values,_=self.reader.prices(self.raw)
   # Unchanged next price and summon counter means the button did not fire.
   counter=self.reader.text(self.raw,(490,1835,590,1894))
   if str((self.summons+1)%5)+'/5' in counter and values['summon'] is not None and values['summon']!=p['price']:
    self.summons+=1;self.pending_action=None;self.repair_mode=True;self.save();self.log('summon_confirmed_role_pending',total=self.summons);return True
   if p.get('bonus_seen') and str((self.summons+1)%5)+'/5' in counter and values['summon']!=p['price']:
    self.summons+=1;self.pending_action=None;self.save();self.log('bonus_summon_verified',total=self.summons);return True
   if str(self.summons%5)+'/5' in counter and values['summon']==p['price']:
    self.pending_action=None;self.save();self.log('summon_not_applied');return True
  else:
   a,b=tuple(p['a']),tuple(p['b'])
   if not self.occupied(*a):
    hero=self.identify(b)
    if hero:
     self.units.pop(a,None);self.units[b]={'hero':hero,'tier':p['tier']+1};self.pending_action=None;self.merges+=1;self.save()
     self.log('merge_verified',hero=hero,tier=p['tier']+1,source=a,target=b);return True
   else:
    p['checks']=p.get('checks',0)+1
    if p['checks']<3:self.save();return True
    self.blocked_pairs[(a,b)]=time.monotonic()+60
    for pos in (a,b):
     if pos in self.units:self.units[pos]['uncertain']=True
    self.repair_mode=True
    self.pending_action=None;self.save();self.log('merge_not_applied');return True
  p['tries']=p.get('tries',0)+1;self.save()
  if p['tries']>=4:return self.recover_battle('pending_action_cannot_be_verified')
  return True
 def choose_buff(self,extra=False):
  cards=[]
  for i,(x1,x2) in enumerate([(30,356),(375,703),(725,1050)]):
   text=self.reader.lines(self.raw,(x1,510,x2,1160))
   matches=[h for h in self.cfg['buff_priority'] if any(w in text for w in self.cfg['heroes'][h]['buff_keywords'])]
   if not matches:
    def hist(patch):
     h=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
     mask=((h[:,:,0]>25)&(h[:,:,1]>60)&(h[:,:,2]>45)&(h[:,:,2]<245)).astype(np.uint8)*255
     z=cv2.calcHist([h],[0],mask,[36],[0,180]);return cv2.normalize(z,z).flatten()
    h=hist(self.raw[630:795,x1+30:x2-30]);scores=[]
    for role in self.cfg['buff_priority']:
     path=ROOT/'assets'/f'portrait_{role}.png'
     if path.exists():scores.append((float(np.dot(h,hist(cv2.imread(str(path))))),role))
    scores.sort(reverse=True)
    if scores and scores[0][0]>.75 and (len(scores)<2 or scores[0][0]-scores[1][0]>.1):matches=[scores[0][1]]
   cards.append({'index':i,'text':text,'hero':matches[0] if matches else None})
  if extra:index=self.cfg['same_role_buff_default_index']
  else:
   ranked=[(self.cfg['buff_priority'].index(c['hero']),c['index']) for c in cards if c['hero']]
   index=min(ranked)[1] if ranked else self.cfg['same_role_buff_default_index']
  self.log('buff_choice',cards=cards,selected=index,extra=extra)
  self.tap([77,216,355][index],340);time.sleep(.5)
 def do_merge(self,pair,reason):
  a,b=pair;u=self.units[a]
  self.pending_action={'kind':'merge','a':a,'b':b,'tier':u['tier'],'hero':u['hero']};self.save()
  self.log('merge_decision',reason=reason,hero=u['hero'],tier=u['tier'],source=a,target=b)
  self.platform.swipe(round(a[0]*2.5),round(a[1]*2.5),round(b[0]*2.5),round(b[1]*2.5),650);time.sleep(1.2)
 def pair(self,full=False):
  # Policy decides only among currently verified units. Exclude recently rejected pairs.
  blocked=[pair for pair,until in self.blocked_pairs.items() if until>time.monotonic()]
  return merge_pair(self.units,self.cfg,full,blocked)
 def decide(self):
  self.discover()
  if self.pending_action:return self.finish_pending()
  if self.repair_mode and self.repair_one():return True
  pair=self.pair()
  if pair:self.do_merge(pair,'excess_support_lowest_tier');return True
  values,texts=self.reader.prices(self.raw)
  if any(v is None for v in values.values()):
   self.bad_prices+=1;self.log('price_unreadable',texts=texts)
   if self.bad_prices>=5:return self.recover_battle('price_ocr_failed')
   return True
  self.bad_prices=0;e,s,m=values['upgrade'],values['summon'],values['money']
  wanted=price_action(e,s,self.cfg)
  if self.summons<5 or (e==100 and len(self.units)<5):wanted='summon' # Respect the initial strengthen unlock.
  occupied=set(self.units)|{p for p in self.available if self.occupied(*p)}
  full=len(occupied)>=len(self.available)
  if wanted=='summon' and full:
   if m<s:return True
   pair=self.pair(True)
   if pair:self.do_merge(pair,'full_board_needs_summon');return True
   if len(self.available)<7+self.summons//5:self.repair_mode=True
   wanted='upgrade'
  price=e if wanted=='upgrade' else s
  if m<price:
   if time.monotonic()-self.last_wait>10:self.log('wait_currency',next_upgrade=e,next_summon=s,money=m,wanted=wanted);self.last_wait=time.monotonic()
   return True
  self.log('purchase_decision',action=wanted,next_upgrade=e,next_summon=s,money=m,occupied=len(self.units),slots=len(self.available))
  if wanted=='summon':self.pending_action={'kind':'summon','price':s,'occupied_before':list(occupied)};self.save();self.tap(307,741)
  else:self.tap(130,741)
  time.sleep(.5);return True
 def run(self):
  self.log('start_strategy',config=self.cfg,resume=self.args.resume)
  if self.args.hide:self.platform.hide()
  start=time.monotonic();unknown=0;transition_until=0
  while self.args.until_stamina or time.monotonic()-start<self.args.minutes*60:
   if (RUNTIME/'STOP').exists():self.pause_stop('stop_file');return
   self.shot()
   if getattr(self,'save_pending',False) and time.monotonic()>=self.save_retry_at:self.save()
   if self.has('loot_close',(130,600,180,55),.84) and '关闭' in self.reader.lines(self.raw,(325,1500,775,1638)):
    if self.pending_action:self.pending_action['bonus_seen']=True;self.save()
    self.tap(15,400);self.log('close_summon_reward');time.sleep(.7);continue
   if self.has('pause',(145,525,155,58)):
    if not self.args.resume:self.log('paused_game_requires_resume');return
    self.tap(308,659);unknown=0;transition_until=time.monotonic()+20;time.sleep(.3);continue
   extra=self.has('extra_choice',(120,125,195,65),.83)
   if self.has('choice',(160,125,120,80),.83) or extra:
    self.choose_buff(extra);unknown=0;continue
   if self.has('return',(100,640,240,125),.86):
    title=self.reader.lines(self.raw,(220,230,860,420));won='胜利' in title;lost='失败' in title
    self.log('settlement',title=title,victory=won);cv2.imwrite(str(self.out/f'result-{self.rounds}.png'),self.im)
    if won:cv2.imwrite(str(ROOT/'assets'/'victory.png'),self.im[116:152,149:281])
    time.sleep(2)
    for _ in range(3):
     self.tap(215,710);time.sleep(1);self.shot()
     if self.home():self.log('return_verified');break
     if not self.has('return',(100,640,240,125),.86):break
    self.pending_action=None;self.save();unknown=0
    if not won and not lost:self.log('settlement_unreadable',title=title);return
    if not self.args.until_stamina and (not won or self.rounds>=self.args.runs):self.log('finished',victory=won,rounds=self.rounds);return
    continue
   if self.has('repeat',(45,400,155,55)):
    self.tap(124,429);unknown=0;transition_until=time.monotonic()+20;time.sleep(.7);continue
   if self.home():
    stamina=self.reader.text(self.raw,(925,163,1060,212));match=re.search(r'(\d+)\s*/',stamina)
    if not match:self.log('stamina_unreadable',text=stamina);return
    if int(match[1])<10:self.log('stamina_exhausted',remaining=int(match[1]));return
    if not self.args.until_stamina and self.rounds>=self.args.runs:self.log('run_limit');return
    self.units={};self.available={(x,603) for x in [87,130,173,216,259,302,345]};self.summons=0;self.pending_action=None;self.blocked_pairs={};self.bad_prices=0;self.wait_settlement=False;self.repair_mode=False;self.repair_due={};self.last_repair=0;self.rounds+=1;self.save()
    self.log('start_stage',stage=self.stage,stamina=int(match[1]),round=self.rounds);self.tap(216,610);unknown=0;transition_until=time.monotonic()+20;time.sleep(.7);continue
   if self.battle():
    unknown=0
    if not self.decide():return
   else:
    if time.monotonic()<transition_until:time.sleep(.2);continue
    detail_name=self.reader.text(self.raw,(115,319,280,366))
    if any(v['name'] in detail_name for v in self.cfg['heroes'].values()):
     self.tap(15,400);self.log('close_unit_details',name=detail_name);time.sleep(.3);continue
    unknown+=1
    if unknown>=7:
     cv2.imwrite(str(self.out/'unknown-before-pause.png'),self.im)
     self.pause_stop('unknown_screen');return
   time.sleep(.2)
  self.pause_stop('time_limit')

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf8')
 p=argparse.ArgumentParser();p.add_argument('--device',default='emulator-5554');p.add_argument('--runs',type=int,default=1);p.add_argument('--minutes',type=int,default=15);p.add_argument('--hide',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--until-stamina',action='store_true',help='Repeat wins or losses until stamina is below 10; never refill.');a=p.parse_args()
 lock=(RUNTIME/'runner.lock').open('a+b');lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:raise SystemExit('Another farmer is running')
 (RUNTIME/'STOP').unlink(missing_ok=True)
 b=StrategicBot(a)
 try:b.run()
 except Exception as e:
  b.log('exception',error=str(e));b.pause_stop('exception');raise
 finally:lock.close()
