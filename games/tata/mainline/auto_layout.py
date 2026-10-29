"""Recognize current game layout without calibration clicks or desktop focus."""
import argparse
import itertools
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from model import Catalog, RUNTIME, read_json, write_json

ASSETS=Path(__file__).with_name('assets')/'layout'


class LayoutError(ValueError):pass


def center(rect):
    x,y,w,h=rect
    return [x+w/2,y+h/2]


def colored_action_button(frame,phase):
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    low,high=([35,100,120],[85,255,255]) if phase=='victory' else ([15,120,140],[40,255,255])
    mask=cv2.inRange(hsv,np.array(low),np.array(high))
    mask[:int(h*.65)]=0
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>w*h*.005]
    candidates=[r for r in candidates if r[2]>.23*w and r[3]>.025*h and r[2]/r[3]>2]
    if phase=='chapter':candidates=[r for r in candidates if r[2]>.60*w and r[1]>.75*h]
    label={'prepare':'开始','victory':'胜利页继续','chapter':'章节地图开始'}[phase]
    if len(candidates)!=1:raise LayoutError(f'未识别到唯一的{label}按钮；保留游戏界面，不会试点坐标')
    return candidates[0]


def yellow_button(frame):return colored_action_button(frame,'prepare')


def continue_button(frame):return colored_action_button(frame,'victory')


def chapter_start_button(frame):return colored_action_button(frame,'chapter')


def filter_buttons(frame,start):
    h,w=frame.shape[:2];y0=max(0,int(start[1]-h*.09));y1=int(start[1]-3)
    roi=frame[y0:y1]
    circles=cv2.HoughCircles(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.HOUGH_GRADIENT,
        dp=1.2,minDist=w*.07,param1=100,param2=23,minRadius=max(5,int(w*.025)),maxRadius=max(7,int(w*.055)))
    if circles is None:raise LayoutError('未识别到布阵元素筛选栏；请打开主线布阵页')
    candidates=sorted(circles[0],key=lambda p:p[0])
    groups=[]
    for group in itertools.combinations(candidates[:16],5):
        a=np.asarray(group);steps=np.diff(a[:,0]);spacing=np.median(steps)
        if spacing<w*.06 or np.std(steps)>spacing*.08 or np.std(a[:,1])>h*.006:continue
        groups.append((float(np.std(steps)),a))
    if not groups:raise LayoutError('元素筛选栏布局尚未识别，不使用旧电脑坐标')
    a=min(groups,key=lambda p:p[0])[1]
    # Original UI order, also checked by native _filterList after each click.
    return {str(element):[float(p[0]),float(p[1]+y0)] for element,p in zip((2,3,4,6,5),a)}


def card_frames(frame,filter_y,rows=2):
    h,w=frame.shape[:2]
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    mask=(gray<50).astype('uint8')*255
    mask[:int(h*.45)]=0;mask[int(filter_y-h*.025):]=0
    contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    rects=[cv2.boundingRect(c) for c in contours]
    rects=[r for r in rects if .055*w<r[2]<.25*w and .035*h<r[3]<.18*h and .9<r[3]/r[2]<1.6]
    outer=[]
    for rect in sorted(rects,key=lambda r:r[2]*r[3],reverse=True):
        x,y,rw,rh=rect
        if any(max(0,min(x+rw,a+aw)-max(x,a))*max(0,min(y+rh,b+bh)-max(y,b))>rw*rh*.85 for a,b,aw,bh in outer):continue
        outer.append(rect)
    rects=outer
    groups=[]
    for r in rects:
        peers=[p for p in rects if abs(p[2]-r[2])<max(3,r[2]*.04) and abs(p[3]-r[3])<max(3,r[3]*.04)]
        if len(peers)>=rows:groups.append(peers)
    if not groups:raise LayoutError('卡片列表未完整显示，无法自动定位卡片')
    rects=max(groups,key=lambda group:(len(group),np.median([r[2]*r[3] for r in group])))
    lines=[]
    for rect in sorted(rects,key=lambda r:(r[1],r[0])):
        line=next((line for line in lines if abs(line[0][1]-rect[1])<rect[3]*.15),None)
        if line is None:lines.append([rect])
        else:line.append(rect)
    lines=[sorted(line,key=lambda r:r[0]) for line in lines if len(line)>=1]
    if len(lines)!=rows:raise LayoutError('卡片行数与游戏内存不一致，等待界面展开后重试')
    return lines


