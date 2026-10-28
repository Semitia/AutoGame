"""Local battle evidence, case retrieval and bounded online pairwise preference learning."""
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from model import RUNTIME
from tactics import BASE_WEIGHTS,FEATURE_VERSION


DEFAULT_PATH=RUNTIME/'experience.sqlite3'


def stable_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def plan_key(plan):return stable_hash(sorted((p['unit_id'],p['x'],p['y']) for p in plan))


def context_for(sim,stage,tactics):
    roster=[{k:v for k,v in row.items() if k!='captured_at'} for _,row in sorted(sim.rows.items())]
    return dict(stage_id=stage['stage']['ID'],stage_name=stage['stage']['DisplayName'],
        stage_hash=stable_hash(dict(waves=stage['waves'],battle=stage.get('battle'),mode=stage.get('battle_mode'),enemies=stage['enemy_units'])),
        roster_hash=stable_hash(roster),owned=sorted(sim.rows),profile=tactics.profile)


def preference(a,b):
    """Controlled same-context, same-seed pairs only; ignore small timing noise."""
    if a['won']!=b['won']:return (1 if a['won'] else -1),1.
    delta=a['kills']-b['kills']
    if delta:return (1 if delta>0 else -1),min(1.,abs(delta)/max(1,a['total_enemies'])*4)
    delta=b['battle_secs']-a['battle_secs']
    if a['won'] and abs(delta)>=2:return (1 if delta>0 else -1),min(.3,abs(delta)/100)
    return 0,0.


