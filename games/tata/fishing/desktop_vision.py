from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass
class DesktopObservation:
    state: str
    pointer: float | None = None
    yellow: tuple | None = None
    score: float = 0.
    track: tuple | None = None


class DesktopVision:
    def __init__(self):
        root=Path(__file__).with_name('assets')
        self.title=cv2.imread(str(root/'desktop-title.png'),0)
        self.reward=cv2.imread(str(root/'desktop-reward.png'),0)
        self.rare=cv2.imread(str(root/'desktop-rare.png'),0)
        self.record=cv2.imread(str(root/'desktop-record.png'),0)

    @staticmethod
    def is_result_card(frame):
        """Fish cards keep their geometry across personal/team/other record titles."""
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        card=hsv[235:540,20:380]
        blue=cv2.inRange(card,(101,125,120),(125,255,255))
        gold=cv2.inRange(card,(10,125,120),(40,255,255))
        broad_rows=np.count_nonzero(np.count_nonzero(blue|gold,axis=1)>270)
        badge=hsv[465:535,95:305]
        dark=np.count_nonzero(badge[:,:,2]<115)
        light=np.count_nonzero(cv2.inRange(badge,(0,0,170),(180,100,255)))
        return broad_rows>85 and dark>600 and light>120

    def observe(self,frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        record=float(cv2.matchTemplate(gray[120:215,75:325],self.record,cv2.TM_CCOEFF_NORMED).max())
        if record>.8:return DesktopObservation('record_reward',score=record)
        rare=float(cv2.matchTemplate(gray[125:205,90:310],self.rare,cv2.TM_CCOEFF_NORMED).max())
        if rare>.83:return DesktopObservation('rare_reward',score=rare)
        reward=float(cv2.matchTemplate(gray[110:185,90:310],self.reward,cv2.TM_CCOEFF_NORMED).max())
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        if reward>.85:
            green=cv2.inRange(hsv[638:678,140:260],(30,110,100),(90,255,255))
            return DesktopObservation('reward' if np.count_nonzero(green)>700 else 'reward_animation',score=reward)
        score=float(cv2.matchTemplate(gray[45:95,130:270],self.title,cv2.TM_CCOEFF_NORMED).max())
        if score<.75:
            return DesktopObservation('result_card' if self.is_result_card(frame) else 'unknown',score=score)
        # Success text above the track can also be yellow/red. Read the target
        # only from the track's interior, and the float from its own vertical band.
        borders=cv2.inRange(hsv[495:539,110:302],(0,0,170),(180,100,255))
        rows=np.count_nonzero(borders,axis=1)
        pairs=[(a,b) for a in range(len(rows)) for b in range(a+11,min(a+23,len(rows))) if rows[a]>90 and rows[b]>90]
        track=None
        if pairs:
            a,b=max(pairs,key=lambda p:int(rows[p[0]])+int(rows[p[1]]))
            top,bottom=a+495,b+495
            track=(114.,296.)
        else:top,bottom=507,523
        roi=hsv[top-24:bottom+20,110:303]
        yellow=cv2.inRange(hsv[top+2:bottom-1,110:303],(18,100,150),(40,255,255))
        red=cv2.inRange(roi,(0,110,100),(16,255,255))|cv2.inRange(roi,(170,110,100),(180,255,255))
        cs,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cs=[c for c in cs if cv2.contourArea(c)>10 and cv2.boundingRect(c)[3]>=9]
        # Slider has a red float; the bite countdown has no float.
        if track and cs:
            c=max(cs,key=cv2.contourArea);x,y,w,h=cv2.boundingRect(c)
            columns=np.count_nonzero(yellow,axis=0)
            xs=np.flatnonzero(columns>=2)
            target=(int(xs[0])+110,int(xs[-1])+111) if len(xs)>=2 else None
            return DesktopObservation('slider',x+w/2+110,target,score,track)
        if track:return DesktopObservation('slider',score=score,track=track)
        ring=hsv[566:663,143:261]
        purple=np.count_nonzero(cv2.inRange(ring,(125,95,120),(170,255,255)))
        green=np.count_nonzero(cv2.inRange(ring,(35,120,120),(85,255,255)))
        if purple>850:return DesktopObservation('hook',score=score)
        if green>850:return DesktopObservation('idle',score=score)
        return DesktopObservation('waiting',score=score)
