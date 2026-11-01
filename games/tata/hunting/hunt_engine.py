"""Hunt loop with a selected desktop transport; no game memory writes or requests."""
from pathlib import Path
from dataclasses import replace
import json
import time
from hunt_paths import RUNTIME
from hunt_policy import Policy
from hunt_layout import LayoutError
from live_roster import LiveReadError


class Runner:
    def __init__(self,options,live,controls,layout,emit,stop_path=None,evidence_dir=None,control_path=None,initial_mode=None):
        self.options=options.validate();self.policy=Policy(options)
        if initial_mode in ('farm','hunt'):self.policy.mode=initial_mode
        self.live=live;self.input=controls;self.layout=layout;self.emit=emit
        self.stop_path=Path(stop_path or RUNTIME/'STOP');self.cached=None
        self.room_token=None;self.last_refresh=time.monotonic();self.pending_since=None;self.stopping=False
        self.evidence_dir=Path(evidence_dir) if evidence_dir else None;self.last_observation=None
        self.farm_aim=None;self.last_aim=0.;self.last_aim_log=0.;self.last_aim_warning=0.
        self.control_path=Path(control_path) if control_path else None;self.last_control=0.
        self.rage_retry_at=0.

    def update_control(self):
        if self.control_path is None or time.monotonic()-self.last_control<1:return
        self.last_control=time.monotonic()
        try:value=json.loads(self.control_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return
        tids=tuple(value.get('targets',self.options.target_tids))
        if tids!=self.options.target_tids:
            self.options=replace(self.options,target_tids=tids).validate();self.policy.options=self.options
            self.emit('targets_changed',targets=list(tids),reason='已更新允许目标：'+self.options.target_name)

    def check(self,allow_stop=False):
        self.input.stop_check()
        if (self.stop_path.exists() or (RUNTIME/'STOP').exists()) and not allow_stop:raise InterruptedError('用户请求停止')

    def snapshot(self):
        self.input.stop_check()
        self.last_observation=self.live.snapshot()
        return self.last_observation

    def ready_snapshot(self):
        try:return self.snapshot()
        except LiveReadError as exc:
            if '账号' in str(exc):raise
            self.input.release();self.emit('recovering',reason='重新定位围猎界面：'+str(exc))
            self.live.refresh()
            return self.wait(lambda current:current['screen'] in ('room','lobby','reward'),60)

    def wait(self,predicate,seconds=12,allow_stop=False,refresh=True):
        end=time.monotonic()+seconds;error=None
        while time.monotonic()<end:
            self.check(allow_stop)
            try:
                state=self.snapshot()
                if predicate(state):return state
            except LiveReadError as exc:error=exc
            if refresh and time.monotonic()-self.last_refresh>.4:
                self.live.refresh();self.last_refresh=time.monotonic()
            time.sleep(.02)
        raise RuntimeError('围猎状态等待超时'+('：'+str(error) if error else ''))

    def image(self):
        image=self.input.capture();self.input.set_reference(*image.size)
        if self.evidence_dir:
            self.evidence_dir.mkdir(parents=True,exist_ok=True);image.save(self.evidence_dir/'last-layout.png')
        return image

    def room_controls(self,state):
        size=self.input.window.bounds()[2:]
        if self.cached and self.cached['size']==size and self.cached['room']==tuple(state['room_token']):return self.cached
        deadline=time.monotonic()+1.2
        while True:
            self.input.release();image=self.image()
            try:close=self.layout.close(image);break
            except LayoutError:
                if time.monotonic()>=deadline:raise
                self.room_check(state,self.snapshot());self.check();time.sleep(.03)
        self.cached=dict(size=image.size,room=tuple(state['room_token']),close=close)
        # Locate consumables only when an action is requested. An active item's
        # countdown may hide its icon and must not prevent the emergency exit.
        return self.cached

    def room_check(self,before,after):
        if after['screen']!='room' or before['account_key']!=after['account_key'] or before['room_token']!=after['room_token']:
            raise RuntimeError('输入前围猎账号或房间已改变，停止')

    def click_item(self,state,name):
        self.input.release()
        try:point=self.layout.icon(self.image(),name)
        except LayoutError as exc:
            if name!='rage':raise
            # Incoming boss portraits can temporarily cover the rage icon.
            # Keep farming the real mobs and retry the visible button later.
            self.rage_retry_at=time.monotonic()+2
            self.emit('rage_wait',reason='狂暴按钮暂被遮挡，继续瞄准怪群并稍后重试：'+str(exc))
            return
        current=self.snapshot();self.room_check(state,current)
        if name=='lock':
            # Recheck after image work, immediately before spending an item.
            if self.policy.decide(current)['kind']!='lock':return
            self.policy.pending=True;self.pending_since=time.monotonic()
        else:
            if current['multiplier']!=self.options.low_multiplier:raise RuntimeError('禁止在高倍场使用狂暴')
            if self.policy.decide(current)['kind']!='rage':return
        self.input.click(*point);self.emit(name+'_requested',locks=current['locks'],rage=current['rage'])
        if name=='rage':
            self.wait(lambda s:s['screen']=='room' and s['room_token']==state['room_token']
                and s['rage_active'],8,refresh=False)

    def dismiss_empty_balance_offer(self,state,allow_stop=False):
        if not state.get('purchase_popup'):return state
        if state['bullets']>self.options.reserve+state['multiplier']:
            raise RuntimeError('礼包页面覆盖围猎，停止输入以免误操作')
        self.input.release();point=self.layout.purchase_close(self.image())
        current=self.snapshot();self.room_check(state,current)
        if not current.get('purchase_popup'):return current
        self.input.click(*point);self.emit('purchase_dismissed',reason='金猎币不足，仅关闭礼包，不购买')
        return self.wait(lambda s:s['screen']=='room' and not s.get('purchase_popup'),8,allow_stop=allow_stop,refresh=False)

    def exit_room(self,state,reason,allow_stop=False):
        state=self.dismiss_empty_balance_offer(state,allow_stop)
        self.input.release();controls=self.room_controls(state)
        current=self.snapshot();self.room_check(state,current)
        started=time.perf_counter()
        self.input.click(*controls['close']);self.emit('exit_requested',reason=reason)
        end=time.monotonic()+30;last_reward_tap=float('-inf')
        while time.monotonic()<end:
            self.check(allow_stop)
            try:
                current=self.snapshot()
                if current['screen']=='room' and current.get('purchase_popup'):
                    current=self.dismiss_empty_balance_offer(current,allow_stop)
                    self.room_check(state,current);self.input.click(*controls['close'])
                    self.emit('exit_requested',reason='关闭余额不足礼包后继续退出')
                if current['screen']=='lobby':
                    self.cached=None;self.emit('room_exited',elapsed_ms=round((time.perf_counter()-started)*1000,1));return
                if (current['screen']=='reward' and not current.get('reward_fly_started')
                    and time.monotonic()-last_reward_tap>.15):
                    image=self.image()
                    # Reuse the verified exit point while the full-screen reward
                    # overlay owns input. If it closes during this gesture, the
                    # underlying point is Exit, never a 200x firing position.
                    point=controls['close'] if image.size==controls['size'] else (image.width/2,image.height*.97)
                    if self.snapshot()['screen']!='reward':continue
                    # Original BaseRewardView.OnSimpleTap accepts a tap anywhere
                    # on its full-screen UI and starts PlayFlyAnim/closeCallback.
                    self.input.click(*point);last_reward_tap=time.monotonic();self.emit('exit_reward_closed')
            except LiveReadError:pass
            if time.monotonic()-self.last_refresh>.3:
                self.live.refresh();self.last_refresh=time.monotonic()
            time.sleep(.02)
        raise RuntimeError('退出未完成，已停止后续射击；请检查围猎奖励页')

    def lobby_action(self,state,action):
        self.input.release();kind=action['kind'];deadline=time.monotonic()+1.2
        while True:
            self.check();image=self.image()
            try:
                point=self.layout.start(image) if kind=='enter' else self.layout.navigation(image,kind)
                break
            except LayoutError:
                if time.monotonic()>=deadline:raise
                time.sleep(.03)
        latest=self.snapshot()
        if (latest['screen']!='lobby' or latest['switching'] or latest['selected_dungeon']!=state['selected_dungeon']
            or self.policy.decide(latest)!=action):raise RuntimeError('场地选择已改变，未点击')
        self.input.click(*point);self.emit(kind,selected_dungeon=state['selected_dungeon'])
        if kind=='enter':
            current=self.wait(lambda s:s['screen']=='room' and s['room_token'][2]==action['dungeon'],60)
            self.room_controls(current)
        else:self.wait(lambda s:s['screen']=='lobby' and not s['switching'] and s['selected_dungeon']!=state['selected_dungeon'],5,refresh=False)

    def run(self):
        end=time.monotonic()+self.options.seconds;previous=None;last_metrics=0.;finish_reason='达到轮数或时长上限'
        try:
            self.wait(lambda s:s['screen'] in ('room','lobby','reward'),20)
            while time.monotonic()<end:
                self.check();self.update_control();s=self.ready_snapshot()
                if s['screen']=='transition':
                    self.input.release()
                    self.wait(lambda current:current['screen'] in ('room','lobby','reward'),20)
                    continue
                if s['screen']=='room':
                    s=self.dismiss_empty_balance_offer(s);self.room_controls(s)
                action=self.policy.decide(s)
                if action['kind']=='rage' and time.monotonic()<self.rage_retry_at:
                    action=dict(kind='fire',reason='狂暴按钮暂被遮挡，继续打怪等待重试')
                kind=action['kind']
                if kind!=previous or time.monotonic()-last_metrics>1:
                    self.emit('state',phase=kind,reason=action.get('reason',''),completed=self.policy.completed,
                        locks=s['locks'],rage=s['rage'],bullets=s['bullets'],multiplier=s.get('multiplier'),
                        lock_active=s.get('lock_active',False),lock_target=s.get('lock_target'),target=self.policy.target,mode=self.policy.mode)
                    previous=kind;last_metrics=time.monotonic()
                if kind=='finish':finish_reason=action.get('reason',finish_reason);break
                if kind in ('enter','next','previous'):self.lobby_action(s,action)
                elif kind=='exit':
                    self.exit_room(s,action['reason']);self.policy.exited(action);self.pending_since=None
                    if action.get('finish'):finish_reason=action['reason'];break
                elif kind in ('lock','rage'):self.click_item(s,kind)
                elif kind=='fire':
                    # Never reuse a firing gesture after changing room or size.
                    if s['multiplier']!=self.options.low_multiplier:raise RuntimeError('高倍场禁止手动射击')
                    if time.monotonic()-self.last_aim>=.08:
                        from farm_aim import FarmAim,farm_target
                        if self.farm_aim is None:self.farm_aim=FarmAim()
                        if self.farm_aim.size!=self.input.window.bounds()[2:] or self.farm_aim.room!=tuple(s['room_token']):
                            self.input.release()
                            try:self.farm_aim.recognize(self.image(),s['room_token'])
                            except LayoutError as exc:
                                if time.monotonic()-self.last_aim_warning>1:
                                    self.emit('aim_wait',reason=str(exc));self.last_aim_warning=time.monotonic()
                                time.sleep(.05);continue
                        latest=self.snapshot();self.room_check(s,latest);target=farm_target(latest,self.farm_aim)
                        if target is None:self.input.release();time.sleep(.02);continue
                        try:point=self.farm_aim.point(target)
                        except LayoutError:self.input.release();time.sleep(.02);continue
                        decision=self.policy.decide(latest)['kind']
                        if decision=='fire' or (decision=='rage' and time.monotonic()<self.rage_retry_at):
                            self.input.fire_at(point,.165 if latest['rage_active'] else .33);self.last_aim=time.monotonic()
                            if self.last_aim-self.last_aim_log>1:
                                self.emit('aim',target_id=target['id'],target_tid=target['tid'],point=point)
                                self.last_aim_log=self.last_aim
                else:
                    self.input.release()
                    if self.policy.pending and self.pending_since is not None and time.monotonic()-self.pending_since>3:
                        self.exit_room(s,'锁定未及时确认，退出避免重复消耗道具')
                        raise RuntimeError('锁定道具未在3秒内回读确认，已请求退出')
                time.sleep(.02)
            self.input.release()
            current=self.snapshot()
            if current['screen']=='room':self.exit_room(current,'本次运行结束')
            self.emit('finished',completed=self.policy.completed,reason=finish_reason)
        except InterruptedError:
            self.input.release();current=self.snapshot()
            if current['screen']=='room':self.exit_room(current,'用户停止',allow_stop=True)
            self.emit('stopped',completed=self.policy.completed,reason='用户停止，已退出围猎')
        except Exception:
            if self.evidence_dir and self.last_observation:
                from model import write_json
                write_json(self.evidence_dir/'last-observation.json',self.last_observation)
            raise
        finally:self.input.release()