class Experience:
    def __init__(self,path=DEFAULT_PATH):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS battles (
                id INTEGER PRIMARY KEY, engine TEXT NOT NULL, context_hash TEXT NOT NULL,
                context TEXT NOT NULL, plan_hash TEXT NOT NULL, plan TEXT NOT NULL,
                seed INTEGER NOT NULL, features TEXT NOT NULL, outcome TEXT NOT NULL,
                score REAL NOT NULL, won INTEGER NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(engine,context_hash,plan_hash,seed));
            CREATE INDEX IF NOT EXISTS battle_engine ON battles(engine,won,score);
            CREATE TABLE IF NOT EXISTS preferences (
                engine TEXT, feature_version TEXT, a INTEGER, b INTEGER,
                PRIMARY KEY(engine,feature_version,a,b));
            CREATE TABLE IF NOT EXISTS learners (
                engine TEXT, feature_version TEXT, correction TEXT, updates INTEGER,
                PRIMARY KEY(engine,feature_version));
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY, engine TEXT, context_hash TEXT, plan_hash TEXT,
                won INTEGER, source TEXT, note TEXT, created_at TEXT);
        ''')
        self.db.commit()

    def close(self):self.db.close()

    def weights(self,engine):
        row=self.db.execute('SELECT correction,updates FROM learners WHERE engine=? AND feature_version=?',
                            (engine,FEATURE_VERSION)).fetchone()
        corrections=json.loads(row[0]) if row else {}
        return {k:v+corrections.get(k,0) for k,v in BASE_WEIGHTS.items()},row[1] if row else 0

    def record(self,engine,context,plan,features,outcome):
        payload={k:v for k,v in outcome.items() if k not in ('frames','compute_secs')}
        args=(engine,stable_hash(context),json.dumps(context),plan_key(plan),json.dumps(plan),outcome['seed'],
              json.dumps(features),json.dumps(payload),outcome['score'],int(outcome['won']),datetime.now(timezone.utc).isoformat())
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO battles(engine,context_hash,context,plan_hash,plan,seed,features,outcome,score,won,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',args)
        return self.db.execute('SELECT id FROM battles WHERE engine=? AND context_hash=? AND plan_hash=? AND seed=?',
                               (args[0],args[1],args[3],args[5])).fetchone()[0]

    def learn(self,engine,a,b):
        if a==b:return False
        ids=sorted((a,b))
        rows=self.db.execute('SELECT id,engine,context_hash,seed,features,outcome FROM battles WHERE id IN (?,?)',ids).fetchall()
        if len(rows)!=2 or any(r[1]!=engine for r in rows) or rows[0][2:4]!=rows[1][2:4]:
            raise ValueError('学习比较必须来自相同版本、角色池、关卡与随机种子')
        fa,fb=[json.loads(r[4]) for r in rows];oa,ob=[json.loads(r[5]) for r in rows]
        sign,confidence=preference(oa,ob)
        delta={k:sign*(fa.get(k,0)-fb.get(k,0)) for k in BASE_WEIGHTS}
        norm=math.sqrt(sum(v*v for v in delta.values()))
        if not sign or norm<1e-8:return False
        # Each real comparison is consumed once, even after the app restarts.
        with self.db:
            cursor=self.db.execute('INSERT OR IGNORE INTO preferences VALUES (?,?,?,?)',(engine,FEATURE_VERSION,*ids))
            if not cursor.rowcount:return False
            weights,updates=self.weights(engine)
            margin=sum(weights[k]*delta[k] for k in delta)
            step=.3*confidence/(1+math.exp(max(-20,min(20,margin))))
            corrections={k:max(-3.,min(3.,.999*(weights[k]-BASE_WEIGHTS[k])+step*delta[k]/max(1.,norm))) for k in delta}
            self.db.execute('INSERT OR REPLACE INTO learners VALUES (?,?,?,?)',
                            (engine,FEATURE_VERSION,json.dumps(corrections),updates+1))
        return True

    def retrieve(self,engine,context,limit=4):
        rows=self.db.execute('SELECT id,context,plan,outcome,plan_hash,context_hash FROM battles WHERE engine=? ORDER BY won DESC,score DESC LIMIT 600',(engine,)).fetchall()
        feedback={}
        for ch,ph,won in self.db.execute('SELECT context_hash,plan_hash,won FROM feedback WHERE engine=? ORDER BY id',(engine,)):
            feedback[(ch,ph)]=bool(won)
        candidates=[];seen=set()
        for identifier,raw,plan,outcome,ph,ch in rows:
            past=json.loads(raw);outcome=json.loads(outcome);profile=past['profile'];current=context['profile']
            a={int(k):v for k,v in profile['enemies'].items()};b={int(k):v for k,v in current['enemies'].items()}
            na=sum(a.values()) or 1;nb=sum(b.values()) or 1
            distance=sum(abs(a.get(k,0)/na-b.get(k,0)/nb) for k in a.keys()|b.keys())/2
            overlap=len(set(past['owned'])&set(context['owned']))/max(1,len(set(past['owned'])|set(context['owned'])))
            similarity=max(0,1-distance)*overlap
            if similarity<.25:continue
            exact=past['stage_hash']==context['stage_hash']
            geometry=profile['xs']==current['xs'] and profile['ys']==current['ys']
            user_result=feedback.get((ch,ph)) if past['roster_hash']==context['roster_hash'] else None
            priority=2*exact+.5*geometry+similarity+.3*outcome['won']+(.15 if user_result is True else -.5 if user_result is False else 0)
            candidates.append((priority,identifier,ph,dict(placements=json.loads(plan),stage_id=past['stage_id'],
                similarity=round(similarity,3),same_roster=past['roster_hash']==context['roster_hash'],
                exact_stage=exact,source='simulation',user_report=user_result,evidence_id=identifier)))
        selected=[]
        for _,_,ph,candidate in sorted(candidates,key=lambda x:(x[0],x[1]),reverse=True):
            if ph in seen:continue
            seen.add(ph);selected.append(candidate)
            if len(selected)>=limit:break
        return selected

    def record_feedback(self,engine,context_hash,placements,won,note=''):
        if type(won) is not bool:raise ValueError('实战结果必须为通过/未通过')
        with self.db:
            self.db.execute('INSERT INTO feedback(engine,context_hash,plan_hash,won,source,note,created_at) VALUES (?,?,?,?,?,?,?)',
                (engine,context_hash,plan_key(placements),int(won),'user_report',str(note)[:2000],datetime.now(timezone.utc).isoformat()))

    def stats(self,engine):
        n,w=self.db.execute('SELECT COUNT(*),COALESCE(SUM(won),0) FROM battles WHERE engine=?',(engine,)).fetchone()
        return dict(battles=n,simulated_victories=w,preference_updates=self.weights(engine)[1],
            user_reports=self.db.execute('SELECT COUNT(*) FROM feedback WHERE engine=?',(engine,)).fetchone()[0])
