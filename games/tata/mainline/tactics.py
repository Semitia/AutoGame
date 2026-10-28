"""Soft, inspectable tactical priors. They propose plans; original Lua judges them."""
import math
from pathlib import Path
import json
from policy import slots_for


FEATURE_VERSION = 'tactics-1'
BASE_WEIGHTS = dict(strength=2., counter=2., frontline=1.8, protected=1.,
                    contact=1., position_hint=.3, aura=1.4, waterfly_row=2.,
                    community_pairs=.5, lane_balance=.7)


def values(table):
    return list(table.values()) if isinstance(table,dict) else list(table or [])


def stage_profile(stage):
    slots=slots_for(stage);xs=sorted({x for x,y in slots});ys=sorted({y for x,y in slots})
    lanes={x:{} for x in xs};enemies={};total=0
    for event in values(stage['waves'].get('Frame',{})):
        for wave in values(event.get('Waves',{})):
            uid=str(wave['EnemyID']);n=wave['Num'];total+=n
            element=stage['enemy_units'][uid].get('UnitElement',1)
            enemies[element]=enemies.get(element,0)+n
            cols=values(wave.get('Cols')) or xs
            # Expected allocation only; original wave RNG still runs in the simulator.
            for x in cols:
                if x in lanes:lanes[x][element]=lanes[x].get(element,0)+n/len(cols)
    return dict(xs=xs,ys=ys,lanes=lanes,enemies=enemies,total=total)


