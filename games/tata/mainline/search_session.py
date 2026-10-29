"""Interruptible, resumable search over formations and sampled input orders."""
from datetime import datetime,timezone
from pathlib import Path
import math
import random
import time

from combat import LIMITATIONS
from experience import context_for,stable_hash,plan_key,formation_key
from model import read_json,write_json
from tactics import Tactics,BASE_WEIGHTS,FEATURE_VERSION


REASONS={
    'verified':'找到全部复核通过的候选',
    'candidate_limit':'达到候选数量上限',
    'time_limit':'达到搜索时长上限',
    'user_stop':'用户停止搜索，已保留最佳候选和进度',
    'stagnation':'连续生成重复候选，已保存当前结果',
}


class SearchHalt(Exception):
    def __init__(self,reason):self.reason=reason


def tuple_tree(value):return tuple(tuple_tree(v) for v in value) if isinstance(value,list) else value


def order_samples(plan,robust):
    choices=[('input',plan)]
    if robust:
        choices += [('column-forward',sorted(plan,key=lambda p:(p['x'],p['y']))),
                    ('column-backward',sorted(plan,key=lambda p:(p['x'],-p['y'])))]
    seen=set();result=[]
    for name,rows in choices:
        key=plan_key(rows)
        if key not in seen:seen.add(key);result.append((name,rows))
    return result


def rank(candidate):
    checks=candidate.get('validation',[])
    complete=candidate.get('validation_complete',False)
    passed=complete and checks and all(v['won'] for v in checks) and candidate['evaluation']['won']
    fraction=sum(v['won'] for v in checks)/len(checks) if checks else 0
    scores=[candidate['score']]+[v['score'] for v in checks]
    return bool(passed),fraction,bool(candidate['evaluation']['won']),min(scores),sum(scores)/len(scores)


