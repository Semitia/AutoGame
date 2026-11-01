"""Current-frame controls from original item sprites and visible button shapes."""
import cv2
import numpy as np
from PIL import Image
from hunt_paths import ASSETS


class LayoutError(ValueError):pass


class Layout:
    def __init__(self):
        self.templates={name:np.asarray(Image.open(ASSETS/(name+'.png')).convert('RGBA')) for name in ('lock','rage','close')}

    def frame(self,image):
        factor=min(1,1200/image.height)
        frame=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)
        if factor!=1:frame=cv2.resize(frame,None,fx=factor,fy=factor)
        return frame,factor

    def icon(self,image,name):
        frame,factor=self.frame(image);h,w=frame.shape[:2]
        x0=int(w*.65);y0=int(h*.58);roi=frame[y0:,x0:]
        template=self.templates[name];best=(-1,None)
        for height in np.linspace(max(18,h*.025),h*.10,28):
            scale=height/template.shape[0]
            t=cv2.resize(template,None,fx=scale,fy=scale)
            if min(t.shape[:2])<8 or t.shape[0]>=roi.shape[0] or t.shape[1]>=roi.shape[1]:continue
            mask=(t[:,:,3]>100).astype(np.uint8)*255
            score=cv2.matchTemplate(roi,t[:,:,:3][:,:,::-1],cv2.TM_CCORR_NORMED,mask=mask)
            score=np.nan_to_num(score,nan=-1,posinf=-1,neginf=-1)
            _,value,_,point=cv2.minMaxLoc(score)
            if value>best[0]:best=(value,((x0+point[0]+t.shape[1]/2)/factor,(y0+point[1]+t.shape[0]/2)/factor))
        if best[0]<.90:raise LayoutError(f'尚未识别到{name}原图按钮（{best[0]:.2f}）')
        return best[1]

    def close(self,image):
        frame,factor=self.frame(image);h,w=frame.shape[:2]
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        # Common close variants tint the same X white or red. Match its shape.
        white=cv2.inRange(hsv,(0,0,165),(180,125,255))
        red=cv2.inRange(hsv,(0,120,130),(12,255,255))|cv2.inRange(hsv,(170,120,130),(180,255,255))
        mask=white|red;x0=int(w*.25);y0=int(h*.90);roi=mask[y0:,x0:int(w*.75)]
        raw=self.templates['close'];alpha=(raw[:,:,3]>190).astype(np.uint8)*255
        ys,xs=np.where(alpha>0);alpha=alpha[ys.min():ys.max()+1,xs.min():xs.max()+1]
        best=(-1,None)
        for height in np.linspace(max(14,h*.012),h*.06,40):
            t=cv2.resize(alpha,None,fx=height/alpha.shape[0],fy=height/alpha.shape[0])
            if t.shape[0]>=roi.shape[0] or t.shape[1]>=roi.shape[1]:continue
            scores=cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED)
            _,value,_,p=cv2.minMaxLoc(scores)
            if value>best[0]:best=(value,((x0+p[0]+t.shape[1]/2)/factor,(y0+p[1]+t.shape[0]/2)/factor))
        if best[0]<.65:raise LayoutError(f'未识别到围猎底部退出叉号（{best[0]:.2f}）')
        return best[1]

    def navigation(self,image,direction):
        frame,factor=self.frame(image);h,w=frame.shape[:2]
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);mask=cv2.inRange(hsv,(0,0,170),(180,135,255))
        keep=np.zeros_like(mask);keep[int(h*.22):int(h*.76),:int(w*.24)]=255
        keep[int(h*.22):int(h*.76),int(w*.76):]=255;mask&=keep
        found=[]
        triangle=np.array([(0,30),(35,0),(35,60)],dtype=np.int32).reshape(-1,1,2)
        chevron=np.array([(30,0),(0,30),(30,60),(42,48),(24,30),(42,12)],dtype=np.int32).reshape(-1,1,2)
        for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            x,y,rw,rh=cv2.boundingRect(contour)
            if not (.02*w<rw<.15*w and .018*h<rh<.10*h and .35<rw/rh<1.5):continue
            p=cv2.approxPolyDP(contour,.035*cv2.arcLength(contour,True),True)[:,0,:]
            if len(p) not in (3,5,6,7):continue
            left=direction=='previous'
            if left!=(x<w*.5):continue
            tip=p[np.argmin(p[:,0]) if left else np.argmax(p[:,0])]
            if abs(tip[1]-(y+rh/2))>rh*.25:continue
            # Artwork in the lobby also contains bright contours. Require an
            # arrow silhouette, including the actual rounded chevron button.
            if min(cv2.matchShapes(contour,t,cv2.CONTOURS_MATCH_I1,0) for t in (triangle,chevron))>.18:continue
            found.append(((x+rw/2)/factor,(y+rh/2)/factor))
        if len(found)!=1:raise LayoutError('未识别到唯一的场地翻页箭头，不猜按钮位置')
        return found[0]

    def start(self,image):
        from auto_layout import yellow_button,center
        frame,factor=self.frame(image)
        try:point=center(yellow_button(frame))
        except ValueError as exc:raise LayoutError(str(exc)) from exc
        return tuple(v/factor for v in point)

    def aim(self,image):
        # Low-room aiming is deliberately arbitrary, but only inside the visible
        # grey/green play field, between HUD and the lower player platform.
        frame,factor=self.frame(image);h,w=frame.shape[:2]
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(0,0,80),(180,105,225))
        keep=np.zeros_like(mask);keep[int(h*.38):int(h*.62),int(w*.35):int(w*.65)]=255
        points=cv2.findNonZero(mask&keep)
        if points is None or len(points)<w*h*.003:raise LayoutError('当前画面未识别到低倍场可射击区域')
        p=np.median(points[:,0,:],axis=0)
        return tuple(float(v/factor) for v in p)