class AutoLayout:
    def __init__(self,catalog=None):
        self.catalog=catalog or Catalog();self.sift=cv2.SIFT_create(nfeatures=2500)
        self.features={}

    def image_path(self,reference):
        name=Path(reference).stem+'.png'
        for folder in ('art','icons'):
            path=RUNTIME/folder/name
            if path.is_file():return path
        raise LayoutError('缺少用于布局识别的原图：'+name+'；可点“同步本机资源”补充')

    def source_features(self,path):
        key=str(path)
        if key not in self.features:
            image=cv2.imread(key,cv2.IMREAD_GRAYSCALE)
            if image is None:raise LayoutError('布局原图无法读取：'+Path(path).name)
            points,descriptors=self.sift.detectAndCompute(image,None)
            self.features[key]=(image,points,descriptors)
        return self.features[key]

    def match(self,path,target_features,minimum=8):
        image,points,descriptors=self.source_features(path)
        target_points,target_desc=target_features
        if descriptors is None or target_desc is None:return None
        pairs=cv2.BFMatcher().knnMatch(descriptors,target_desc,k=2)
        good=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.70*pair[1].distance]
        if len(good)<minimum:return None
        a=np.float32([points[m.queryIdx].pt for m in good]);b=np.float32([target_points[m.trainIdx].pt for m in good])
        matrix,inliers=cv2.estimateAffine2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.5)
        if matrix is None or inliers is None or int(inliers.sum())<minimum:return None
        scale=float(matrix[0,0])
        if not .08<scale<5 or not .08<matrix[1,1]<5 or abs(matrix[1,0])>scale*.03 or abs(matrix[0,1])>scale*.03:return None
        return matrix,int(inliers.sum()),image.shape

    def recognize(self,image,state):
        frame=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)
        h,w=frame.shape[:2];start=yellow_button(frame)
        filters=filter_buttons(frame,start);filter_y=float(np.median([p[1] for p in filters.values()]))
        rows=state.get('prepare',{}).get('_currentPrepareListRowCount',2)
        lines=card_frames(frame,filter_y,rows)
        stage=self.catalog.stage(state['current_stage_id'])
        reference=self.catalog.battle_resources[str(stage['battle']['ResID'])]['BackgroundRes']
        target=self.sift.detectAndCompute(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),None)
        match=self.match(self.image_path(reference),target)
        if match is None:raise LayoutError('原地图与游戏画面未能匹配；等待布阵动画结束后重试')
        matrix,inliers,shape=match
        offset=state.get('field_offset',{})
        if any(type(offset.get(k)) not in (int,float) for k in ('x','y')):
            raise LayoutError('未读取到当前游戏的战场偏移，请重新同步')
        # 0.50.1 original GetBattlePositionByGrid yields (x-.5,y-.5).
        # BattleBaseScene.AdjustBackgroundScale uses 110 source pixels/grid;
        # background and actors share the field-root offset. Do not infer from
        # the stage name or reuse a previous computer's screen projection.
        point=np.array([shape[1]/2+(.5+offset['x'])*110,
                        shape[0]/2-(.5+offset['y'])*110,1])
        grid=(matrix@point).tolist();step=float(matrix[0,0]*110);step_y=float(matrix[1,1]*110)
        clear=self.clear_point(frame,start,lines[0][0][1])
        return dict(schema_version=3,calibration_source='automatic-image-and-model',
                    width=w,height=h,physical_size=[w,h],grid=grid,gridStep=step,gridStepX=step,gridStepY=step_y,
                    start=center(start),clear=clear,filters=filters,
                    card=center(lines[0][0]),cardStep=float(np.median(np.diff([center(r)[0] for r in lines[0]]))),
                    cardRowStep=(center(lines[1][0])[1]-center(lines[0][0])[1]) if rows>1 else lines[0][0][3],
                    visible_cards=sum(map(len,lines)),map_inliers=inliers,stage_id=state['current_stage_id'])

    def clear_point(self,frame,start,gallery_top):
        h,w=frame.shape[:2];template=cv2.imread(str(ASSETS/'clear-arrow.png'),0)
        if template is None:raise LayoutError('仓库缺少清空按钮识别模板')
        x0=int(w*.70);y0=int(h*.25);roi=cv2.cvtColor(frame[y0:int(gallery_top),x0:],cv2.COLOR_BGR2GRAY)
        best=(-1,None)
        for scale in np.linspace(start[3]/96*.85,start[3]/96*1.15,7):
            t=cv2.resize(template,None,fx=scale,fy=scale)
            if t.shape[0]>=roi.shape[0] or t.shape[1]>=roi.shape[1]:continue
            scoremap=cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED)
            _,score,_,point=cv2.minMaxLoc(scoremap)
            if score>best[0]:best=(score,[x0+point[0]+t.shape[1]/2,y0+point[1]+t.shape[0]/2])
        if best[0]<.78:raise LayoutError('全部下阵按钮尚未识别，不会试点旧坐标')
        return best[1]

    def locate_card(self,image,state,uid,pets,geometry=None):
        frame=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)
        if geometry and image.size==(geometry['width'],geometry['height']) and geometry.get('stage_id')==state['current_stage_id']:
            filters=geometry['filters']
        else:
            start=yellow_button(frame);filters=filter_buttons(frame,start)
        fy=float(np.median([p[1] for p in filters.values()]))
        rows=state.get('prepare',{}).get('_currentPrepareListRowCount',2)
        ids=state['pet_list'];index=ids.index(uid)
        lines=card_frames(frame,fy,min(rows,len(ids)))
        columns=min(map(len,lines))
        if len(ids)<=columns*rows:
            return dict(point=center(lines[index%rows][index//rows]))
        top=min(r[1] for line in lines for r in line)
        bottom=max(r[1]+r[3] for line in lines for r in line)
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        features=self.sift.detectAndCompute(gray[top:bottom],None)
        votes=[]
        for candidate in ids:
            pet=pets.get(candidate)
            if pet is None:continue
            ref=self.catalog.resource(candidate,pet['evoTID'])['IconName']
            match=self.match(self.image_path(ref),features,minimum=4)
            if match is None:continue
            matrix,inliers,shape=match
            p=matrix@np.array([shape[1]/2,shape[0]/2,1]);p[1]+=top
            for row,line in enumerate(lines):
                for col,rect in enumerate(line):
                    x,y,rw,rh=rect
                    if x<=p[0]<=x+rw and y<=p[1]<=y+rh and ids.index(candidate)%rows==row:
                        votes.append((ids.index(candidate)//rows-col,inliers))
        if votes:
            offset=max(set(v[0] for v in votes),key=lambda off:sum(weight for value,weight in votes if value==off))
            agreeing=[weight for value,weight in votes if value==offset]
            if sum(agreeing)<.7*sum(weight for _,weight in votes) or (len(agreeing)<2 and max(agreeing)<6):
                raise LayoutError('卡片图像证据不足，停止输入；可先把目标卡片滑到完整可见的位置')
            col=index//rows-offset
            if 0<=col<len(lines[index%rows]):return dict(point=center(lines[index%rows][col]))
            direction='left' if col>=columns else 'right'
        else:
            raise LayoutError('未识别到足够的卡片图像，不会按猜测的列表位置点击')
        first,last=center(lines[0][0]),center(lines[0][-1])
        y=(center(lines[0][0])[1]+center(lines[-1][0])[1])/2
        swipe=[last[0],y,first[0],y]
        if direction=='right':swipe=swipe[2:]+swipe[:2]
        return dict(swipe=swipe)

    def capture(self):
        from calibration import capture_visible_game
        return capture_visible_game()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=RUNTIME/'autoplay-geometry.json')
    args=parser.parse_args()
    from live_battle import LiveBattle
    live=LiveBattle()
    try:
        state=live.snapshot()
        detector=AutoLayout()
        if state.get('screen')=='chapter':
            image=detector.capture()
            point=center(chapter_start_button(cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)))
            write_json(args.out,dict(schema_version=3,screen='chapter',stage_id=state['current_stage_id'],
                                    width=image.width,height=image.height,chapter_start=point))
            print('已识别章节地图与开始按钮；启动推关后会自动进入布阵，此检查未执行游戏输入。',flush=True)
            return 0
        if state.get('battle',{}).get('state')!=1:raise LayoutError('请打开主线章节地图或布阵页；此检查不会操作游戏')
        value=detector.recognize(detector.capture(),state)
        write_json(args.out,value)
        print(f'自动识别完成：{value["width"]}×{value["height"]}，地图匹配 {value["map_inliers"]} 点；无需手工标点。',flush=True)
    except (ValueError,OSError) as exc:
        print(str(exc),flush=True)
        return 1
    finally:live.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
