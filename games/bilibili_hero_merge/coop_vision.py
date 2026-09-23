"""Co-op image adapter. Coordinates are always 432x768 reference pixels."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import re
import cv2
import numpy as np
from coop_ui import unique_name

XS = {'host': (77,111,146), 'guest': (285,320,355)}
ROWS = (391,425,460,494,527,562,596)
PRICE_BOXES = {'upgrade':(141,750,168,766), 'summon':(277,750,304,766),
               'money':(132,646,177,667)}
BUTTONS = {'upgrade':(153,741), 'summon':(290,741)}


def raw_box(box):
    return tuple(round(v*2.5) for v in box)


def read_prices(reader, raw):
    texts={key:reader.text(raw,raw_box(box)) for key,box in PRICE_BOXES.items()}
    values={key:reader.number(text) for key,text in texts.items()}
    if '免费' in texts['summon']:
        values['summon']=0
    return values,texts


def layer(labels, host, guest, stage):
    text=' '.join(p.text for p in labels)
    if '点击空白处关闭' in text:
        return 'reward'
    if any(('请选择' in p.text or '选择强化' in p.text) and 100<p.y<300 for p in labels):
        return 'choice'
    if any(w in text for w in ('战斗胜利','挑战成功','挑战失败','战斗失败')) or (
            '返回' in text and ('胜利' in text or '失败' in text)):
        return 'settled'
    if '继续游戏' in text or '继续战斗' in text:
        return 'paused'
    host_label,guest_label=unique_name(labels,host),unique_name(labels,guest)
    if (host_label and guest_label and host_label.x<195 and guest_label.x>240
            and host_label.y<100 and guest_label.y<100
            and any(floor_number(p.text)==stage and p.y<100 for p in labels)
            and any('波次' in p.text and p.y<130 for p in labels)):
        return 'battle'
    return 'unknown'


def floor_number(text):
    # The saved floor-1 screenshot is consistently read as 第I层. Limit this
    # substitution to the complete floor title, never account names/numbers.
    match=re.fullmatch(r'第([0-9]+|[Il丨])层',text)
    if not match:return None
    return 1 if match[1] in ('I','l','丨') else int(match[1])


def wave_number(labels):
    for p in labels:
        match=re.search(r'波次[:：]?(\d+)',p.text)
        if match and p.y<130:
            return int(match[1])
    return None


def modal_token(labels):
    # Stable card titles; ignore damage numbers and animated battlefield.
    words=sorted(p.text for p in labels if 200<p.y<240 and p.confidence>.85)
    return hashlib.sha256('|'.join(words).encode()).hexdigest()[:16]


@dataclass
class Board:
    cells: set
    occupied: set
    uncertain: set
    scores: dict

    @property
    def verified(self):
        return len(self.cells)>=7 and not self.uncertain


class BoardVision:
    @staticmethod
    def consensus(boards, required=()):
        """Vote only within one input-free burst; never carry old unit states."""
        cells,occupied,uncertain=set(),set(),set()
        candidates=set(required).union(*(b.cells | b.uncertain for b in boards))
        for pos in candidates:
            empty=sum(pos in b.cells and pos not in b.occupied and pos not in b.uncertain for b in boards)
            filled=sum(pos in b.occupied and pos not in b.uncertain for b in boards)
            # A contradictory definite reading may be a moving unit/animation.
            if empty and filled:
                uncertain.add(pos)
            elif max(empty,filled)>=2:
                cells.add(pos)
                if filled:occupied.add(pos)
            elif pos in required or pos in boards[-1].cells:
                uncertain.add(pos)
        scores=boards[-1].scores if boards else {}
        return Board(cells,occupied,uncertain,scores)

    def __init__(self):
        root=Path(__file__).with_name('assets')/'coop'
        self.bases=[cv2.imread(str(p),0) for p in sorted(root.glob('base-*.png'))]
        self.empty=[cv2.imread(str(p),0) for p in sorted(root.glob('empty-*.png'))]
        if not self.bases or not self.empty:
            raise RuntimeError('Missing co-op board templates')

    def read(self, raw, side):
        if side not in XS:
            raise ValueError('Unknown board side')
        im=cv2.resize(raw,(432,768),interpolation=cv2.INTER_AREA)
        gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        cells,occupied,uncertain,scores=set(),set(),set(),{}
        for y in ROWS:
            for x in XS[side]:
                # Scan only the observed grid; require an actual matching tile
                # pedestal, including expansion cells. Never tap a candidate.
                patch=gray[y+10:y+24,x-14:x+14]
                best=max(self.match(patch,ref) for ref in self.bases)
                scores[(x,y)]=round(best,3)
                if best<.58:
                    if best>=.55:
                        uncertain.add((x,y))
                    continue
                cells.add((x,y))
                center=gray[y-12:y+9,x-12:x+12]
                empty_score=max(self.match(center,ref) for ref in self.empty)
                if empty_score>.65 and center.std()<16:
                    continue
                if center.std()>22:
                    occupied.add((x,y))
                else:
                    uncertain.add((x,y))
        return Board(cells,occupied,uncertain,scores)

    @staticmethod
    def match(patch, ref):
        corr=float(cv2.matchTemplate(patch,ref,cv2.TM_CCOEFF_NORMED)[0,0])
        error=float(np.abs(patch.astype(float)-ref.astype(float)).mean())
        return corr-.004*error


def owner_side(raw):
    """Own name is blue; verified against both devices' lobby identities."""
    im=cv2.resize(raw,(432,768),interpolation=cv2.INTER_AREA)
    votes={}
    for side,x in [('host',104),('guest',332)]:
        hsv=cv2.cvtColor(im[61:75,x-35:x+35],cv2.COLOR_BGR2HSV)
        h,s,v=cv2.split(hsv)
        red=float(np.mean(((h<15)|(h>165))&(s>90)&(v>90)))
        blue=float(np.mean((h>90)&(h<135)&(s>90)&(v>70)))
        votes[side]=(red,blue)
    if votes['host'][0]>.20 and votes['guest'][1]>.20 and votes['host'][1]<.10:
        return 'guest'
    if votes['guest'][0]>.20 and votes['host'][1]>.20 and votes['guest'][1]<.10:
        return 'host'
    return None