def run_search(sim,stage,budget=120,seed=123456,progress=None,initial_plan=None,experience=None,
               max_seconds=0,stop_path=None,stop_when_verified=False,checkpoint=None,resume=None,
               status=None,check_stop=None,robust_orders=False,clock=None):
    """Limits apply between VM evaluations; 0 disables that limit.

    Resume grants a new time/candidate allowance and retains the accumulated
    cases, RNG, coverage cursor and seen set. A new roster/version is rejected.
    """
    if type(budget) is not int or budget<0:raise ValueError('候选上限应为非负整数，0表示不限')
    if not math.isfinite(max_seconds) or max_seconds<0:raise ValueError('搜索时长应为非负有限数，0表示不限')
    clock=clock or time.monotonic;started=clock();last_checkpoint=started
    rng=random.Random(seed);tactics=Tactics(sim,stage)
    context=context_for(sim,stage,tactics);context_hash=stable_hash(context)
    engine=getattr(sim,'engine_fingerprint','test-engine')
    weights,old_updates=experience.weights(engine) if experience else (dict(BASE_WEIGHTS),0)
    before=experience.stats(engine) if experience else {}
    memories=experience.retrieve(engine,context) if experience else []
    seen=set();elite=[];operators={};learned=0;evaluated=0;simulations=0;previous_elapsed=0
    coverage_base=tactics.repair(initial_plan) if initial_plan else tactics.seed(rng,0)
    coverage_index=0;coverage_round=1;coverage_checked=0;coverage_bases={formation_key(coverage_base)};reason=None
    if resume:
        saved=read_json(resume)
        if (saved.get('schema_version')!=1 or saved.get('engine_fingerprint')!=engine or
            saved.get('context_hash')!=context_hash or saved.get('search_seed')!=seed or
            saved.get('robust_orders')!=robust_orders):
            raise ValueError('搜索进度与当前关卡、角色池、引擎或复核设置不一致；请开始新搜索')
        rng.setstate(tuple_tree(saved['rng_state']));seen=set(saved['seen']);elite=saved['elite']
        evaluated=saved['evaluated'];simulations=saved['simulations'];previous_elapsed=saved['elapsed_seconds']
        coverage_base=saved['coverage_base'];coverage_index=saved['coverage_index'];operators=saved['operators']
        coverage_round=saved.get('coverage_round',1);coverage_checked=saved.get('coverage_checked',coverage_index)
        coverage_bases=set(saved.get('coverage_bases',[formation_key(coverage_base)]))
        # Evidence IDs only refer to the experience DB that created them.
        for candidate in elite:candidate.pop('evidence_id',None)
    baseline=evaluated;coverage=list(tactics.single_replacements(coverage_base))
    # Priors order the exhaustive sweep; they never remove a legal substitution.
    coverage.sort(key=lambda p:tactics.score(p,weights),reverse=True)
    if resume and saved.get('coverage') is not None:coverage=saved['coverage']
    if resume and saved.get('coverage_order') is not None:
        coverage=[[dict(p,unit_id=after if p['unit_id']==before else p['unit_id']) for p in coverage_base]
                  for before,after in saved['coverage_order']]
    coverage_order=[next((before['unit_id'],after['unit_id']) for before,after in zip(coverage_base,plan)
        if before['unit_id']!=after['unit_id']) for plan in coverage]
    initial=[(coverage_base,'manual-seed' if initial_plan else 'tactical-seed',None)]
    initial += list(tactics.player_seeds(coverage_base))
    initial += [(tactics.repair(m['placements']),'experience',None) for m in memories]
    initial += tactics.community_seeds()
    initial += [(tactics.seed(rng,i),'tactical-seed',None) for i in range(1,4)]

    def stopped(candidates=False):
        if check_stop and check_stop():return 'user_stop'
        if stop_path and Path(stop_path).exists():return 'user_stop'
        if max_seconds and clock()-started>=max_seconds:return 'time_limit'
        if candidates and budget and evaluated-baseline>=budget:return 'candidate_limit'
        return None

    def sort_elite():
        elite.sort(key=rank,reverse=True);del elite[48:]

    def save(force=False):
        nonlocal last_checkpoint
        if not checkpoint or (not force and clock()-last_checkpoint<30):return
        sort_elite()
        write_json(checkpoint,dict(schema_version=1,engine_fingerprint=engine,context_hash=context_hash,
            search_seed=seed,robust_orders=robust_orders,rng_state=rng.getstate(),seen=sorted(seen),elite=elite,
            evaluated=evaluated,simulations=simulations,elapsed_seconds=previous_elapsed+clock()-started,
            coverage_base=coverage_base,coverage_index=coverage_index,coverage_order=coverage_order,operators=operators,
            coverage_round=coverage_round,coverage_checked=coverage_checked,coverage_bases=sorted(coverage_bases)))
        last_checkpoint=clock()

    def emit(phase):
        sort_elite();best=elite[0] if elite else None
        payload=dict(status='searching',phase=phase,evaluated=evaluated,run_evaluated=evaluated-baseline,
            budget=budget,max_seconds=max_seconds,elapsed_seconds=previous_elapsed+clock()-started,
            run_elapsed_seconds=clock()-started,simulations=simulations,
            replacement_checked=coverage_index,replacement_total=len(coverage),replacement_round=coverage_round,
            replacement_checked_total=coverage_checked)
        if best:
            payload.update(evaluation=best['evaluation'],placements=best['placements'],
                validation_wins=sum(v['won'] for v in best.get('validation',[])),
                validation_total=best.get('validation_expected',0),validation_checked=len(best.get('validation',[])))
        if status:status(payload)
        if progress and best:progress(evaluated,budget,best)
        save()

    def simulate(plan,number):
        nonlocal simulations
        halt=stopped()
        if halt:raise SearchHalt(halt)
        value=sim.evaluate(stage,plan,number);simulations+=1
        return value

    def record(plan,features,outcome):
        return experience.record(engine,context,plan,features,outcome) if experience else None

    def validate(candidate):
        checks=candidate.setdefault('validation',[])
        samples=order_samples(candidate['placements'],robust_orders)
        tasks=[(name,rows,s) for name,rows in samples for s in (701,2029,8191)]
        candidate['validation_expected']=len(tasks)
        candidate['validation_complete']=False
        for name,rows,number in tasks[len(checks):]:
            outcome=simulate(rows,number)
            checks.append(dict(outcome,order_mode=name))
            record(rows,candidate['tactical_features'],outcome)
            emit('validating')
        candidate['validation_complete']=True
        candidate['validation_wins']=sum(v['won'] for v in checks)
        candidate['explanations']=tactics.explain(candidate['placements'])

    def evaluate(plan,origin,parent=None):
        nonlocal evaluated,learned,weights
        key=plan_key(plan)
        if key in seen:return
        outcome=simulate(plan,seed);seen.add(key);evaluated+=1
        features=tactics.features(plan)
        candidate=dict(placements=plan,evaluation=outcome,score=outcome['score'],origin=origin,
            tactical_features=features,validation=[],validation_complete=False,validation_expected=3)
        identifier=record(plan,features,outcome)
        if identifier is not None:candidate['evidence_id']=identifier
        if experience and parent and parent.get('evidence_id') is not None:
            if experience.learn(engine,identifier,parent['evidence_id']):
                learned+=1;weights,_=experience.weights(engine)
        elite.append(candidate);operators[origin]=operators.get(origin,0)+1
        # Check every training winner immediately, rather than only three fast
        # winners at shutdown. A slower but stable candidate remains selectable.
        if outcome['won']:validate(candidate)
        emit(origin)
        if stop_when_verified and rank(candidate)[0]:raise SearchHalt('verified')

    emit('resuming' if resume else 'starting')
    try:
        if stop_when_verified and any(rank(c)[0] for c in elite):raise SearchHalt('verified')
        for candidate in list(elite):
            if candidate['evaluation']['won'] and not candidate.get('validation_complete'):validate(candidate)
        for plan,origin,parent in initial:
            reason=stopped(candidates=True)
            if reason:break
            evaluate(plan,origin,parent)
        attempts=0
        while reason is None:
            reason=stopped(candidates=True)
            if reason:break
            sort_elite()
            if coverage_index>=len(coverage) and elite and formation_key(elite[0]['placements']) not in coverage_bases:
                coverage_base=[dict(p) for p in elite[0]['placements']]
                coverage_bases.add(formation_key(coverage_base));coverage_round+=1;coverage_index=0
                coverage=list(tactics.single_replacements(coverage_base));coverage.sort(key=lambda p:tactics.score(p,weights),reverse=True)
                coverage_order=[next((a['unit_id'],b['unit_id']) for a,b in zip(coverage_base,plan)
                    if a['unit_id']!=b['unit_id']) for plan in coverage]
            attempts+=1
            if attempts>max(1000,(evaluated-baseline+1)*80):reason='stagnation';break
            if coverage_index<len(coverage) and attempts%2:
                plan=coverage[coverage_index];coverage_index+=1;coverage_checked+=1
                evaluate(plan,'single-replacement');continue
            if rng.random()<.15:
                evaluate(tactics.seed(rng,1),'restart');continue
            sort_elite()
            parent=elite[0] if rng.random()<.6 else rng.choice(elite[:min(12,len(elite))])
            pool=[]
            for _ in range(18):
                plan,origin=tactics.mutate(parent['placements'],rng)
                if plan_key(plan) not in seen:pool.append((plan,origin))
            if not pool:continue
            if rng.random()<.3:plan,origin=rng.choice(pool);origin='explore-'+origin
            else:plan,origin=max(pool,key=lambda p:tactics.score(p[0],weights))
            evaluate(plan,origin,parent)
    except SearchHalt as exc:reason=exc.reason
    finally:save(force=True)
    sort_elite()
    finalists=elite[:3]
    # Keep report shape useful even when the limit lands during initialization.
    best=finalists[0] if finalists else None
    passed=bool(best and rank(best)[0]);cancelled=reason=='user_stop'
    report=dict(schema_version=3,stage_id=stage['stage']['ID'],stage_name=stage['stage']['DisplayName'],
        created_at=datetime.now(timezone.utc).isoformat(),mode='original-lua-adaptive-v3',
        simulated=True,calibrated=False,budget=budget,evaluated=evaluated,run_evaluated=evaluated-baseline,
        max_seconds=max_seconds,elapsed_seconds=previous_elapsed+clock()-started,run_elapsed_seconds=clock()-started,
        simulations=simulations,status='cancelled' if cancelled else 'verified' if passed else 'no_solution',
        stop_reason=reason,reason=REASONS.get(reason,reason),search_seed=seed,finalists=finalists,
        checkpoint=str(checkpoint) if checkpoint else None,replacement_checked=coverage_index,replacement_total=len(coverage),
        replacement_round=coverage_round,replacement_checked_total=coverage_checked,
        feature_version=FEATURE_VERSION,proposal_weights=weights,robust_orders=robust_orders,
        experience=dict(enabled=bool(experience),path=str(experience.path) if experience else None,before=before,
            after=experience.stats(engine) if experience else {},retrieved=[{k:v for k,v in m.items() if k!='placements'} for m in memories],
            previous_updates=old_updates,new_updates=learned,operators=operators),
        engine_fingerprint=engine,context_hash=context_hash,context=context,
        attribute_validation=sim.attribute_validation,limitations=LIMITATIONS,
        capture_sha256=stable_hash(sim.capture),capture_time=sim.capture['captured_at'])
    if best:report.update({k:best[k] for k in ('placements','evaluation','tactical_features')},explanations=tactics.explain(best['placements']))
    if status:status(report)
    return report
