"""Short-horizon timing for tiny targets, including temporary float occlusion."""
from collections import deque
from dataclasses import dataclass
import statistics

import numpy as np


@dataclass
class Aim:
    speed: float
    target: tuple
    predicted: float
    delay: float | None


class SliderAim:
    def __init__(self):
        self.samples=deque(maxlen=6)
        self.speeds=deque(maxlen=15)
        self.target=None;self.target_seen=0.;self.blocked_until=0.

    def reset(self):
        self.samples.clear();self.speeds.clear();self.target=None;self.target_seen=0.;self.blocked_until=0.

    def fired(self,now):
        self.samples.clear();self.target=None
        self.blocked_until=now+.32

    def update(self,stamp,position,target,now,lead=.04,track=(114.,296.),lookahead=.075):
        if position is None:return None
        if self.samples and stamp<=self.samples[-1][0]:return None
        if self.samples and (stamp-self.samples[-1][0]>.2 or abs(position-self.samples[-1][1])>45):self.samples.clear()
        self.samples.append((stamp,position))
        if target:
            # While the float covers a boundary, the visible part is smaller than the real target.
            covered=self.target is not None and self.target[0]-13<position<self.target[1]+13
            changed=self.target is None or target[1]<self.target[0]-3 or target[0]>self.target[1]+3
            if changed or not covered:self.target=target
            self.target_seen=now
        if self.target is None or now-self.target_seen>1.2 or now<self.blocked_until or len(self.samples)<3:return None
        points=list(self.samples)
        # Fit only the latest direction after a turn; old-direction samples must not cancel it.
        last_delta=points[-1][1]-points[-2][1]
        if abs(last_delta)<.6:return None
        sign=1 if last_delta>0 else -1
        start=len(points)-2
        while start>0:
            delta=points[start][1]-points[start-1][1]
            if delta*sign<-.5:break
            start-=1
        segment=points[start:]
        if len(segment)<3:return None
        ts=np.array([p[0]-segment[0][0] for p in segment]);xs=np.array([p[1] for p in segment])
        speed=float(np.polyfit(ts,xs,1)[0])
        if not 40<abs(speed)<450:return None
        fit=np.polyval(np.polyfit(ts,xs,1),ts)
        if float(np.max(np.abs(fit-xs)))>2.8:return None
        self.speeds.append(abs(speed))
        magnitude=statistics.median(self.speeds)
        if abs(abs(speed)-magnitude)<magnitude*.35:speed=sign*magnitude
        # stamp approximates the actual capture time. Lead includes game display and input delay.
        raw=position+speed*(lead+max(0,now-stamp))
        bound_left,bound_right=track;width=bound_right-bound_left
        phase=(raw-bound_left)%(2*width)
        projected=bound_left+(phase if phase<=width else 2*width-phase)
        left,right=self.target
        margin=min(2.,max(.35,(right-left)*.06))
        center=(left+right)/2
        images=[bound_left+2*k*width+direction*(center-bound_left) for k in range(-2,3) for direction in (-1,1)]
        arrivals=[(image-raw)/speed for image in images if 0<=(image-raw)/speed<=lookahead]
        delay=min(arrivals) if arrivals else None
        if left+margin<=projected<=right-margin:delay=0.
        return Aim(speed,self.target,projected,delay)
