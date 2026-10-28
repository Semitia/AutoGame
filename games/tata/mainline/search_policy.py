"""Bounded roster/position search scored by the experimental original-Lua simulator."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random

from combat import Simulator, LIMITATIONS
from model import Catalog, RUNTIME, read_json, write_json
from policy import recommend, slots_for


def search(sim,stage,budget=120,seed=123456,progress=None,initial_plan=None):
    rng=random.Random(seed);slots=slots_for(stage)
    allowed=set(stage['waves'].get('CanUsePetIDs',{}).values())
    ids=[uid for uid in sim.rows if not allowed or uid in allowed]
    count=min(len(ids),len(slots),stage['waves']['CanDeployNum'])
    if count<1:raise ValueError('没有可用于搜索的塔塔')
    strongest=sorted(ids,key=lambda uid:sim.rows[uid]['gs'],reverse=True)
    front=sorted(slots,key=lambda p:(-p[1],p[0]))
    def formation(selected,positions):
        return [dict(unit_id=uid,x=pos[0],y=pos[1]) for uid,pos in zip(selected,positions)]
    initial=[recommend(sim.catalog,stage,sim.roster['pets'])[0]['placements'],
             formation(strongest[:count],slots),formation(strongest[:count],front)]
    # Spread the same roster over all legal rows as another starting point.
    scattered=rng.sample(slots,count);initial.append(formation(strongest[:count],scattered))
    if initial_plan:initial.insert(0,initial_plan)
    cache={};ranked=[]
    def key(p):return tuple(sorted((x['unit_id'],x['x'],x['y']) for x in p))
    def evaluate(plan):
        k=key(plan)
        if k in cache:return
        outcome=sim.evaluate(stage,plan,seed)
        candidate=dict(placements=plan,evaluation=outcome,score=outcome['score'])
        cache[k]=candidate;ranked.append(candidate);ranked.sort(key=lambda c:c['score'],reverse=True)
        if progress:progress(len(cache),budget,ranked[0])
    for p in initial[:budget]:evaluate(p)
    attempts=0
    while len(cache)<budget and attempts<budget*20:
        attempts+=1
        # Continue from the best or another leading candidate to retain alternatives.
        base=ranked[0] if rng.random()<.65 else rng.choice(ranked[:min(8,len(ranked))])
        plan=[dict(p) for p in base['placements']]
        action=rng.random()
        if action<.4 and len(ids)>count:
            unused=[u for u in ids if u not in {p['unit_id'] for p in plan}]
            weights=[max(1,sim.rows[u]['gs'])**2 for u in unused]
            plan[rng.randrange(count)]['unit_id']=rng.choices(unused,weights=weights)[0]
        elif action<.78 and count>1:
            a,b=rng.sample(range(count),2)
            plan[a]['x'],plan[b]['x']=plan[b]['x'],plan[a]['x']
            plan[a]['y'],plan[b]['y']=plan[b]['y'],plan[a]['y']
        else:
            empty=[p for p in slots if p not in {(x['x'],x['y']) for x in plan}]
            if empty:
                x,y=rng.choice(empty);plan[rng.randrange(count)].update(x=x,y=y)
            else:rng.shuffle(plan)
        evaluate(plan)
    finalists=[]
    for candidate in ranked[:3]:
        validation=[sim.evaluate(stage,candidate['placements'],s) for s in (701,2029,8191)]
        finalists.append(dict(candidate,validation=validation,
                               validation_wins=sum(v['won'] for v in validation)))
    finalists.sort(key=lambda p:(p['validation_wins'],sum(v['score'] for v in p['validation'])),reverse=True)
    best=finalists[0]
    replay=sim.evaluate(stage,best['placements'],seed,trace=True)
    return dict(schema_version=1,stage_id=stage['stage']['ID'],stage_name=stage['stage']['DisplayName'],
        created_at=datetime.now(timezone.utc).isoformat(),mode='original-lua-search-v1',
        simulated=True,calibrated=False,budget=budget,evaluated=len(cache),search_seed=seed,
        placements=best['placements'],evaluation=replay,finalists=finalists,
        attribute_validation=sim.attribute_validation,limitations=LIMITATIONS,
        capture_sha256=hashlib.sha256(json.dumps(sim.capture,sort_keys=True).encode()).hexdigest(),
        capture_time=sim.capture['captured_at'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,default=RUNTIME/'live-capture.json')
    p.add_argument('--stage',default='11-26');p.add_argument('--budget',type=int,default=120)
    p.add_argument('--out',type=Path,default=RUNTIME/'search-result.json')
    p.add_argument('--initial',type=Path)
    a=p.parse_args()
    if not 4<=a.budget<=10000:p.error('budget must be 4–10000')
    c=Catalog();stage=c.stage(next((s['id'] for s in c.stages if s['name']==a.stage),a.stage))
    sim=Simulator(read_json(a.capture),c)
    def progress(n,total,best):
        v=best['evaluation']
        write_json(a.out.with_suffix('.progress.json'),dict(stage_id=stage['stage']['ID'],evaluated=n,budget=total,
            simulated=True,calibrated=False,mode='original-lua-search-v1',**best))
        if n<=4 or n%10==0:print(f'{n}/{total} best: won={v["won"]} kills={v["kills"]}/{v["total_enemies"]} time={v["battle_secs"]}',flush=True)
    result=search(sim,stage,a.budget,progress=progress,
                  initial_plan=read_json(a.initial)['placements'] if a.initial else None);write_json(a.out,result)
    print(f'Finished {result["evaluated"]} candidates; independent-seed wins: {result["finalists"][0]["validation_wins"]}/3',flush=True)


if __name__=='__main__':main()
