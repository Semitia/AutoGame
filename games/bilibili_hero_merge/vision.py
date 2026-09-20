import re,time
from pathlib import Path
import cv2,numpy as np
from rapidocr_onnxruntime import RapidOCR

class Reader:
    def __init__(self):
        self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
    def text(self,image,box):
        x1,y1,x2,y2=box
        result,_=self.ocr(image[y1:y2,x1:x2],use_det=False,use_cls=False)
        return result[0][0] if result else ''
    def lines(self,image,box):
        x1,y1,x2,y2=box
        result,_=self.ocr(image[y1:y2,x1:x2],use_cls=False)
        return ' '.join(row[1] for row in (result or []))
    @staticmethod
    def number(text):
        text=text.strip().replace(',','').replace('O','0').replace('o','0')
        m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*([KkMm万]?)',text)
        if not m:return None
        return round(float(m[1])*{'':1,'k':1000,'m':1000000,'万':10000}[m[2].lower()])
    def prices(self,image):
        boxes={'upgrade':(302,1853,397,1890),'summon':(740,1853,824,1890),'money':(163,1675,263,1717)}
        texts={k:self.text(image,v) for k,v in boxes.items()}
        values={k:self.number(v) for k,v in texts.items()}
        for key in ['upgrade','summon']:
            if values[key] is not None:continue
            x1,y1,x2,y2=boxes[key];crop=image[y1:y2,x1:x2]
            h=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
            red=(h[:,:,0]<10)&(h[:,:,1]>130)&(h[:,:,2]>120)
            white=(h[:,:,1]<75)&(h[:,:,2]>190)
            bw=cv2.copyMakeBorder(255-(red|white).astype(np.uint8)*255,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
            for path in Path(__file__).with_name('assets').glob('price_*.png'):
                ref=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
                # Match the foreground glyphs independently of red/white price colour.
                def glyph(a):
                    points=cv2.findNonZero(255-a)
                    if points is None:return None
                    x,y,w,hh=cv2.boundingRect(points)
                    return cv2.resize(a[y:y+hh,x:x+w],(64,32))
                a,b=glyph(bw),glyph(ref)
                if a is not None and b is not None and np.mean(abs(a.astype(float)-b.astype(float)))<25:
                    values[key]=int(path.stem.split('_')[1]);break
        # Free first summon. Do not infer zero from failed OCR.
        if '免费' in texts['summon']:values['summon']=0
        return values,texts

def tile_scores(image,template):
    mask=np.ones(template.shape[:2],bool);mask[3:30,4:36]=False
    reference=template[mask].astype(float).flatten()
    out=[]
    for y in [560,517,474,431]:
        for x in [87,130,173,216,259,302,345]:
            patch=image[y-17:y+19,x-20:x+20]
            if patch.shape!=template.shape:continue
            observed=patch[mask].astype(float).flatten()
            correlation=float(np.corrcoef(observed,reference)[0,1])
            error=float(np.mean(abs(observed-reference)))
            out.append((correlation-.004*error,(x,y),correlation,error))
    return sorted(out,reverse=True)
