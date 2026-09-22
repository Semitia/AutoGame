"""Game-specific visual primitives. Coordinates use a 432x768 reference."""
import argparse,io,json,subprocess,time,sys,msvcrt,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
sys.path.insert(0,str(REPO/'src'))
sys.path.insert(0,str(REPO/'.local/python-deps'))
from autogame.platforms.mumu import MuMuPlatform
RUNTIME=Path(os.environ.get('AUTOGAME_RUNTIME',str(REPO/'runtime'/'bilibili_hero_merge'))).resolve()
RUNTIME.mkdir(parents=True,exist_ok=True)
import cv2
import numpy as np
from PIL import Image

class Bot:
 def __init__(self,args):
  self.args=args; self.platform=MuMuPlatform(device=args.device); self.out=RUNTIME/'runs'/time.strftime('%Y%m%d-%H%M%S');self.out.mkdir(parents=True)
  self.templates={p.stem:cv2.imread(str(p)) for p in (ROOT/'assets').glob('*.png')}
  self.last_summon=0;self.last_upgrade=0;self.blocked={};self.pending=None;self.merges=0;self.wins=0;self.rounds=0;self.unknown=0;self.frame=0
 def log(self,event,**kw):
  data={'time':time.strftime('%H:%M:%S'),'event':event,**kw};print(json.dumps(data,ensure_ascii=False),flush=True)
  with (self.out/'events.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(data,ensure_ascii=False)+'\n')
 def shell(self,*args):return self.platform.shell(*args)
 def tap(self,x,y):self.platform.tap(round(x*2.5),round(y*2.5))
 def shot(self):
  t=time.monotonic();b=self.platform.screenshot()
  a=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR)
  if a.shape[:2]!=(1920,1080):raise RuntimeError('Expected 1080x1920 Android resolution')
  self.im=cv2.resize(a,(432,768),interpolation=cv2.INTER_AREA);self.frame+=1
  cv2.imwrite(str(self.out/'latest.png'),self.im)
  if self.frame%10==0:cv2.imwrite(str(self.out/f'frame-{self.frame:05d}.png'),self.im)
  return time.monotonic()-t
 def score(self,name,box):
  x,y,w,h=box;t=self.templates[name];a=self.im[y:y+h,x:x+w]
  return float(cv2.matchTemplate(a,t,cv2.TM_CCOEFF_NORMED).max())
 def has(self,name,box,threshold=.88):
  if name not in self.templates:return False
  x,y,w,h=box;t=self.templates[name];a=self.im[y:y+h,x:x+w]
  result=cv2.matchTemplate(a,t,cv2.TM_CCOEFF_NORMED);_,score,_,pos=cv2.minMaxLoc(result)
  patch=a[pos[1]:pos[1]+t.shape[0],pos[0]:pos[0]+t.shape[1]]
  # Reject the same screen when it is dimmed behind an unknown modal.
  brightness=float(patch.mean())/max(1,float(t.mean()))
  return score>threshold and .75<brightness<1.3
 def occupied(self,x,y):
  a=self.im[y-20:y+4,x-14:x+14]
  return float(cv2.cvtColor(a,cv2.COLOR_BGR2GRAY).std())>22
