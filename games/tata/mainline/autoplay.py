"""Standalone, bounded mainline loop: sync, simulate, deploy, verify, fight, advance."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import time
import uuid

from model import Catalog,RUNTIME,read_json,write_json

STOP=RUNTIME/'AUTOPLAY-STOP'
GEOMETRY=RUNTIME/'autoplay-geometry.json'


class WaitTimeout(RuntimeError):pass


class RunStopped(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def canonical(rows):
    return sorted((p['unit_id'],p.get('x',p.get('_gridX')),p.get('y',p.get('_gridY'))) for p in rows)


def placements(state):
    return [dict(unit_id=p['unit_id'],x=p['_gridX'],y=p['_gridY']) for p in state.get('selected',[])]


def verified(report):
    if report.get('status') in ('cancelled','no_solution','error'):return False
    finalists=report.get('finalists',[])
    validation=finalists[0].get('validation',[]) if finalists else []
    return (report.get('evaluation',{}).get('won') is True and len(validation)>=3
        and finalists[0].get('validation_complete',True) and all(v.get('won') is True for v in validation))


def card_point(index,g,total=None,tail=False):
    if tail:
        if total is None or not 0<=index<total or 'cardRight' not in g:raise ValueError('缺少末页卡片校准')
        x=g['cardRight']+((index//2)-(total-1)//2)*g['cardStep']
        if not g['card'][0]<=x<=g['cardRight']:raise ValueError('目标卡片不在末页')
        return x,g['card'][1]+index%2*g['cardRowStep']
    if not 0<=index<12:raise ValueError('目标卡片超出已核验的可见范围')
    return g['card'][0]+index//2*g['cardStep'],g['card'][1]+index%2*g['cardRowStep']


def grid_point(x,y,g):return g['grid'][0]+(x-1)*g['gridStep'],g['grid'][1]-(y-1)*g['gridStep']


def next_stage_id(catalog,stage):
    stages=sorted(row['id'] for row in catalog.stages)
    if stage not in stages:raise ValueError('当前关卡不在主线配置中')
    index=stages.index(stage)+1
    if index>=len(stages):raise ValueError('已到达本机主线配置末尾')
    return stages[index]


def is_preparing(state,stage=None):
    stage=state.get('current_stage_id') if stage is None else stage
    return (state.get('controller',{}).get('battleMode')==1
        and state.get('controller',{}).get('stageID')==stage
        and state.get('battle',{}).get('battleID')==stage
        and state.get('battle',{}).get('state')==1
        and state.get('prepare',{}).get('stageID')==stage
        and 'selected' in state and 'pet_list' in state)


class Runner:
    def __init__(self,geometry,budget=40,max_stages=5,run_dir=None,stop_path=STOP,max_search_seconds=600,stop_when_verified=True):
        from desktop_input import GameInput
        from live_battle import LiveBattle
        self.g=geometry;self.budget=budget;self.max_stages=max_stages;self.stop_path=Path(stop_path)
        self.max_search_seconds=max_search_seconds;self.stop_when_verified=stop_when_verified
        self.folder=Path(run_dir or RUNTIME/'autoplay-runs'/uuid.uuid4().hex);self.folder.mkdir(parents=True,exist_ok=True)
        self.catalog=Catalog();self.input=GameInput(geometry['width'],geometry['height'])
        if geometry.get('physical_size') and tuple(geometry['physical_size'])!=self.input.initial_dimensions:
            raise RuntimeError('窗口尺寸与已验证配置不同，请重新校准后运行')
        self.live=LiveBattle();self.input.focus();self.completed=[];self.events=[]

    def event(self,kind,**data):
        row=dict(time=datetime.now(timezone.utc).isoformat(),event=kind,**data)
        value=dict(**row,run_dir=str(self.folder),completed=self.completed)
        write_json(self.folder/'status.json',value);write_json(RUNTIME/'autoplay-status.json',value)
        if kind=='searching' and data.get('search',{}).get('status')=='searching':
            now=time.monotonic()
            if now-getattr(self,'_search_log_time',float('-inf'))<10:return
            self._search_log_time=now
        self.events.append(row);self.events=self.events[-256:]
        write_json(self.folder/'events.json',self.events)
        with (self.folder/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)

    def check_stop(self):
        if self.stop_path.exists():raise RuntimeError('用户停止自动推关')
        self.input.stop_check()

    def compute_stopped(self):
        # Simulation does not use the mouse; a long offline search can run while
        # the user works elsewhere. Foreground is checked again before input.
        return self.stop_path.exists() or self.input.window.emergency_stop()

    def snapshot(self):
        self.check_stop()
        from live_roster import LiveReadError
        try:return self.live.snapshot()
        except LiveReadError:
            self.live.close()
            from live_battle import LiveBattle
            self.live=LiveBattle();return self.live.snapshot()

    def relocate(self):
        self.check_stop();self.live.close()
        from live_battle import LiveBattle
        self.live=LiveBattle()

    def wait(self,predicate,timeout=15):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.snapshot()
            if predicate(state):return state
            time.sleep(.25)
        raise WaitTimeout('游戏状态等待超时，停止输入')

    def preparing(self,stage):
        state=self.snapshot()
        if not is_preparing(state,stage):
            raise RuntimeError('关卡或布阵阶段改变，停止输入')
        return state

    def action(self,stage,kind,**args):
        self.preparing(stage);getattr(self.input,kind)(**args);time.sleep(.12)
        return self.preparing(stage)

    def deploy(self,report):
        if not verified(report):raise ValueError('方案尚未通过全部模拟复核')
        stage=report['stage_id'];target=report['placements'];state=self.preparing(stage)
        if canonical(state['selected'])==canonical(target):return
        self.event('deploy',stage_id=stage,previous=placements(state),target=target)
        gallery_page=None
        if not all(p in canonical(target) for p in canonical(state['selected'])):
            state=self.action(stage,'click',x=self.g['clear'][0],y=self.g['clear'][1])
            if state['selected']:raise RuntimeError('清空阵容未生效')
        for pet in sorted(target,key=lambda p:self.catalog.units[str(p['unit_id'])]['UnitElement']):
            uid=pet['unit_id']
            if (uid,pet['x'],pet['y']) in canonical(state['selected']):continue
            element=self.catalog.units[str(uid)]['UnitElement']
            if not state['pet_list'] or any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):
                x,y=self.g['filters'][str(element)];state=self.action(stage,'click',x=x,y=y)
                gallery_page=None
            if any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):raise RuntimeError('元素筛选未核验')
            index=state['pet_list'].index(uid);tail=index>=12;total=len(state['pet_list'])
            if (total>12 or 'gallerySwipe' in self.g) and gallery_page!=(element,tail):
                if 'gallerySwipe' not in self.g or 'cardRight' not in self.g:raise ValueError('此阵容需要卡片横向滚动，请先校准列表末页')
                fx,fy,tx,ty=self.g['gallerySwipe']
                if not tail:fx,fy,tx,ty=tx,ty,fx,fy
                distance=abs(tx-fx)
                offset=max(0,self.g['card'][0]+((total-1)//2)*self.g['cardStep']-self.g['cardRight'])
                for _ in range(max(1,math.ceil(offset/distance))):
                    previous=canonical(state['selected'])
                    state=self.action(stage,'drag',from_x=fx,from_y=fy,to_x=tx,to_y=ty)
                    if canonical(state['selected'])!=previous:raise RuntimeError('滚动误触了上阵操作，停止输入')
                time.sleep(.6);gallery_page=(element,tail)
            x,y=card_point(index,self.g,total,tail);before=len(state['selected'])
            state=self.action(stage,'click',x=x,y=y)
            actual=next((p for p in state['selected'] if p['unit_id']==uid),None)
            if actual is None or len(state['selected'])!=before+1:raise RuntimeError(f'宠物 {uid} 上阵未核验')
            if (actual['_gridX'],actual['_gridY'])!=(pet['x'],pet['y']):
                x,y=grid_point(actual['_gridX'],actual['_gridY'],self.g);tx,ty=grid_point(pet['x'],pet['y'],self.g)
                state=self.action(stage,'drag',from_x=x,from_y=y,to_x=tx,to_y=ty)
            if (uid,pet['x'],pet['y']) not in canonical(state['selected']):raise RuntimeError(f'宠物 {uid} 拖动未核验')
        if canonical(state['selected'])!=canonical(target):raise RuntimeError('整队布阵不一致，禁止开战')
        self.event('deployment_verified',stage_id=stage)

    def plan(self,state):
        from live_roster import read_live,to_roster
        from combat import Simulator
        from experience import Experience,context_for,stable_hash
        from search_policy import search
        from tactics import Tactics
        capture=read_live();to_roster(capture,self.catalog)
        stage_id=state['current_stage_id'];stage=self.catalog.stage(stage_id)
        write_json(self.folder/f'capture-{stage_id}.json',capture)
        self.event('planning',stage_id=stage_id,level=capture['shared_level'])
        sim=Simulator(capture,self.catalog);self.sim=sim
        current=state.get('request_order') or placements(state);memory=Experience()
        try:
            outcomes=[]
            if current:
                for seed in (123456,701,2029,8191):
                    if self.compute_stopped():raise RunStopped('user_stop','用户停止搜索，尚未进行布阵')
                    outcomes.append(sim.evaluate(stage,current,seed))
            if outcomes and all(o['won'] for o in outcomes) and self.stop_when_verified:
                t=Tactics(sim,stage);ctx=context_for(sim,stage,t);features=t.features(current)
                for outcome in outcomes:memory.record(sim.engine_fingerprint,ctx,current,features,outcome)
                report=dict(stage_id=stage_id,stage_name=stage['stage']['DisplayName'],placements=current,
                    evaluation=outcomes[0],finalists=[dict(validation=outcomes[1:])],context=ctx,context_hash=stable_hash(ctx),
                    engine_fingerprint=sim.engine_fingerprint,simulated=True,calibrated=False,mode='validated-current-formation')
            else:
                def status(value):self.event('searching',stage_id=stage_id,search=value)
                report=search(sim,stage,budget=self.budget,experience=memory,initial_plan=current or None,status=status,
                    max_seconds=self.max_search_seconds,stop_path=self.stop_path,check_stop=self.compute_stopped,
                    stop_when_verified=self.stop_when_verified,robust_orders=True,checkpoint=self.folder/f'search-{stage_id}.checkpoint.json')
        finally:memory.close()
        write_json(self.folder/f'plan-{stage_id}.json',report)
        if not verified(report):
            from job_status import search_summary
            code='user_stop' if report.get('status')=='cancelled' else 'search_not_found'
            raise RunStopped(code,search_summary(report)+'；已保存最佳候选，尚未进行布阵')
        return report

    def verify_request_order(self,stage,state,report):
        order=state.get('request_order')
        if not order or canonical(order)!=canonical(report['placements']):raise RuntimeError('无法核验原游戏的战斗入场顺序')
        outcomes=[]
        for seed in (123456,701,2029,8191):
            self.check_stop();outcomes.append(self.sim.evaluate(self.catalog.stage(stage),order,seed))
        write_json(self.folder/f'preflight-{stage}.json',dict(placements=order,evaluations=outcomes))
        from experience import Experience
        from tactics import Tactics
        memory=Experience()
        try:
            features=Tactics(self.sim,self.catalog.stage(stage)).features(order)
            for outcome in outcomes:memory.record(report['engine_fingerprint'],report['context'],order,features,outcome)
        finally:memory.close()
        if not all(o['won'] for o in outcomes):raise RunStopped('request_order_failed',f'按原游戏实际入场顺序复核未通过（{sum(o["won"] for o in outcomes)}/4）；已保存结果、保留布阵，未点击开战')
        report['placements']=order;report['actual_order_validation']=outcomes
        write_json(self.folder/f'plan-{stage}.json',report)
        self.event('request_order_verified',stage_id=stage)

    def verify_roster(self):
        from live_roster import read_live
        from experience import stable_hash
        current=read_live();before=self.sim.capture
        def key(capture):return stable_hash(dict(level=capture['shared_level'],pets=sorted(capture['pets'],key=lambda p:p['tid'])))
        if key(current)!=key(before):raise RunStopped('roster_changed','搜索期间角色池或养成已改变；方案和进度已保存，请重新同步后搜索，尚未进行布阵')

    def continue_victory(self,state):
        battle=state.get('battle',{});finished=battle.get('battleID');next_stage=state.get('current_stage_id')
        if battle.get('state')!=4 or battle.get('result')!=1 or next_stage!=next_stage_id(self.catalog,finished):
            raise RuntimeError('不是已确认通关的主线结算，停止输入')
        # The server advances StageModel before the result view opens. Locate
        # the newly created view and require actual preparation after clicking.
        time.sleep(2);self.relocate()
        try:self.wait(lambda s:s.get('victory',{}).get('isShow') is True,3)
        except WaitTimeout:
            # The view may have been allocated after the heap scan started.
            self.relocate()
            self.wait(lambda s:s.get('victory',{}).get('isShow') is True,6)
        time.sleep(2);self.check_stop()
        x,y=self.g['continue'];self.input.click(x,y)
        time.sleep(2);self.relocate()
        advanced=self.wait(lambda s:is_preparing(s,next_stage),20)
        self.event('preparation_ready',stage_id=next_stage)
        return advanced

    def run(self):
        from experience import Experience
        state=self.snapshot()
        if state.get('battle',{}).get('state')==4:self.continue_victory(state)
        for _ in range(self.max_stages):
            state=self.wait(is_preparing)
            stage=state['current_stage_id'];report=self.plan(state);self.verify_roster();self.deploy(report)
            state=self.preparing(stage)
            if canonical(state['selected'])!=canonical(report['placements']):raise RuntimeError('开战前整队核验失败')
            self.verify_request_order(stage,state,report)
            x,y=self.g['start'];self.input.click(x,y)
            self.wait(lambda s:s.get('battle',{}).get('battleID')==stage and s.get('battle',{}).get('state') in (2,4),10)
            self.event('battle_started',stage_id=stage)
            result=self.wait(lambda s:s.get('battle',{}).get('battleID')==stage and s.get('battle',{}).get('state')==4,170)
            write_json(self.folder/f'live-result-{stage}.json',result)
            won=result['battle'].get('result')==1
            self.event('battle_settled',stage_id=stage,won=won,battle_secs=result['battle'].get('elapsed_time'))
            memory=Experience()
            try:memory.record_feedback(report['engine_fingerprint'],report['context_hash'],report['placements'],won,
                note=f'原进程只读结算，证据 {self.folder.name}/live-result-{stage}.json',source='live_observation')
            finally:memory.close()
            if not won:raise RunStopped('battle_lost','实战未通过，已记录与模拟的差异，停止连续挑战')
            expected_next=next_stage_id(self.catalog,stage)
            self.wait(lambda s:s.get('current_stage_id')==expected_next,15)
            advanced=self.continue_victory(self.snapshot())
            self.completed.append(stage);self.event('stage_advanced',stage_id=stage,next_stage=advanced['current_stage_id'])
        self.event('finished',reason='达到本次关卡数量上限')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--geometry',type=Path,default=GEOMETRY)
    p.add_argument('--stages',type=int,default=5);p.add_argument('--budget',type=int,default=40)
    p.add_argument('--seconds',type=float,default=600,help='每关搜索秒数上限，0不限')
    p.add_argument('--optimize-until-limit',action='store_true',help='找到通过方案后仍继续优化到上限')
    p.add_argument('--run-dir',type=Path);a=p.parse_args()
    if not 1<=a.stages<=100 or a.budget<0 or not math.isfinite(a.seconds) or a.seconds<0:p.error('关卡数1–100；候选/时长上限非负，0不限')
    import msvcrt
    RUNTIME.mkdir(parents=True,exist_ok=True)
    folder=a.run_dir or RUNTIME/'autoplay-runs'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
    def startup_event(event,**data):
        value=dict(time=datetime.now(timezone.utc).isoformat(),event=event,run_dir=str(folder),completed=[],**data)
        write_json(folder/'status.json',value);write_json(RUNTIME/'autoplay-status.json',value)
    startup_event('initializing')
    lock=None;locked=False;runner=None
    try:
        lock=(RUNTIME/'autoplay.lock').open('a+b')
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('已有自动推关进程控制该游戏')
        locked=True
        runner=Runner(read_json(a.geometry),a.budget,a.stages,run_dir=folder,
            max_search_seconds=a.seconds,stop_when_verified=not a.optimize_until_limit);runner.run()
    except Exception as exc:
        from job_status import error_code
        data=dict(reason=str(exc),reason_code=getattr(exc,'code',None) or error_code(exc))
        if runner:runner.event('stopped',**data)
        else:startup_event('stopped',**data)
        raise
    finally:
        if runner:runner.live.close()
        if locked:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        if lock:lock.close()


if __name__=='__main__':main()
