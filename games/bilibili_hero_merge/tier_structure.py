"""Offline, appearance-independent cell evidence. Never authorizes game input.

Requires a verified empty reference from the same board/rendering scale. Reports
occupancy separately from rank: failure to find repetition is not proof of rank 1.
"""
from dataclasses import dataclass, asdict
import cv2
import numpy as np


def cell_crop(image, center, pitch):
    x,y=center
    bounds=(round(x-.5*pitch),round(y-.95*pitch),
            round(x+.5*pitch),round(y+.1*pitch))
    a,b,c,d=bounds
    if a<0 or c>image.shape[1] or d>image.shape[0] or y<.7*pitch:
        return None
    crop=image[max(0,b):d,a:c]
    if b<0:crop=cv2.copyMakeBorder(crop,-b,0,0,0,cv2.BORDER_REPLICATE)
    return cv2.resize(crop,(96,101),interpolation=cv2.INTER_AREA)


@dataclass
class StructureEvidence:
    occupied: bool | None
    tier: int | None
    reason: str
    foreground_fraction: float = 0
    width: float = 0
    pair_score: float = 0
    triple_score: float = 0
    matches: list = None
    pair_center_y: float | None = None
    pair_support: list = None
    layout_shift: float | None = None

    def as_dict(self):return asdict(self)


