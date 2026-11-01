"""Project native active enemy coordinates through the original arena artwork."""
import math
import cv2
import numpy as np
from PIL import Image
from hunt_paths import ASSETS
from hunt_layout import LayoutError
from hunt_config import rules

# Original trap.unity: enemy_layer is under battle_field at this position.
# The bg Sprite is at (0,0), pivot (.5,.5), pixels-to-units 54.61333465576172.
FIELD_ORIGIN=(-6.665999889373779,-6.693999767303467)
PIXELS_PER_UNIT=54.61333465576172


def farm_target(state,projector=None):
    candidates=[e for e in state.get('enemies',[]) if e['active']
        and all(type(e.get(k)) in (int,float) and math.isfinite(e[k]) for k in ('x','y'))
        and .25<e['x']<13.09 and .25<e['y']<13.09]
    # Ordinary groups also drop lock/rage items in the original TrapZobo table.
    # Aim at a real member of the densest visible group, never empty centroid.
    weights={r['id']:r.get('farm_weight',1) for r in rules()['enemies']}
    def density(e):
        return sum(math.exp(-((e['x']-n['x'])**2+(e['y']-n['y'])**2)/(2*.9**2))*weights.get(n['tid'],1) for n in candidates)
    candidates.sort(key=lambda e:(-density(e),e['score'],e['id']))
    for candidate in candidates:
        if projector is not None:
            try:projector.point(candidate)
            except LayoutError:continue
        return candidate
    return None


class FarmAim:
    def __init__(self):
        self.source=np.asarray(Image.open(ASSETS/'txui_gym_bg_01.png').convert('RGB'))
        self.sift=cv2.SIFT_create(nfeatures=6000,contrastThreshold=.01)
        self.keys,self.descriptors=self.sift.detectAndCompute(cv2.cvtColor(self.source,cv2.COLOR_RGB2GRAY),None)
        self.matrix=None;self.size=None;self.room=None

    def recognize(self,image,room):
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        factor=min(1,2000/image.height)
        if factor!=1:gray=cv2.resize(gray,None,fx=factor,fy=factor)
        keys,descriptors=self.sift.detectAndCompute(gray,None)
        if descriptors is None:raise LayoutError('未识别到围猎原场景，不向空地射击')
        matches=cv2.BFMatcher().knnMatch(self.descriptors,descriptors,k=2)
        best={}
        for pair in matches:
            if len(pair)!=2:continue
            a,b=pair
            if a.distance<.72*b.distance and (a.trainIdx not in best or a.distance<best[a.trainIdx].distance):best[a.trainIdx]=a
        good=list(best.values())
        if len(good)<10:raise LayoutError('围猎场景特征不足，不猜怪物投影')
        source=np.float32([self.keys[m.queryIdx].pt for m in good])
        target=np.float32([keys[m.trainIdx].pt for m in good])
        matrix,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,ransacReprojThreshold=2.5)
        if matrix is None or inliers is None or int(inliers.sum())<10:raise LayoutError('围猎坐标投影尚未验证')
        keep=inliers.ravel().astype(bool);spread=np.ptp(source[keep],axis=0)
        scale=math.hypot(matrix[0,0],matrix[1,0])
        if abs(matrix[0,1])>scale*.035 or not .12<scale<4 or spread[0]<self.source.shape[1]*.30 or spread[1]<self.source.shape[0]*.25:
            raise LayoutError('围猎投影范围或方向不符，停止瞄准')
        self.matrix=matrix/factor;self.size=image.size;self.room=tuple(room)
        return dict(inliers=int(inliers.sum()),scale=scale/factor)

    def point(self,enemy):
        if self.matrix is None:raise LayoutError('尚未识别当前场景投影')
        x=(enemy['x']+FIELD_ORIGIN[0])*PIXELS_PER_UNIT+self.source.shape[1]/2
        y=self.source.shape[0]/2-(enemy['y']+FIELD_ORIGIN[1])*PIXELS_PER_UNIT
        point=self.matrix@np.array([x,y,1])
        if not self.size[0]*.18<point[0]<self.size[0]*.82 or not self.size[1]*.34<point[1]<self.size[1]*.71:
            raise LayoutError('怪物投影不在可射击区域，未发射')
        return tuple(float(v) for v in point)
