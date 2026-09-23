"""Best-effort visual rank recovery for identified units with unknown ranks.

User-authorized emergency mode: candidates may drive merges. Never overwrite
action-history ranks or use this to identify a hero or confirm a pending action.
"""
from tier_structure import StructureVision,cell_crop
from tier_vision import TierVision


class TierRescue:
    def __init__(self):
        self.structure=StructureVision()
        self.templates=TierVision()
        self.empty=None

    def recover(self,image,cells,occupied,units,pitch,log):
        targets=[p for p,u in units.items() if p in occupied and u.get('hero')
                 and u.get('tier',0)==0 and not u.get('uncertain')]
        if not targets:return 0
        for pos in sorted(set(cells)-set(occupied)):
            reference=cell_crop(image,pos,pitch)
            if reference is not None:
                self.empty=reference.copy();break
        positions=sorted(occupied)
        estimates=self.structure.estimate_board(image,positions,pitch,self.empty)
        by_pos=dict(zip(positions,estimates));changed=0
        for pos in targets:
            result=by_pos[pos];tier=result.tier;method='structure'
            evidence={'structure':result.as_dict()}
            if tier is None:
                fallback=self.templates.estimate(image,pos,pitch)
                evidence['template']=fallback.as_dict()
                tier=fallback.tier;method='head_template'
            log('visual_tier_recovery',cell=pos,hero=units[pos]['hero'],tier=tier,
                method=method,applied=tier in (1,2,3,4),evidence=evidence)
            if tier in (1,2,3,4):
                units[pos].update(tier=tier,tier_source='visual:'+method)
                changed+=1
        return changed