class Tactics:
    def __init__(self,sim,stage):
        self.sim,self.stage=sim,stage;self.profile=stage_profile(stage)
        self.slots=slots_for(stage);allowed=set(values(stage['waves'].get('CanUsePetIDs',{})))
        self.ids=[u for u in sim.rows if (not allowed or u in allowed) and
                  sim.catalog.pets[str(u)].get('CanDeployNum',0)>0]
        self.count=min(len(self.ids),len(self.slots),stage['waves']['CanDeployNum'])
        if not self.count:raise ValueError('没有可用于搜索的塔塔')
        self.units=sim.catalog.pets;self.facts=getattr(sim,'pet_facts',{})
        self.max_gs=max(1,max(sim.rows[u]['gs'] for u in self.ids))
        self.max_tough=max(1,max(self.toughness(u) for u in self.ids))

    def toughness(self,uid):
        f=self.facts.get(uid,{})
        # A ranking proxy, not the game's effective-HP formula.
        return f.get('hp',self.sim.rows[uid]['gs'])*math.sqrt(1+max(0,f.get('defense',0)))

    def power(self,uid):return math.sqrt(max(0,self.sim.rows[uid]['gs'])/self.max_gs)

    def forward_range(self,uid):
        return max((y for x,y in self.facts.get(uid,{}).get('range_grids',[]) if x==0),default=3)

    def front_fit(self,uid):
        # Skill reach and current stats matter more than official career labels.
        reach=self.forward_range(uid);unit=self.units[str(uid)]
        short=1. if reach<=2 else .6 if reach<=3 else 0.
        return .6*short+.3*math.sqrt(max(0,self.toughness(uid))/self.max_tough)+.1*(unit.get('PositionType')=='Front')

    def counter(self,uid,x):
        unit=self.units[str(uid)];counts=self.profile['lanes'][x];n=sum(counts.values()) or 1
        positive=set(values(unit.get('CounterElement',{})));negative=set(values(unit.get('WeakElement',{})))
        return sum(v*((e in positive)-.7*(e in negative)) for e,v in counts.items())/n

    def evo(self,uid):return self.sim.rows[uid].get('evoTID',1)

    def features(self,plan):
        n=max(1,len(plan));xs=self.profile['xs'];ys=self.profile['ys'];top=max(ys)
        f=dict.fromkeys(BASE_WEIGHTS,0.);by_id={p['unit_id']:p for p in plan}
        lanes={x:[p for p in plan if p['x']==x] for x in xs}
        power_by_lane=[]
        for x,line in lanes.items():
            if line:
                lead=max(line,key=lambda p:p['y']);f['frontline']+=self.front_fit(lead['unit_id'])/len(xs)
                power_by_lane.append(sum(self.power(p['unit_id']) for p in line))
            else:power_by_lane.append(0.)
        for p in plan:
            uid=p['unit_id'];x,y=p['x'],p['y'];unit=self.units[str(uid)];fact=self.facts.get(uid,{})
            f['strength']+=self.power(uid)/n
            f['counter']+=self.counter(uid,x)*self.power(uid)/n
            allies_ahead=[q for q in lanes[x] if q['y']>y]
            f['protected']+=(1-self.front_fit(uid))*bool(allies_ahead)/n
            offsets=set(map(tuple,fact.get('range_grids',[])))
            if offsets:
                f['contact']+=sum((col-x,top+1-y) in offsets for col in xs)/len(xs)/n
            hint=unit.get('PositionType');depth=(y-min(ys))/max(1,top-min(ys))
            f['position_hint']+=(depth if hint=='Front' else 1-depth if hint=='Back' else 1-abs(depth-.5))/n
            # Confirmed hero-specific auras; do not infer allies from generic AOE names.
            if uid in (27,40):
                area=set(map(tuple,fact.get('aoe_grids',[])))
                linked=[q for q in plan if q is not p and (q['x']-x,q['y']-y) in area]
                f['aura']+=sum(self.power(q['unit_id']) for q in linked)/max(1,min(n-1,8))
            if uid==46 and self.evo(uid)>=3:
                f['waterfly_row']+=sum(self.power(q['unit_id']) for q in plan if q['y']==y and q is not p)/max(1,len(xs)-1)
        # Firsthand player guide combinations, deliberately low-weight and optional.
        for a,b in ((56,11),(18,33)):
            if a in by_id and b in by_id:
                p,q=by_id[a],by_id[b]
                f['community_pairs']+=.5*(p['x']==q['x'])
        if power_by_lane:
            mean=sum(power_by_lane)/len(xs)
            f['lane_balance']=1/(1+sum(abs(v-mean) for v in power_by_lane)/len(xs))
        return f

    def score(self,plan,weights=None):
        f=self.features(plan);w=weights or BASE_WEIGHTS
        return sum(w.get(k,0)*v for k,v in f.items())

    def seed(self,rng,variant=0):
        """Build lane defenders first, then ranged/support around actual aura geometry."""
        xs=self.profile['xs'];top=max(self.profile['ys']);used=set();plan=[]
        # Allow a fresh rollout to change the composition rather than freezing a template.
        jitter={u:rng.uniform(-.2,.2)*(variant>0) for u in self.ids}
        def add(uid,pos):
            used.add(uid);plan.append(dict(unit_id=uid,x=pos[0],y=pos[1]))
        for x in sorted(xs,key=lambda x:-sum(self.profile['lanes'][x].values())):
            if len(plan)>=self.count:break
            pos=max((s for s in self.slots if s[0]==x),key=lambda s:s[1])
            uid=max((u for u in self.ids if u not in used),key=lambda u:
                2*self.front_fit(u)+self.power(u)+.7*self.counter(u,x)+jitter[u])
            add(uid,pos)
        # Prefer high-stat developed pets, but include learned/guide structure through position scoring.
        selected=sorted((u for u in self.ids if u not in used),key=lambda u:
            self.power(u)+max(self.counter(u,x) for x in xs)*.25+jitter[u],reverse=True)[:self.count-len(plan)]
        # Place local support before its recipients; don't strand the aura in a corner.
        selected.sort(key=lambda u:(u not in (40,27,46),-self.power(u)))
        for uid in selected:
            empty=[s for s in self.slots if s not in {(p['x'],p['y']) for p in plan}]
            def placement_score(pos):
                x,y=pos;depth=top-y
                # Reach-derived target depth (short range forward, long range behind defenders).
                target=min(max(self.profile['ys'])-min(self.profile['ys']),1 if self.forward_range(uid)>3 else 0)
                score=-.8*abs(depth-target)+self.counter(uid,x)*.9
                if uid in (40,27):
                    area=set(map(tuple,self.facts.get(uid,{}).get('aoe_grids',[])))
                    score+=.5*sum((p['x']-x,p['y']-y) in area for p in plan)
                if uid==46 and self.evo(uid)>=3:score+=.2*(len(xs)-abs(x-sum(xs)/len(xs)))
                if 46 in used and self.evo(46)>=3:
                    waterfly=next(p for p in plan if p['unit_id']==46)
                    score+=1.5*(y==waterfly['y'])
                return score+rng.uniform(-.15,.15)*(variant>0)
            add(uid,max(empty,key=placement_score))
        return plan

    def repair(self,plan):
        """Keep nearest legal positions; replace unavailable pets, never illegal slots."""
        output=[];used=set();occupied=set()
        # Preserve absolute legal positions first; incompatible layouts use nearest legal coordinates.
        for p in plan:
            if len(output)>=self.count:break
            uid=p['unit_id'];empty=[s for s in self.slots if s not in occupied]
            pos=min(empty,key=lambda s:abs(s[0]-p['x'])+abs(s[1]-p['y']))
            if uid not in self.ids or uid in used:
                uid=max((u for u in self.ids if u not in used),key=lambda u:self.power(u)+self.counter(u,pos[0]))
            used.add(uid);occupied.add(pos);output.append(dict(unit_id=uid,x=pos[0],y=pos[1]))
        for uid in sorted((u for u in self.ids if u not in used),key=self.power,reverse=True):
            if len(output)>=self.count:break
            pos=max((s for s in self.slots if s not in occupied),key=lambda s:self.counter(uid,s[0])-.1*abs(s[1]-max(self.profile['ys'])+1))
            occupied.add(pos);output.append(dict(unit_id=uid,x=pos[0],y=pos[1]))
        return output

    def community_seeds(self):
        """Small reviewed reference set, not an unverified web scrape or a mandatory lineup."""
        data=json.loads(Path(__file__).with_name('community_knowledge.json').read_text(encoding='utf-8'))
        results=[]
        for reference in data['formations']:
            rows=reference['rows_front_to_back']
            plan=[dict(unit_id=uid,x=x+1,y=len(rows)-i) for i,row in enumerate(rows) for x,uid in enumerate(row) if uid]
            results.append((self.repair(plan),'community:'+reference['id'],None))
        return results

    def mutate(self,base,rng):
        plan=[dict(p) for p in base];action=rng.randrange(5);n=len(plan)
        if action==0 and len(self.ids)>n:
            i=rng.randrange(n);p=plan[i];unused=[u for u in self.ids if u not in {p['unit_id'] for p in plan}]
            weights=[math.exp(2*self.power(u)+self.counter(u,p['x'])) for u in unused]
            p['unit_id']=rng.choices(unused,weights=weights)[0];name='replace'
        elif action==1 and n>1:
            a,b=rng.sample(range(n),2)
            plan[a]['x'],plan[b]['x']=plan[b]['x'],plan[a]['x']
            plan[a]['y'],plan[b]['y']=plan[b]['y'],plan[a]['y'];name='swap'
        elif action==2:
            empty=[s for s in self.slots if s not in {(p['x'],p['y']) for p in plan}]
            if empty:
                x,y=rng.choice(empty);rng.choice(plan).update(x=x,y=y)
            name='move'
        elif action==3 and len(self.profile['xs'])>1:
            # Coordinated lane swap retains support/frontline structure.
            a,b=rng.sample(self.profile['xs'],2)
            for p in plan:
                if p['x'] in (a,b):p['x']=b if p['x']==a else a
            name='lane-swap'
        else:
            # Whole-line depth changes can escape a single-cell local optimum.
            y=rng.choice(self.profile['ys']);other=rng.choice(self.profile['ys'])
            for p in plan:
                if p['y'] in (y,other):p['y']=other if p['y']==y else y
            name='row-swap'
        return plan,name

    def explain(self,plan):
        notes=[]
        for x in self.profile['xs']:
            line=sorted((p for p in plan if p['x']==x),key=lambda p:-p['y'])
            if not line:notes.append(f'第 {x} 路为空；需核对跨路支援和漏怪风险');continue
            leader=line[0];uid=leader['unit_id']
            notes.append(f'第 {x} 路最前：{self.sim.catalog.name(uid,self.evo(uid))}；对位克制偏好 {self.counter(uid,x):+.2f}')
        for p in plan:
            if p['unit_id']==46 and self.evo(46)>=3:
                names=[self.sim.catalog.name(q['unit_id'],self.evo(q['unit_id'])) for q in plan if q['y']==p['y'] and q is not p]
                notes.append('水舞蝶同排联动：'+('、'.join(names) or '无伙伴，光环利用不足'))
            if p['unit_id'] in (27,40):
                area=set(map(tuple,self.facts.get(p['unit_id'],{}).get('aoe_grids',[])))
                linked=sum(q is not p and (q['x']-p['x'],q['y']-p['y']) in area for q in plan)
                notes.append(f'{self.sim.catalog.name(p["unit_id"],self.evo(p["unit_id"]))} 开局光环覆盖 {linked} 名伙伴')
        return notes
