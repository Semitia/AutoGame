"""Standalone, bounded mainline loop: sync, simulate, deploy, verify, fight, advance."""
import argparse
from contextlib import ExitStack
from datetime import datetime,timezone
import json
import os
import math
import sys
from pathlib import Path
import time
import uuid

from model import Catalog,RUNTIME,read_json,write_json
from review import MODES,review_seeds,preflight_seeds,passed

STOP=RUNTIME/'AUTOPLAY-STOP'
GEOMETRY=RUNTIME/'autoplay-geometry.json'
POLL_SECONDS=.03


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
    if not finalists:return False
    mode=report.get('review_mode','full')
    if mode not in MODES:return False
    best=dict(finalists[0],evaluation=report.get('evaluation',{}))
    # Reports predating configurable review always required three rechecks.
    best.setdefault('validation_expected',len(review_seeds(mode)))
    best.setdefault('validation_complete','review_mode' not in report)
    return passed(best)


def card_point(index,g,total=None,tail=False):
    if tail:
        if total is None or not 0<=index<total or 'cardRight' not in g:raise ValueError('缺少末页卡片校准')
        x=g['cardRight']+((index//2)-(total-1)//2)*g['cardStep']
        if not g['card'][0]<=x<=g['cardRight']:raise ValueError('目标卡片不在末页')
        return x,g['card'][1]+index%2*g['cardRowStep']
    if not 0<=index<g.get('visible_cards',12):raise ValueError('目标卡片超出已核验的可见范围')
    return g['card'][0]+index//2*g['cardStep'],g['card'][1]+index%2*g['cardRowStep']


def grid_point(x,y,g):return g['grid'][0]+(x-1)*g.get('gridStepX',g['gridStep']),g['grid'][1]-(y-1)*g.get('gridStepY',g['gridStep'])


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


def is_chapter(state,stage=None):
    current=state.get('current_stage_id')
    return (type(current) is int and current>0 and (stage is None or stage==current)
            and state.get('screen')=='chapter' and state.get('chapter',{}).get('stage_id')==current
            and not state.get('controller'))


class Runner:
    def __init__(self,geometry=None,budget=40,max_stages=5,run_dir=None,stop_path=STOP,max_search_seconds=600,stop_when_verified=True,review_mode='light',account_key=None,hwnd=None,background=False):
        from desktop_input import GameInput
        from live_battle import LiveBattle
        self.automatic=geometry is None or geometry.get('schema_version')==3
        geometry=geometry or dict(width=400,height=750)
        self.g=geometry;self.budget=budget;self.max_stages=max_stages;self.stop_path=Path(stop_path)
        self.account_key=account_key
        self.pids=None
        if hwnd is not None or background:
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
            from windows_runtime import window_pids,background_input
            from desktop_input import find_game_window
            hwnd=find_game_window(hwnd) if hwnd is not None else find_game_window()
            self.pids=window_pids(hwnd)
        if geometry.get('schema_version')==2:
            from calibration import validate_geometry
            validate_geometry(geometry)
            if max_stages>1 and 'continue' not in geometry:raise ValueError('缺少胜利页继续按钮校准，请先只挑战 1 关')
        self.max_search_seconds=max_search_seconds;self.stop_when_verified=stop_when_verified
        review_seeds(review_mode);self.review_mode=review_mode
        self.folder=Path(run_dir or RUNTIME/'autoplay-runs'/uuid.uuid4().hex);self.folder.mkdir(parents=True,exist_ok=True)
        self.catalog=Catalog()
        self.input=background_input(hwnd,geometry['width'],geometry['height'],self.automatic) if background else GameInput(geometry['width'],geometry['height'],adaptive=self.automatic,hwnd=hwnd)
        self.status_root=RUNTIME/'windows'/str(hwnd) if hwnd is not None else RUNTIME
        if not self.automatic and geometry.get('physical_size') and tuple(geometry['physical_size'])!=self.input.initial_dimensions:
            raise RuntimeError('窗口尺寸与已验证配置不同，请重新校准后运行')
        self.live=LiveBattle(account_key=account_key,pids=self.pids)
        if not background:self.input.focus()
        self.completed=[];self.events=[]
        if self.automatic:
            from auto_layout import AutoLayout
            self.layout=AutoLayout(self.catalog);self.layout_signature=None
            if background:self.layout.capture=self.input.capture
            elif hwnd is not None:
                from calibration import capture_visible_game
                self.layout.capture=lambda:capture_visible_game(hwnd=hwnd)
            state=self.live.snapshot()
            if state.get('battle',{}).get('state')==1:self.refresh_layout(state)

    def refresh_layout(self,state):
        if not getattr(self,'automatic',False):return
        signature=(self.input.window.bounds()[2:],state['current_stage_id'],state.get('prepare',{}).get('_currentPrepareListRowCount'))
        if signature==self.layout_signature:return
        image=self.layout.capture();geometry=self.layout.recognize(image,state)
        self.input.set_reference(geometry['width'],geometry['height'])
        self.g=geometry;self.layout_signature=signature
        write_json(self.folder/'geometry.json',geometry)
        self.event('layout_recognized',width=geometry['width'],height=geometry['height'],map_inliers=geometry['map_inliers'])

    def event(self,kind,**data):
        row=dict(time=datetime.now(timezone.utc).isoformat(),event=kind,pid=os.getpid(),
            stop_file=str(self.stop_path.resolve()),**data)
        value=dict(**row,run_dir=str(self.folder),completed=self.completed)
        write_json(self.folder/'status.json',value);write_json(getattr(self,'status_root',RUNTIME)/'autoplay-status.json',value)
        write_json(getattr(self,'status_root',RUNTIME)/'status.json',value)
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
            self.relocate();return self.live.snapshot()

    def relocate(self):
        self.check_stop()
        from live_roster import LiveReadError
        try:
            self.live.refresh()
            return
        except (LiveReadError,OSError):self.live.close()
        from live_battle import LiveBattle
        self.live=LiveBattle(account_key=getattr(self,'account_key',None),pids=getattr(self,'pids',None))

    def wait(self,predicate,timeout=15,*,rediscover=False):
        from live_roster import LiveReadError
        end=time.monotonic()+timeout;next_scan=time.monotonic()+.15;last_error=None
        while time.monotonic()<end:
            state=None
            try:
                state=self.snapshot()
                if predicate(state):return state
            except LiveReadError as exc:
                if not rediscover:raise
                last_error=exc
            if rediscover and time.monotonic()>=next_scan and (not callable(rediscover) or rediscover(state or {})):
                self.relocate();next_scan=time.monotonic()+.5
            time.sleep(min(POLL_SECONDS,max(0,end-time.monotonic())))
        raise WaitTimeout('游戏状态等待超时，停止输入'+('：'+str(last_error) if last_error else ''))

    def preparing(self,stage):
        state=self.snapshot()
        if not is_preparing(state,stage):
            raise RuntimeError('关卡或布阵阶段改变，停止输入')
        self.refresh_layout(state)
        return state

    def action(self,stage,kind,resolve=None,expect=None,timeout=1.2,**args):
        self.preparing(stage)
        if resolve:args=resolve(self.g)
        getattr(self.input,kind)(**args)
        def applied(state):
            if not is_preparing(state,stage):raise RuntimeError('关卡或布阵阶段改变，停止输入')
            self.refresh_layout(state)
            return expect(state) if expect else True
        return self.wait(applied,timeout)

    def preparation_ready(self,state,stage):
        if not is_preparing(state,stage):return False
        from auto_layout import LayoutError
        try:self.refresh_layout(state)
        except LayoutError:return False
        return True

    def enter_chapter(self,state,stage=None):
        stage=state.get('current_stage_id') if stage is None else stage
        if not is_chapter(state,stage):raise RunStopped('game_state_error','当前不是已确认的章节地图，未执行输入')
        if not getattr(self,'automatic',False):
            raise RunStopped('game_state_error','旧手工配置模式需要先打开布阵页；默认自动模式可从章节地图进入')
        def ready(s):
            return is_chapter(s,stage) and not any(s['chapter'].get(k) is True for k in (
                'isCarMoving','isStartingBattle','isOpeningWorldMapDye','tweenCameraToChapterBossing'))
        self.wait(ready,15)
        from auto_layout import chapter_start_button,center
        import cv2,numpy as np
        image=self.layout.capture()
        point=center(chapter_start_button(cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)))
        if not ready(self.snapshot()):raise RunStopped('game_state_error','章节地图正在切换，保留现场，未点击')
        self.input.set_reference(*image.size);self.input.click(*point)
        self.event('entering_preparation',stage_id=stage)
        result=self.wait(lambda s:self.preparation_ready(s,stage),25,
            rediscover=lambda s:not is_preparing(s,stage))
        self.event('preparation_ready',stage_id=stage)
        return result

    def deploy(self,report):
        if getattr(self,'automatic',False):return self.deploy_automatic(report)
        if not verified(report):raise ValueError('方案尚未通过全部模拟复核')
        stage=report['stage_id'];target=report['placements'];state=self.preparing(stage)
        if canonical(state['selected'])==canonical(target):return
        self.event('deploy',stage_id=stage,previous=placements(state),target=target)
        gallery_page=None
        if not all(p in canonical(target) for p in canonical(state['selected'])):
            state=self.action(stage,'click',x=self.g['clear'][0],y=self.g['clear'][1],expect=lambda s:not s['selected'])
            if state['selected']:raise RuntimeError('清空阵容未生效')
        for pet in sorted(target,key=lambda p:self.catalog.units[str(p['unit_id'])]['UnitElement']):
            uid=pet['unit_id']
            if (uid,pet['x'],pet['y']) in canonical(state['selected']):continue
            element=self.catalog.units[str(uid)]['UnitElement']
            if not state['pet_list'] or any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):
                x,y=self.g['filters'][str(element)];state=self.action(stage,'click',x=x,y=y,
                    expect=lambda s:bool(s['pet_list']) and all(self.catalog.units[str(i)]['UnitElement']==element for i in s['pet_list']))
                gallery_page=None
            if any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):raise RuntimeError('元素筛选未核验')
            visible=self.g.get('visible_cards',12)
            index=state['pet_list'].index(uid);tail=index>=visible;total=len(state['pet_list'])
            if (total>visible or 'gallerySwipe' in self.g) and gallery_page!=(element,tail):
                if 'gallerySwipe' not in self.g or 'cardRight' not in self.g:raise ValueError('此阵容需要卡片横向滚动，请先校准列表末页')
                fx,fy,tx,ty=self.g['gallerySwipe']
                if not tail:fx,fy,tx,ty=tx,ty,fx,fy
                distance=abs(tx-fx)
                offset=max(0,self.g['card'][0]+((total-1)//2)*self.g['cardStep']-self.g['cardRight'])
                for _ in range(max(1,math.ceil(offset/distance))):
                    previous=canonical(state['selected'])
                    state=self.action(stage,'drag',from_x=fx,from_y=fy,to_x=tx,to_y=ty)
                    if canonical(state['selected'])!=previous:raise RuntimeError('滚动误触了上阵操作，停止输入')
                gallery_page=(element,tail)
            x,y=card_point(index,self.g,total,tail);before=len(state['selected'])
            state=self.action(stage,'click',x=x,y=y,expect=lambda s:any(p['unit_id']==uid for p in s['selected']))
            actual=next((p for p in state['selected'] if p['unit_id']==uid),None)
            if actual is None or len(state['selected'])!=before+1:raise RuntimeError(f'宠物 {uid} 上阵未核验')
            if (actual['_gridX'],actual['_gridY'])!=(pet['x'],pet['y']):
                x,y=grid_point(actual['_gridX'],actual['_gridY'],self.g);tx,ty=grid_point(pet['x'],pet['y'],self.g)
                state=self.action(stage,'drag',from_x=x,from_y=y,to_x=tx,to_y=ty,
                    expect=lambda s:(uid,pet['x'],pet['y']) in canonical(s['selected']))
            if (uid,pet['x'],pet['y']) not in canonical(state['selected']):raise RuntimeError(f'宠物 {uid} 拖动未核验')
        if canonical(state['selected'])!=canonical(target):raise RuntimeError('整队布阵不一致，禁止开战')
        self.event('deployment_verified',stage_id=stage)

    def deploy_automatic(self,report):
        stage=report['stage_id'];target=report['placements'];state=self.preparing(stage)
        if canonical(state['selected'])==canonical(target):return
        deployed_started=time.perf_counter()
        self.event('deploy',stage_id=stage,previous=placements(state),target=target)
        def click(point):return dict(x=point[0],y=point[1])
        if not all(p in canonical(target) for p in canonical(state['selected'])):
            state=self.action(stage,'click',resolve=lambda g:click(g['clear']),expect=lambda s:not s['selected'])
            if state['selected']:raise RuntimeError('清空阵容未生效')
        pets={p['tid']:p for p in self.sim.capture['pets']}
        for pet in sorted(target,key=lambda p:self.catalog.units[str(p['unit_id'])]['UnitElement']):
            unit_started=time.perf_counter()
            uid=pet['unit_id'];state=self.preparing(stage)
            if (uid,pet['x'],pet['y']) in canonical(state['selected']):continue
            element=self.catalog.units[str(uid)]['UnitElement']
            if not state['pet_list'] or any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):
                state=self.action(stage,'click',resolve=lambda g:click(g['filters'][str(element)]),
                    expect=lambda s:bool(s['pet_list']) and all(self.catalog.units[str(i)]['UnitElement']==element for i in s['pet_list']))
            if any(self.catalog.units[str(i)]['UnitElement']!=element for i in state['pet_list']):raise RuntimeError('元素筛选未核验')
            before=len(state['selected'])
            for attempt in range(max(6,len(state['pet_list'])//2+2)):
                from auto_layout import LayoutError
                settle_end=time.monotonic()+1.2
                while True:
                    state=self.preparing(stage);image=self.layout.capture()
                    try:
                        decision=self.layout.locate_card(image,state,uid,pets,geometry=self.g)
                        break
                    except LayoutError:
                        if time.monotonic()>=settle_end:
                            image.save(self.folder/'layout-failure.png')
                            write_json(self.folder/'layout-failure.json',dict(stage_id=stage,unit_id=uid,selected=state['selected'],geometry=self.g))
                            raise
                        time.sleep(POLL_SECONDS)
                from desktop_input import LayoutChanged
                try:
                    if 'point' in decision:
                        state=self.action(stage,'click',**click(decision['point']),
                            expect=lambda s:any(p['unit_id']==uid for p in s['selected']));break
                    previous=canonical(state['selected']);fx,fy,tx,ty=decision['swipe']
                    state=self.action(stage,'drag',from_x=fx,from_y=fy,to_x=tx,to_y=ty)
                    if canonical(state['selected'])!=previous:raise RuntimeError('滚动误触了上阵操作，停止输入')
                except LayoutChanged as exc:
                    if exc.gesture:raise
                    self.layout_signature=None
            else:raise RuntimeError('目标卡片未能完整识别，停止输入；未按估计坐标点击')
            actual=next((p for p in state['selected'] if p['unit_id']==uid),None)
            if actual is None or len(state['selected'])!=before+1:raise RuntimeError(f'宠物 {uid} 上阵未核验')
            if (actual['_gridX'],actual['_gridY'])!=(pet['x'],pet['y']):
                def move(g):
                    x,y=grid_point(actual['_gridX'],actual['_gridY'],g);tx,ty=grid_point(pet['x'],pet['y'],g)
                    return dict(from_x=x,from_y=y,to_x=tx,to_y=ty)
                state=self.action(stage,'drag',resolve=move,
                    expect=lambda s:(uid,pet['x'],pet['y']) in canonical(s['selected']))
            if (uid,pet['x'],pet['y']) not in canonical(state['selected']):raise RuntimeError(f'宠物 {uid} 拖动未核验')
            self.event('unit_deployed',stage_id=stage,unit_id=uid,selected=len(state['selected']),target=len(target),
                elapsed_ms=round((time.perf_counter()-unit_started)*1000,1))
        if canonical(state['selected'])!=canonical(target):raise RuntimeError('整队布阵不一致，禁止开战')
        self.event('deployment_verified',stage_id=stage,elapsed_ms=round((time.perf_counter()-deployed_started)*1000,1))

    def plan(self,state):
        from live_roster import read_live,to_roster
        from combat import Simulator
        from experience import Experience,context_for,stable_hash
        from search_policy import search
        from tactics import Tactics
        started=time.perf_counter()
        capture=self.read_account_capture() if getattr(self,'live',None) or getattr(self,'account_key',None) else read_live();to_roster(capture,self.catalog)
        stage_id=state['current_stage_id'];stage=self.catalog.stage(stage_id)
        write_json(self.folder/f'capture-{stage_id}.json',capture)
        self.event('planning',stage_id=stage_id,level=capture['shared_level'],roster_ms=round((time.perf_counter()-started)*1000,1))
        roster_key=stable_hash(dict(level=capture['shared_level'],pets=sorted(capture['pets'],key=lambda p:p['tid'])))
        if getattr(self,'sim_roster_key',None)!=roster_key:
            self.sim=Simulator(capture,self.catalog);self.sim_roster_key=roster_key
        sim=self.sim
        current=state.get('request_order') or placements(state);memory=Experience()
        try:
            outcomes=[]
            if current:
                for seed in (123456,)+review_seeds(self.review_mode):
                    if self.compute_stopped():raise RunStopped('user_stop','用户停止搜索，尚未进行布阵')
                    outcomes.append(sim.evaluate(stage,current,seed))
                    if not outcomes[-1]['won']:break
            if outcomes and all(o['won'] for o in outcomes) and self.stop_when_verified:
                t=Tactics(sim,stage);ctx=context_for(sim,stage,t);features=t.features(current)
                for outcome in outcomes:memory.record(sim.engine_fingerprint,ctx,current,features,outcome)
                report=dict(stage_id=stage_id,stage_name=stage['stage']['DisplayName'],placements=current,
                    evaluation=outcomes[0],finalists=[dict(validation=outcomes[1:],validation_complete=True,
                        validation_expected=len(review_seeds(self.review_mode)))],review_mode=self.review_mode,context=ctx,context_hash=stable_hash(ctx),
                    engine_fingerprint=sim.engine_fingerprint,simulated=True,calibrated=False,mode='validated-current-formation')
            else:
                def status(value):self.event('searching',stage_id=stage_id,search=value)
                report=search(sim,stage,budget=self.budget,experience=memory,initial_plan=current or None,status=status,
                    max_seconds=self.max_search_seconds,stop_path=self.stop_path,check_stop=self.compute_stopped,
                    stop_when_verified=self.stop_when_verified,review_mode=self.review_mode,checkpoint=self.folder/f'search-{stage_id}.checkpoint.json')
        finally:memory.close()
        write_json(self.folder/f'plan-{stage_id}.json',report)
        if not verified(report):
            from job_status import search_summary
            code='user_stop' if report.get('status')=='cancelled' else 'search_not_found'
            raise RunStopped(code,search_summary(report)+'；已保存最佳候选，尚未进行布阵')
        # Only evidence produced by this plan call can avoid an identical
        # preflight simulation. Preserve request order: equal cells are not enough.
        self.plan_preflight=(sim,stage_id,
            tuple((p['unit_id'],p['x'],p['y']) for p in report['placements']),dict(report['evaluation']))
        self.event('plan_ready',stage_id=stage_id,elapsed_ms=round((time.perf_counter()-started)*1000,1))
        return report

    def verify_request_order(self,stage,state,report):
        started=time.perf_counter()
        order=state.get('request_order')
        if not order or canonical(order)!=canonical(report['placements']):raise RuntimeError('无法核验原游戏的战斗入场顺序')
        outcomes=[];reused=0
        evidence=getattr(self,'plan_preflight',None)
        same_evidence=(evidence is not None and evidence[0] is self.sim and evidence[1]==stage
            and evidence[2]==tuple((p['unit_id'],p['x'],p['y']) for p in order))
        for seed in preflight_seeds(self.review_mode):
            self.check_stop()
            if same_evidence and evidence[3].get('seed')==seed:
                outcomes.append(dict(evidence[3]));reused+=1
            else:outcomes.append(self.sim.evaluate(self.catalog.stage(stage),order,seed))
        write_json(self.folder/f'preflight-{stage}.json',dict(placements=order,evaluations=outcomes,
            review_mode=self.review_mode,reused_evaluations=reused))
        from experience import Experience
        from tactics import Tactics
        memory=Experience()
        try:
            features=Tactics(self.sim,self.catalog.stage(stage)).features(order)
            for outcome in outcomes:memory.record(report['engine_fingerprint'],report['context'],order,features,outcome)
        finally:memory.close()
        if not all(o['won'] for o in outcomes):raise RunStopped('request_order_failed',f'按原游戏实际入场顺序复核未通过（{sum(o["won"] for o in outcomes)}/{len(outcomes)}）；已保存结果、保留布阵，未点击开战')
        report['placements']=order;report['actual_order_validation']=outcomes
        write_json(self.folder/f'plan-{stage}.json',report)
        self.event('request_order_verified' if outcomes else 'request_order_checked',stage_id=stage,review_mode=self.review_mode,
            elapsed_ms=round((time.perf_counter()-started)*1000,1),reused_evaluations=reused)

    def verify_roster(self):
        from live_roster import read_live
        from experience import stable_hash
        started=time.perf_counter()
        current=self.read_account_capture() if getattr(self,'live',None) or getattr(self,'account_key',None) else read_live();before=self.sim.capture
        def key(capture):return stable_hash(dict(level=capture['shared_level'],pets=sorted(capture['pets'],key=lambda p:p['tid'])))
        if key(current)!=key(before):raise RunStopped('roster_changed','搜索期间角色池或养成已改变；方案和进度已保存，请重新同步后搜索，尚未进行布阵')
        if hasattr(self,'events'):self.event('roster_verified',elapsed_ms=round((time.perf_counter()-started)*1000,1))

    def read_account_capture(self):
        if getattr(self,'live',None):
            from live_roster import LiveReadError
            try:capture=self.live.capture_roster()
            except LiveReadError:
                self.relocate();capture=self.live.capture_roster()
            if self.account_key and capture['account']['key']!=self.account_key:
                raise RunStopped('account_changed','当前游戏账号与工作台所选账号不同，已停止；请重新同步账号后运行')
            self.account_key=capture['account']['key'];self.live.account_key=self.account_key
            return capture
        from live_session import read_sessions
        sessions=read_sessions()
        # Foreground mouse automation still requires one game window. Do not use
        # another logged-in account's stats, even if its pet growth is identical.
        if len(sessions)!=1 or sessions[0]['account']['key']!=self.account_key:
            raise RunStopped('account_changed','当前游戏账号与工作台所选账号不同，已停止；请重新同步账号后运行')
        return sessions[0]

    def continue_victory(self,state):
        if not getattr(self,'automatic',False) and 'continue' not in self.g:raise RunStopped('calibration_required','胜利页继续按钮尚未校准；请自行返回布阵页，或补充窗口校准')
        battle=state.get('battle',{});finished=battle.get('battleID');next_stage=state.get('current_stage_id')
        if battle.get('state')!=4 or battle.get('result')!=1 or next_stage!=next_stage_id(self.catalog,finished):
            raise RuntimeError('不是已确认通关的主线结算，停止输入')
        started=time.perf_counter();point=[]
        def clickable(s):
            b=s.get('battle',{})
            if s.get('current_stage_id')!=next_stage or b.get('battleID')!=finished or b.get('state')!=4 or b.get('result')!=1:
                return False
            if s.get('victory',{}).get('isShow') is not True:return False
            if getattr(self,'automatic',False):
                from auto_layout import continue_button,center,LayoutError
                import cv2,numpy as np
                image=self.layout.capture()
                try:p=center(continue_button(cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)))
                except LayoutError:return False
                self.input.set_reference(*image.size);point[:]=p
            else:point[:]=self.g['continue']
            return True
        # Cached refs usually already contain the victory view. Discover only
        # when a new view/controller appears, not on every scene transition.
        self.wait(clickable,9,rediscover=lambda s:not s.get('victory'))
        self.check_stop();self.input.click(*point)
        advanced=self.wait(lambda s:self.preparation_ready(s,next_stage) or is_chapter(s,next_stage),20,
            rediscover=lambda s:not is_preparing(s,next_stage) and not is_chapter(s,next_stage))
        if is_chapter(advanced,next_stage):advanced=self.enter_chapter(advanced,next_stage)
        self.event('preparation_ready',stage_id=next_stage,transition_ms=round((time.perf_counter()-started)*1000,1))
        return advanced

    def run(self):
        from experience import Experience
        state=self.snapshot()
        if state.get('battle',{}).get('state')==4:self.continue_victory(state)
        for _ in range(self.max_stages):
            state=self.wait(lambda s:is_preparing(s) or is_chapter(s),20)
            if is_chapter(state):state=self.enter_chapter(state)
            stage=state['current_stage_id'];report=self.plan(state);self.verify_roster();self.deploy(report)
            state=self.preparing(stage)
            if canonical(state['selected'])!=canonical(report['placements']):raise RuntimeError('开战前整队核验失败')
            self.verify_request_order(stage,state,report)
            if getattr(self,'automatic',False):
                self.preparing(stage);self.input.click(*self.g['start'])
            else:
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
            self.completed.append(stage)
            self.event('stage_won',stage_id=stage)
            if len(self.completed)>=self.max_stages:
                break
            expected_next=next_stage_id(self.catalog,stage)
            self.wait(lambda s:s.get('current_stage_id')==expected_next,15)
            advanced=self.continue_victory(self.snapshot())
            self.event('stage_advanced',stage_id=stage,next_stage=advanced['current_stage_id'])
        self.event('finished',reason='达到本次关卡数量上限')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--geometry',type=Path,help='可选：显式使用旧手工配置；默认自动识别当前画面')
    p.add_argument('--stages',type=int,default=5);p.add_argument('--budget',type=int,default=40)
    p.add_argument('--seconds',type=float,default=600,help='每关搜索秒数上限，0不限')
    p.add_argument('--optimize-until-limit',action='store_true',help='找到通过方案后仍继续优化到上限')
    p.add_argument('--review',choices=MODES,default='light',help='复核方式：light默认轻量，none关闭模拟复核，full完整')
    p.add_argument('--account-key',help='绑定工作台当前账号，切换游戏账号时停止')
    p.add_argument('--hwnd',type=int,help='双开时明确指定游戏窗口')
    p.add_argument('--foreground',action='store_true',help='改用前台系统鼠标；默认后台窗口输入')
    p.add_argument('--stop-file',type=Path)
    p.add_argument('--run-dir',type=Path);a=p.parse_args()
    if not 1<=a.stages<=100 or a.budget<0 or not math.isfinite(a.seconds) or a.seconds<0:p.error('关卡数1–100；候选/时长上限非负，0不限')
    import msvcrt
    RUNTIME.mkdir(parents=True,exist_ok=True)
    folder=a.run_dir or RUNTIME/'autoplay-runs'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
    def startup_event(event,**data):
        value=dict(time=datetime.now(timezone.utc).isoformat(),event=event,run_dir=str(folder),completed=[],**data)
        write_json(folder/'status.json',value);write_json(RUNTIME/'autoplay-status.json',value)
    startup_event('initializing')
    lock=None;locked=False;runner=None;controller=ExitStack()
    try:
        from desktop_input import find_game_window
        hwnd=find_game_window(a.hwnd) if a.hwnd is not None else find_game_window()
        if a.stop_file is None:
            a.stop_file=RUNTIME/'windows'/str(hwnd)/'AUTOPLAY-STOP';a.stop_file.unlink(missing_ok=True)
        lock=(RUNTIME/f'autoplay-{hwnd}.lock').open('a+b')
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('已有自动推关进程控制该游戏')
        locked=True
        sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
        from autogame.platforms.lease import device_lease
        # Keep fishing's existing lease key so older fishing workers also exclude us.
        controller.enter_context(device_lease('windows-fishing-'+str(hwnd),check_processes=False))
        runner=Runner(read_json(a.geometry) if a.geometry else None,a.budget,a.stages,run_dir=folder,
            max_search_seconds=a.seconds,stop_when_verified=not a.optimize_until_limit,review_mode=a.review,account_key=a.account_key,
            hwnd=hwnd,background=not a.foreground,stop_path=a.stop_file);runner.run()
    except Exception as exc:
        from job_status import error_code
        data=dict(reason=str(exc),reason_code=getattr(exc,'code',None) or error_code(exc))
        if runner:runner.event('stopped',**data)
        else:startup_event('stopped',**data)
        raise
    finally:
        if runner:runner.live.close()
        controller.close()
        if locked:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        if lock:lock.close()


if __name__=='__main__':main()
