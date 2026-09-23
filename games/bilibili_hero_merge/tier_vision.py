"""Experimental head counting. Advisory only: never authorizes a merge.

Templates describe a visual appearance, not every possible hero skin. Unsupported
appearances and ambiguous layouts return unknown. Coordinates use native pixels.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import cv2
import numpy as np

ASSETS = Path(__file__).with_name('assets')/'tiers'


@dataclass
class TierEstimate:
    tier: int | None
    appearance: str | None
    score: float
    heads: list
    reason: str

    def as_dict(self):
        return asdict(self)


class TierVision:
    def __init__(self, directory=ASSETS):
        self.references=[]
        for row in json.loads((Path(directory)/'atlas.json').read_text(encoding='utf8')):
            im=cv2.imread(str(Path(directory)/row['file']))
            if im is None:raise ValueError('Missing tier appearance: '+row['file'])
            self.references.append((row['appearance'], im, row['pitch']))

    def estimate(self, image, center, pitch):
        if pitch<=0 or image is None:raise ValueError('Image and positive cell pitch required')
        x,y=center
        x0,y0=round(x-.53*pitch),round(y-.93*pitch)
        x1,y1=round(x+.53*pitch),round(y+.16*pitch)
        if x0<0 or x1>image.shape[1] or y1>image.shape[0]:
            return TierEstimate(None,None,0,[],'clipped_cell')
        y0=max(0,y0)
        crop=image[y0:y1,x0:x1]
        hits=[]
        for appearance,template,ref_pitch in self.references:
            for scale in np.arange(.72,1.85,.08):
                ratio=pitch/ref_pitch*float(scale)
                w,h=round(template.shape[1]*ratio),round(template.shape[0]*ratio)
                if min(w,h)<10 or w>crop.shape[1] or h>crop.shape[0]:continue
                ref=cv2.resize(template,(w,h),interpolation=cv2.INTER_AREA)
                maps=[]
                for angle in (-20,-10,0,10,20):
                    rotation=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
                    rotated=cv2.warpAffine(ref,rotation,(w,h),borderMode=cv2.BORDER_REFLECT_101)
                    maps.append(cv2.matchTemplate(crop,rotated,cv2.TM_CCOEFF_NORMED))
                scores=np.maximum.reduce(maps)
                for _ in range(4):
                    _,score,_,loc=cv2.minMaxLoc(scores)
                    if score<.61:break
                    a,b=loc
                    hits.append(dict(appearance=appearance,score=float(score),scale=float(scale),
                                     x=x0+a+w/2,y=y0+b+h/2,w=w,h=h))
                    cv2.rectangle(scores,(max(0,a-w//2),max(0,b-h//2)),(a+w//2,b+h//2),-1,-1)
        selected=[]
        for hit in sorted(hits,key=lambda v:v['score'],reverse=True):
            if any(abs(hit['x']-v['x'])<.23*pitch and abs(hit['y']-v['y'])<.23*pitch for v in selected):continue
            selected.append(hit)
        if not selected:return TierEstimate(None,None,0,[],'unsupported_or_occluded')
        appearances={v['appearance'] for v in selected}
        score=min(v['score'] for v in selected)
        appearance=selected[0]['appearance']
        reason='candidate'
        tier=None
        if len(appearances)!=1:reason='mixed_appearances'
        elif len(selected)>3:reason='too_many_heads'
        elif len(selected)>1 and any(h['scale']>1.24 for h in selected):reason='oversized_group'
        elif len(selected)==1:
            head=selected[0]
            if abs(head['x']-x)>.23*pitch:reason='off_center_single'
            elif head['scale']>=1.32:tier=4
            elif head['scale']<=1.16:tier=1
            else:reason='ambiguous_size'
        elif len(selected)==2:
            a,b=sorted(selected,key=lambda v:v['x'])
            if (.28*pitch< b['x']-a['x'] <.64*pitch and abs(a['y']-b['y'])<.14*pitch
                    and abs((a['x']+b['x'])/2-x)<.14*pitch):tier=2
            else:reason='not_a_pair'
        else:
            top,a,b=sorted(selected,key=lambda v:v['y'])
            if (abs(top['x']-x)<.18*pitch and abs(a['y']-b['y'])<.14*pitch
                    and .2*pitch<abs(a['x']-b['x'])<.65*pitch
                    and .15*pitch<(a['y']+b['y'])/2-top['y']<.5*pitch):tier=3
            else:reason='not_a_triangle'
        return TierEstimate(tier,appearance,round(score,3),selected,reason)


class TierConsensus:
    """Only consecutive agreeing views count; clearing is mandatory after input."""
    def __init__(self, repeats=3):
        self.repeats=repeats
        self.history={}

    def clear(self):
        self.history.clear()

    def observe(self, cell, estimate):
        if estimate.tier is None:
            self.history.pop(cell,None)
            return None
        value=(estimate.appearance,estimate.tier)
        previous,count=self.history.get(cell,(None,0))
        count=count+1 if previous==value else 1
        self.history[cell]=(value,count)
        return estimate.tier if count>=self.repeats else None


def inspect_samples(manifest, output):
    """Offline only. Cell centers are annotated; this does not detect a grid."""
    import time
    manifest=Path(manifest);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    data=json.loads(manifest.read_text(encoding='utf8'));vision=TierVision()
    results=[]
    for group in data['images']:
        image=cv2.imread(str(manifest.parent/group['file']))
        if image is None:raise ValueError('Unreadable sample '+group['file'])
        overlay=image.copy();rows=[]
        for i,cell in enumerate(group['cells']):
            start=time.perf_counter()
            estimate=vision.estimate(image,cell['center'],group['pitch'])
            row=dict(cell=cell,estimate=estimate.as_dict(),milliseconds=round((time.perf_counter()-start)*1000))
            rows.append(row)
            x,y=cell['center'];p=group['pitch'];color=(90,210,90) if estimate.tier else (0,180,255)
            for head in estimate.heads:
                a,b,w,h=(head[k] for k in ('x','y','w','h'))
                cv2.rectangle(overlay,(round(a-w/2),round(b-h/2)),(round(a+w/2),round(b+h/2)),color,1)
            caption=f'{i+1}: T{estimate.tier}' if estimate.tier else f'{i+1}: ?'
            cv2.putText(overlay,caption,(round(x-p*.43),round(y+p*.3)),cv2.FONT_HERSHEY_SIMPLEX,
                        max(.3,p/240),color,max(1,round(p/100)),cv2.LINE_AA)
        cv2.imwrite(str(output/(group['id']+'.png')),overlay)
        results.append(dict(id=group['id'],split=group['split'],rows=rows))
    (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    for group in inspect_samples(args.manifest,args.output):
        print(group['id'],[(r['cell']['expected'],r['estimate']['tier']) for r in group['rows']])
