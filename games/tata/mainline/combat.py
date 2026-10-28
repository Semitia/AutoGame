"""Experimental original-Lua battle evaluation and replay capture."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import tempfile

from headless import CombatRuntime
from model import Catalog, RUNTIME, read_json, write_json
from policy import recommend, slots_for
from live_roster import to_roster


LIMITATIONS = [
    '尚未与同阵容的游戏实战结算校准，模拟胜利不是通关保证',
    '寻路使用原包保留的 Lua 版本，尚未验证与原生寻路的路径选择完全一致',
    '当前角色属性来自读取时的观测；未同步的战斗专用温泉/场地技能可能影响结果',
]


def source_fingerprint(source):
    """Cache per-file content hashes; a fresh process need not reread 6,000 unchanged files."""
    cache_path=RUNTIME/'engine-fingerprint-cache.json'
    try:cache=read_json(cache_path)
    except (OSError,ValueError):cache={}
    digest=hashlib.sha256();entries={}
    paths=list(source.rglob('*.luae'))+list(source.rglob('*.pbe'))
    paths += [Path(__file__).with_name(n) for n in ('combat.py','headless.py','headless.lua')]
    for path in sorted(paths):
        name=str(path.resolve());stat=path.stat();signature=[stat.st_size,stat.st_mtime_ns]
        old=cache.get(name,{})
        content_hash=old['sha256'] if old.get('stat')==signature else hashlib.sha256(path.read_bytes()).hexdigest()
        entries[name]=dict(stat=signature,sha256=content_hash)
        relative=str(path.relative_to(source)) if path.is_relative_to(source) else path.name
        digest.update(relative.encode());digest.update(content_hash.encode())
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=cache_path.parent,delete=False) as stream:
        json.dump(entries,stream);temporary=Path(stream.name)
    temporary.replace(cache_path)
    return digest.hexdigest()


def pet_proto(row):
    if 'progress' not in row or 'badgeProps' not in row:
        raise ValueError('角色观测缺少等级进度或徽章加成，请重新从游戏同步')
    result={k:v for k,v in row.items() if k not in ('isGet','feed','gs')}
    result['feed']=dict(feedLv=row['feed']['feedLevel'],feedProgress=row['feed']['feedGrowth'],
                        todayFeedCnt=row['feed']['feedCount'])
    result['unitKey']={'staticUnitID':row['tid']}
    return result


class Simulator:
    def __init__(self,capture,catalog=None):
        self.catalog=catalog or Catalog()
        self.capture=capture
        self.roster=to_roster(capture,self.catalog)
        self.rows={p['tid']:p for p in capture['pets']}
        self.runtime=CombatRuntime();self.engine=self.runtime.initialize()
        self.protos={tid:self.runtime.value(pet_proto(row)) for tid,row in self.rows.items()}
        self.api=self.runtime.lua.execute('''return {
            frame=function(e)
                local units={}
                for _,u in ipairs(e.battleUnitSystem:ForeachUnitList()) do
                    if not u:IsFieldNpc() and u.hp>0 then
                        local x,y=u.transformComponent:GetPosition()
                        units[#units+1]={gid=u.gid,tid=u.tid,camp=u.camp,evolution=u.petData.evoTID,
                            x=x+.5,y=y+.5,hp=u.hp,max_hp=u.attribs:Get('HP')}
                    end
                end
                return {time=e.battleModule:GetElapsedTime(),units=units}
            end,
            run=function(e,trace)
                local frames={};local limit=math.ceil(e.battleModule.max_time/e.battleModule.dt)+8
                for i=0,limit do
                    if trace and (i%4==0 or e:IsEnd()) then frames[#frames+1]=trace(e) end
                    if e:IsEnd() then return frames end
                    e:Tick(e.battleModule.dt)
                end
                error('Battle did not settle within original time limit')
            end
        }''')
        mismatches=[];self.pet_facts={}
        skill_table=self.runtime.load_config('Skill')
        for tid,proto in self.protos.items():
            pd=self.runtime.env.ed.PetData.Create(proto)
            a=self.runtime.env.ed.PetAttribs.Create(pd,self.runtime.lua.table())
            a.Rebuild(a,'battle');actual=a.GetGS(a)
            sid=pd.GetBattleSkill(pd);cfg=skill_table[sid]
            def grids(prefix):
                manual=cfg[prefix+'Manual']
                if manual is not None and len(manual):
                    return [(manual[i],manual[i+1]) for i in range(1,len(manual),2)]
                rect=cfg[prefix+'Grid'];args=[rect[i] if rect is not None else None for i in range(1,5)]
                values=self.runtime.env.ed.CalcSkillGrids(cfg[prefix+'Dis'] or 0,*args)
                return [(v[1],v[2]) for _,v in values.items()]
            self.pet_facts[tid]=dict(hp=a.Get(a,'HP'),atk=a.Get(a,'ATK'),defense=a.Get(a,'DEF'),
                skill_id=sid,range_grids=grids('Range'),aoe_grids=grids('AOE'),
                target_camp=cfg.TargetCamp,description=cfg.Description or '')
            if actual!=self.rows[tid]['gs']:
                mismatches.append(dict(tid=tid,calculated=actual,observed=self.rows[tid]['gs']))
        self.attribute_validation=dict(checked=len(self.rows),matched=len(self.rows)-len(mismatches),mismatches=mismatches)
        if mismatches:
            raise ValueError(f'{len(mismatches)} 只塔塔的重算战力与游戏不同，暂停搜索，请核对版本/加成')
        # Learned evidence must not silently survive a different engine/configuration.
        self.engine_fingerprint=source_fingerprint(self.runtime.source)

    def evaluate(self,stage,placements,seed=123456,trace=False):
        start=time.perf_counter();r=self.runtime;e=self.engine
        slots=set(slots_for(stage));seen=set()
        if not placements or len(placements)>stage['waves']['CanDeployNum']:
            raise ValueError('上阵数量不合法')
        occupied=set();heroes=[]
        allowed=set(stage['waves'].get('CanUsePetIDs',{}).values())
        for p in placements:
            uid=p['unit_id'];slot=(p['x'],p['y'])
            if uid not in self.rows or uid in seen or slot not in slots or slot in occupied or (allowed and uid not in allowed):
                raise ValueError('阵容有重复、未拥有或不合法的角色/格子')
            seen.add(uid);occupied.add(slot)
            heroes.append(r.lua.table_from(dict(petData=self.protos[uid],config=r.value(dict(grid=dict(x=p['x'],y=p['y']),camp=1)))))
        stage_id=stage['stage']['ID'];battle_id=stage['battle']['BattleID']
        cb=r.value(dict(mode=1,battleID=battle_id,seed=seed,self_heroes=[],oppo_heroes=[],operations=[],
                        arg={'stageID':stage_id},ext={}))
        cb.self_heroes=r.lua.table_from(heroes)
        cb.enemy_round_configs=r.lua.table_from([r.env.ed.BattleConfigUtils.getBattleEnemyRoundConfig(battle_id,1)])
        cb.fieldNpcInfo=r.env.ed.ClientBattleBuilder._BuildFieldNpcInfo(r.value({'mode':1}),r.value({}))
        r.api.ui_events=r.lua.table()
        e.StartBattle(e,cb)
        frames=self.api.run(e,self.api.frame if trace else None)
        m=e.battleModule;end=e.battleEndCheckSystem
        units=e.battleUnitSystem.ForeachUnitList(e.battleUnitSystem)
        alive=[u for _,u in units.items() if u.hp>0 and not u.IsFieldNpc(u)]
        result=int(e.GetResult(e));total=e.enemySpawnSystem.GetTotalCount(e.enemySpawnSystem)
        remaining_hp=sum(u.hp for u in alive if u.camp==-1)
        kills=int(end.GetKillZombieCount(end))
        output=dict(result=result,won=result==1,kills=kills,total_enemies=total,
                    battle_secs=m.GetElapsedTime(m),damage=m.GetTotalDamage(m,1),
                    remaining_enemy_hp=remaining_hp,survivors=sum(u.camp==1 for u in alive),
                    seed=seed,compute_secs=round(time.perf_counter()-start,4))
        output['score']=outcome_score(output)
        if trace:
            output['frames']=[dict(time=f.time,units=[dict(u.items()) for _,u in f.units.items()]) for _,f in frames.items()]
        return output


def outcome_score(outcome):
    """Victory > one whole kill > bounded damage > bounded speed/survival tie breaks."""
    won=outcome['won'];seconds=outcome['battle_secs']
    total=max(1,outcome['total_enemies']);damage=outcome.get('damage',0)
    return ((1_000_000 if won else 0)+100_000*outcome['kills']/total+
            (100*damage/(damage+1e6)+(1/(1+seconds) if won else seconds/(1+seconds)))/(total+1))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,default=RUNTIME/'live-capture.json')
    p.add_argument('--stage',default='11-26');p.add_argument('--plan',type=Path)
    p.add_argument('--seed',type=int,default=123456)
    p.add_argument('--out',type=Path,default=RUNTIME/'simulation.json')
    p.add_argument('--no-experience',action='store_true')
    a=p.parse_args();c=Catalog();stage=c.stage(next((s['id'] for s in c.stages if s['name']==a.stage),a.stage))
    s=Simulator(read_json(a.capture),c)
    placements=read_json(a.plan)['placements'] if a.plan else recommend(c,stage,s.roster['pets'])[0]['placements']
    result=s.evaluate(stage,placements,a.seed,trace=True)
    from experience import Experience,context_for,stable_hash
    from tactics import Tactics,FEATURE_VERSION
    tactics=Tactics(s,stage);context=context_for(s,stage,tactics);features=tactics.features(placements)
    memory=None if a.no_experience else Experience()
    try:
        if memory:memory.record(s.engine_fingerprint,context,placements,features,result)
        evidence=dict(enabled=bool(memory),after=memory.stats(s.engine_fingerprint) if memory else {},retrieved=[])
    finally:
        if memory:memory.close()
    report=dict(schema_version=1,simulated=True,calibrated=False,stage_id=stage['stage']['ID'],
                placements=placements,evaluation=result,attribute_validation=s.attribute_validation,limitations=LIMITATIONS,
                engine_fingerprint=s.engine_fingerprint,context=context,context_hash=stable_hash(context),
                feature_version=FEATURE_VERSION,tactical_features=features,explanations=tactics.explain(placements),
                experience=evidence,capture_time=s.capture['captured_at'])
    write_json(a.out,report)
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},ensure_ascii=False))


if __name__=='__main__':main()
