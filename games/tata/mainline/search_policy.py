"""Prior-guided original-Lua search with persistent cases and online preference learning."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import random

from combat import Simulator,LIMITATIONS
from experience import Experience,DEFAULT_PATH,context_for,stable_hash,plan_key
from model import Catalog,RUNTIME,read_json,write_json
from tactics import Tactics,BASE_WEIGHTS,FEATURE_VERSION


def search(sim,stage,budget=120,seed=123456,progress=None,initial_plan=None,experience=None):
    if budget<1:raise ValueError('预算必须为正整数')
    rng=random.Random(seed);tactics=Tactics(sim,stage)
    context=context_for(sim,stage,tactics);engine=getattr(sim,'engine_fingerprint','test-engine')
    weights,old_updates=experience.weights(engine) if experience else (dict(BASE_WEIGHTS),0)
    before=experience.stats(engine) if experience else {}
    memories=experience.retrieve(engine,context) if experience else []
    initial=[(tactics.repair(m['placements']),'experience',None) for m in memories]
    if initial_plan:initial.insert(0,(tactics.repair(initial_plan),'manual-seed',None))
    initial=initial[:max(0,budget-1)]
    initial += [(tactics.seed(rng,i),'tactical-seed',None) for i in range(2)]
    initial += tactics.community_seeds()
    initial += [(tactics.seed(rng,i),'tactical-seed',None) for i in range(2,4)]
    cache={};ranked=[];operators={};learned=0

    def evaluate(plan,origin,parent=None):
        nonlocal weights,learned
        k=plan_key(plan)
        if k in cache:return None
        outcome=sim.evaluate(stage,plan,seed)
        features=tactics.features(plan)
        candidate=dict(placements=plan,evaluation=outcome,score=outcome['score'],origin=origin,
                       tactical_features=features)
        if experience:
            identifier=experience.record(engine,context,plan,features,outcome)
            candidate['evidence_id']=identifier
            if parent and experience.learn(engine,identifier,parent['evidence_id']):
                learned+=1;weights,_=experience.weights(engine)
        cache[k]=candidate;ranked.append(candidate);ranked.sort(key=lambda c:c['score'],reverse=True)
        operators[origin]=operators.get(origin,0)+1
        if progress:progress(len(cache),budget,ranked[0])
        return candidate

    for plan,origin,parent in initial:
        if len(cache)>=budget:break
        evaluate(plan,origin,parent)
    attempts=0
    while len(cache)<budget and attempts<budget*40:
        attempts+=1
        if rng.random()<.15:
            evaluate(tactics.seed(rng,1),'restart');continue
        parent=ranked[0] if rng.random()<.6 else rng.choice(ranked[:min(8,len(ranked))])
        pool=[]
        for _ in range(18):
            plan,origin=tactics.mutate(parent['placements'],rng)
            if plan_key(plan) not in cache:pool.append((plan,origin))
        if not pool:continue
        if rng.random()<.25:plan,origin=rng.choice(pool);origin='explore-'+origin
        else:plan,origin=max(pool,key=lambda p:tactics.score(p[0],weights))
        evaluate(plan,origin,parent)
    finalists=[]
    for candidate in ranked[:3]:
        validation=[sim.evaluate(stage,candidate['placements'],s) for s in (701,2029,8191)]
        finalists.append(dict(candidate,validation=validation,validation_wins=sum(v['won'] for v in validation)))
    finalists.sort(key=lambda p:(p['validation_wins'],sum(v['score'] for v in p['validation'])),reverse=True)
    best=finalists[0];replay=sim.evaluate(stage,best['placements'],seed,trace=True)
    if experience:
        for candidate in finalists:
            for outcome in candidate['validation']:
                experience.record(engine,context,candidate['placements'],candidate['tactical_features'],outcome)
    for candidate in finalists:candidate['explanations']=tactics.explain(candidate['placements'])
    return dict(schema_version=2,stage_id=stage['stage']['ID'],stage_name=stage['stage']['DisplayName'],
        created_at=datetime.now(timezone.utc).isoformat(),mode='original-lua-adaptive-v2',
        simulated=True,calibrated=False,budget=budget,evaluated=len(cache),search_seed=seed,
        placements=best['placements'],evaluation=replay,finalists=finalists,
        explanations=tactics.explain(best['placements']),feature_version=FEATURE_VERSION,
        tactical_features=best['tactical_features'],proposal_weights=weights,
        experience=dict(enabled=bool(experience),path=str(experience.path) if experience else None,
            before=before,after=experience.stats(engine) if experience else {},
            retrieved=[{k:v for k,v in m.items() if k!='placements'} for m in memories],
            previous_updates=old_updates,new_updates=learned,operators=operators),
        engine_fingerprint=engine,context_hash=stable_hash(context),context=context,
        attribute_validation=sim.attribute_validation,limitations=LIMITATIONS,
        capture_sha256=stable_hash(sim.capture),capture_time=sim.capture['captured_at'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,default=RUNTIME/'live-capture.json')
    p.add_argument('--stage',default='11-26');p.add_argument('--budget',type=int,default=120)
    p.add_argument('--out',type=Path,default=RUNTIME/'search-result.json');p.add_argument('--initial',type=Path)
    p.add_argument('--experience',type=Path,default=DEFAULT_PATH)
    p.add_argument('--no-experience',action='store_true',help='Independent cold search; neither reads nor writes experience')
    a=p.parse_args()
    if not 4<=a.budget<=10000:p.error('budget must be 4–10000')
    c=Catalog();stage=c.stage(next((s['id'] for s in c.stages if s['name']==a.stage),a.stage))
    sim=Simulator(read_json(a.capture),c)
    def progress(n,total,best):
        v=best['evaluation']
        write_json(a.out.with_suffix('.progress.json'),dict(stage_id=stage['stage']['ID'],evaluated=n,budget=total,
            simulated=True,calibrated=False,mode='original-lua-adaptive-v2',**best))
        if n<=4 or n%10==0:print(f'{n}/{total} best: won={v["won"]} kills={v["kills"]}/{v["total_enemies"]} time={v["battle_secs"]}',flush=True)
    memory=None if a.no_experience else Experience(a.experience)
    try:
        result=search(sim,stage,a.budget,progress=progress,experience=memory,
                      initial_plan=read_json(a.initial)['placements'] if a.initial else None)
        write_json(a.out,result)
        print(f'Finished {result["evaluated"]} candidates; held-out wins: {result["finalists"][0]["validation_wins"]}/3; learned pairs: {result["experience"]["new_updates"]}',flush=True)
    finally:
        if memory:memory.close()


if __name__=='__main__':main()