class StructureVision:
    @staticmethod
    def align_pair(source,target,support,scale=1):
        """Match many foreground parts under one displacement, not one ornament."""
        # Compare the lower front bodies: a rear occluder can also cover the
        # uppermost hat pixels. Keep the feet when the pair shifts down.
        support=[box for box in support if box[1]>=40]
        if len(support)<12:return None
        if not .85<=scale<=1.15:return None
        matrix=np.float32([[scale,0,48*(1-scale)],[0,scale,0]])
        source=cv2.warpAffine(source,matrix,(96,101),borderMode=cv2.BORDER_REFLECT_101)
        support=[[round(x*scale+48*(1-scale)),round(y*scale),round(w*scale),round(h*scale)]
                 for x,y,w,h in support]
        # Evenly subsample; all vertical regions retain representation.
        support=support[::max(1,len(support)//40)]
        best=(0,None)
        for dy in range(-20,21):
            for dx in range(-6,7,2):
                scores=[];ys=[]
                for x,y,w,h in support:
                    a,b=x+dx,y+dy
                    if a<0 or b<0 or a+w>96 or b+h>101:continue
                    patch=source[y:y+h,x:x+w]
                    other=target[b:b+h,a:a+w]
                    scores.append(float(cv2.matchTemplate(other,patch,cv2.TM_CCOEFF_NORMED)[0,0]))
                    ys.append(y)
                if len(scores)<.85*len(support):continue
                scores=np.array(scores);good=scores>=.82
                # This only vetoes a rank-2 claim; partial body agreement is
                # useful even when the rear occluder covers some front pixels.
                if good.mean()<.40:continue
                if np.ptp(np.array(ys)[good])<18:continue
                score=float(np.median(scores))
                if score>best[0]:best=(score,dy)
        # Convert translation to displacement at the lower body's anchor.
        return best[1]+65*(scale-1) if best[0]>=.78 else None

    @staticmethod
    def pair_geometry(crop,mask,boxes):
        """Aggregate matching foreground under one shared translation.

        This is a visual foreground centre, not a semantic body/foot detector.
        A matching eye/weapon alone must not define the pair's vertical position.
        """
        a,b=boxes[:2];dx=b[0]-a[0];dy=b[1]-a[1]
        points=[]
        for y in range(16,80,3):
            for x in range(7,min(45,88-dx),3):
                rx,ry=x+dx,y+dy
                if ry<0 or ry+10>89:continue
                left=crop[y:y+10,x:x+10];right=crop[ry:ry+10,rx:rx+10]
                if left.shape!=right.shape:continue
                if min(mask[y:y+10,x:x+10].mean(),mask[ry:ry+10,rx:rx+10].mean())<.5:continue
                if min(np.mean(left.std(axis=(0,1))),np.mean(right.std(axis=(0,1))))<18:continue
                score=float(cv2.matchTemplate(left,right,cv2.TM_CCOEFF_NORMED)[0,0])
                if score>=.82:points.append((x+5,y+5,score))
        if len(points)<8:return None,[]
        coords=np.array(points)
        # Need support spanning the body, not one compact matching ornament.
        low,high=np.quantile(coords[:,1],[.1,.9])
        if high-low<18:return None,[]
        center=float(np.average(coords[:,1],weights=coords[:,2]))
        return round(center/96-.95,3),[[int(x-5),int(y-5),10,10] for x,y,_ in points]

    def estimate_board(self,image,centers,pitch,empty_reference):
        """Learn small-unit patches from confident repetition on THIS board.

        No hero atlas, labels or expected ranks are read. The calibration only
        resolves broad unknown silhouettes, leaving compact candidates unchanged.
        """
        evidence=[self.estimate(image,c,pitch,empty_reference) for c in centers]
        crops=[cell_crop(image,c,pitch) for c in centers]
        # A high pair correlation establishes two visible copies, not exactly
        # two people. Compare distributed same-appearance features with another
        # pair before accepting a lowered pair as rank 2. No global y cutoff.
        lowered={}
        for i,result in enumerate(evidence):
            if result.tier!=2:continue
            for j,reference in enumerate(evidence):
                if i==j or reference.tier!=2:continue
                source_width=reference.matches[1][0]-reference.matches[0][0]
                target_width=result.matches[1][0]-result.matches[0][0]
                shift=self.align_pair(crops[j],crops[i],reference.pair_support or [],target_width/source_width)
                if shift is not None and shift>=6:
                    lowered[i]=shift;break
        for i,shift in lowered.items():
            evidence[i].tier=None
            evidence[i].reason='lowered_pair_possible_occluded_third'
            evidence[i].layout_shift=round(shift/96,3)
        templates=[]
        for center,result in zip(centers,evidence):
            if result.tier not in (2,3):continue
            crop=cell_crop(image,center,pitch)
            for x,y,w,h in result.matches:
                templates.append(crop[y:y+h,x:x+w].copy())
        for center,result in zip(centers,evidence):
            if result.occupied is not True or result.reason!='occupied_size_ambiguous':continue
            crop=cell_crop(image,center,pitch)
            candidates={1:[],4:[]}
            for template in templates:
                for scale in np.arange(.8,1.93,.04):
                    size=round(template.shape[0]*scale)
                    ref=cv2.resize(template,(size,size),interpolation=cv2.INTER_LINEAR)
                    # Exclude the upper neighbour's rim just as in pair matching.
                    region=crop[32:89,8:88]
                    if size>min(region.shape[:2]):continue
                    scores=[]
                    for angle in (-20,0,20):
                        rotation=cv2.getRotationMatrix2D((size/2,size/2),angle,1)
                        rotated=cv2.warpAffine(ref,rotation,(size,size),borderMode=cv2.BORDER_REFLECT_101)
                        scores.append(cv2.matchTemplate(region,rotated,cv2.TM_CCOEFF_NORMED))
                    _,score,_,loc=cv2.minMaxLoc(np.maximum.reduce(scores))
                    if score<.82:continue
                    rank=1 if scale<=1.16 else 4 if scale>=1.36 else None
                    if rank:candidates[rank].append((score,[loc[0]+8,loc[1]+32,size,size]))
            best={rank:max(rows,default=(0,[])) for rank,rows in candidates.items()}
            rank=max(best,key=lambda k:best[k][0]);other=4 if rank==1 else 1
            if best[rank][0]>=.82 and best[rank][0]-best[other][0]>=.06:
                result.tier=rank;result.reason='same_board_small_unit_calibration'
                result.matches=[best[rank][1]]
        return evidence

    def estimate(self,image,center,pitch,empty_reference):
        if pitch<=0:raise ValueError('Positive pitch required')
        crop=cell_crop(image,center,pitch)
        if crop is None:return StructureEvidence(None,None,'clipped_cell')
        if empty_reference is None:return StructureEvidence(None,None,'empty_reference_required')
        ref=cv2.resize(empty_reference,(96,101),interpolation=cv2.INTER_AREA)
        # Small brightness changes are not people. Keep colour and outline changes.
        delta=crop.astype(np.float32)-ref.astype(np.float32)
        delta-=np.median(delta[50:88,10:86],axis=(0,1))
        difference=np.max(np.abs(delta),axis=2)
        mask=(difference>32).astype(np.uint8)
        mask[:12]=0;mask[89:]=0;mask[:,:7]=0;mask[:,89:]=0
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        fraction=float(mask[45:87,14:82].mean())
        if fraction<.025:return StructureEvidence(False,None,'empty',round(fraction,3),matches=[])
        if fraction<.09:return StructureEvidence(None,None,'weak_foreground',round(fraction,3),matches=[])
        # Repeated, textured foreground patches in left/right/upper positions.
        # Background, tile edges and tiny identical eyes must not dominate a match.
        pair=(0,[]);triple=(0,[])
        for size in (22,28,34):
            # Lower heads belong to this cell. The upper strip may contain the
            # repeated rims/feet of the row above; never seed a pair from it.
            for y in range(47,67,5):
                for x in range(8,40-size//2,5):
                    patch=crop[y:y+size,x:x+size]
                    if mask[y:y+size,x:x+size].mean()<.40:continue
                    if np.mean(patch.std(axis=(0,1)))<23:continue
                    xa,xb=x+27,min(96-size,x+56)
                    ya,yb=max(12,y-7),min(89-size,y+7)
                    if xa>xb or ya>yb:continue
                    region=crop[ya:yb+size,xa:xb+size]
                    corr=cv2.matchTemplate(region,patch,cv2.TM_CCOEFF_NORMED)
                    _,score,_,loc=cv2.minMaxLoc(corr)
                    rx,ry=xa+loc[0],ya+loc[1]
                    if mask[ry:ry+size,rx:rx+size].mean()<.4:continue
                    boxes=[[x,y,size,size],[rx,ry,size,size]]
                    if score>pair[0]:pair=(float(score),boxes)
                    # The third copy should be above, near the pair's midpoint.
                    tx=round((x+rx)/2);ty=y-25
                    a,b=max(0,tx-8),max(10,ty-12)
                    c,d=min(96-size,tx+8),min(y-14,ty+8)
                    if c<a or d<b:continue
                    corr=cv2.matchTemplate(crop[b:d+size,a:c+size],patch,cv2.TM_CCOEFF_NORMED)
                    _,third,_,loc=cv2.minMaxLoc(corr)
                    ux,uy=a+loc[0],b+loc[1]
                    if mask[uy:uy+size,ux:ux+size].mean()<.4:continue
                    joint=min(float(score),float(third))
                    if joint>triple[0]:triple=(joint,boxes+[[ux,uy,size,size]])
        # Width measured over foreground pixels, robust to isolated particles.
        yy,xx=np.where(mask[47:85])
        width=float((np.quantile(xx,.95)-np.quantile(xx,.05))/96) if len(xx) else 0
        tier=None;reason='occupied_size_ambiguous';matches=[]
        if triple[0]>=.77:tier=3;reason='three_repeated_regions';matches=triple[1]
        elif pair[0]>=.80:tier=2;reason='two_repeated_regions';matches=pair[1]
        elif width<.65:tier=1;reason='compact_single_candidate'
        # Broad silhouettes alone cannot distinguish a large hero from effects,
        # weapons or an occluded group. Rank 4 needs calibrated size evidence.
        center_y,support=self.pair_geometry(crop,mask,pair[1]) if pair[0]>=.8 else (None,[])
        return StructureEvidence(True,tier,reason,round(fraction,3),round(width,3),
                                 round(pair[0],3),round(triple[0],3),matches,center_y,support)


def inspect_samples(manifest,output):
    import json
    from pathlib import Path
    manifest=Path(manifest);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    groups=json.loads(manifest.read_text(encoding='utf8'))['images'];results=[]
    detector=StructureVision()
    for group in groups:
        image=cv2.imread(str(manifest.parent/group['file']))
        reference=cell_crop(image,group['empty_center'],group['pitch'])
        rows=[];tiles=[]
        evidence=detector.estimate_board(image,[c['center'] for c in group['cells']],group['pitch'],reference)
        for i,(cell,result) in enumerate(zip(group['cells'],evidence)):
            rows.append(dict(cell=cell,evidence=result.as_dict()))
            tile=cell_crop(image,cell['center'],group['pitch'])
            for x,y,w,h in result.matches or []:
                cv2.rectangle(tile,(x,y),(x+w,y+h),(80,230,80),1)
            tile=cv2.copyMakeBorder(cv2.resize(tile,(192,202)),0,60,0,0,cv2.BORDER_CONSTANT)
            for line,text in enumerate((f'{i+1}: expected {cell["expected"]}, got {result.tier}',
                                        f'occupied={result.occupied} width={result.width:.2f}',
                                        f'pair={result.pair_score:.2f} triple={result.triple_score:.2f}')):
                cv2.putText(tile,text,(3,219+line*18),cv2.FONT_HERSHEY_SIMPLEX,.36,(255,255,255),1)
            tiles.append(tile)
        while len(tiles)%3:tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(str(output/(group['id']+'.png')),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
        results.append(dict(id=group['id'],rows=rows))
    (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    for group in inspect_samples(args.manifest,args.output):
        print(group['id'])
        for row in group['rows']:print(row)
