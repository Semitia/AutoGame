"""Foreground hunt loop; no game memory writes, Lua calls or network requests."""
from pathlib import Path
import time
from hunt_paths import RUNTIME
from hunt_policy import Policy
from live_roster import LiveReadError


class Runner:
    def __init__(self,options,live,controls,layout,emit,stop_path=None,evidence_dir=None):
        self.options=options.validate();self.policy=Policy(options)
        self.live=live;self.input=controls;self.layout=layout;self.emit=emit
        self.stop_path=Path(stop_path or RUNTIME/'STOP');self.cached=None
        self.room_token=None;self.last_refresh=0.;self.pending_since=None;self.stopping=False
        self.evidence_dir=Path(evidence_dir) if evidence_dir else None;self.last_observation=None

    def check(self,allow_stop=False):
        self.input.stop_check()
        if (self.stop_path.exists() or (RUNTIME/'STOP').exists()) and not allow_stop:raise InterruptedError('用户请求停止')

    def snapshot(self):
        self.input.stop_check()
        self.last_observation=self.live.snapshot()
        return self.last_observation

    def wait(self,predicate,seconds=12,allow_stop=False):
        end=time.monotonic()+seconds;error=None
        while time.monotonic()<end:
            self.check(allow_stop)
            try:
                state=self.snapshot()
                if predicate(state):return state
            except LiveReadError as exc:error=exc
            if time.monotonic()-self.last_refresh>.4:
                self.live.refresh();self.last_refresh=time.monotonic()
            time.sleep(.02)
        raise RuntimeError('围猎状态等待超时'+('：'+str(error) if error else ''))

    def image(self):
        from calibration import capture_visible_game
        image=capture_visible_game();self.input.set_reference(*image.size)
        if self.evidence_dir:
            self.evidence_dir.mkdir(parents=True,exist_ok=True);image.save(self.evidence_dir/'last-layout.png')
        return image

    def room_controls(self,state):
        size=self.input.window.bounds()[2:]
        if self.cached and self.cached['size']==size and self.cached['room']==tuple(state['room_token']):return self.cached
        image=self.image()
        self.cached=dict(size=image.size,room=tuple(state['room_token']),close=self.layout.close(image))
        # Locate consumables only when an action is requested. An active item's
        # countdown may hide its icon and must not prevent the emergency exit.
        return self.cached

    def room_check(self,before,after):
        if after['screen']!='room' or before['account_key']!=after['account_key'] or before['room_token']!=after['room_token']:
            raise RuntimeError('输入前围猎账号或房间已改变，停止')

    def click_item(self,state,name):
        self.input.release();point=self.layout.icon(self.image(),name)
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
                and (s['rage_active'] or s['rage']<state['rage']),3)

    def exit_room(self,state,reason,allow_stop=False):
        self.input.release();controls=self.room_controls(state)
        current=self.snapshot();self.room_check(state,current)
        started=time.perf_counter()
        self.input.click(*controls['close']);self.emit('exit_requested',reason=reason)
        end=time.monotonic()+12;last_reward_tap=float('-inf')
        while time.monotonic()<end:
            self.check(allow_stop)
            try:
                current=self.snapshot()
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
        self.input.release();kind=action['kind'];image=self.image()
        point=self.layout.start(image) if kind=='enter' else self.layout.navigation(image,kind)
        latest=self.snapshot()
        if (latest['screen']!='lobby' or latest['switching'] or latest['selected_dungeon']!=state['selected_dungeon']
            or self.policy.decide(latest)!=action):raise RuntimeError('场地选择已改变，未点击')
        self.input.click(*point);self.emit(kind,selected_dungeon=state['selected_dungeon'])
        if kind=='enter':
            current=self.wait(lambda s:s['screen']=='room' and s['room_token'][2]==action['dungeon'],20)
            self.room_controls(current)
        else:self.wait(lambda s:s['screen']=='lobby' and not s['switching'] and s['selected_dungeon']!=state['selected_dungeon'],5)

    def run(self):
        end=time.monotonic()+self.options.seconds;previous=None;last_metrics=0.
        try:
            self.wait(lambda s:s['screen'] in ('room','lobby','reward'),20)
            while time.monotonic()<end:
                self.check();s=self.snapshot()
                if s['screen']=='room':self.room_controls(s)
                action=self.policy.decide(s);kind=action['kind']
                if kind!=previous or time.monotonic()-last_metrics>1:
                    self.emit('state',phase=kind,reason=action.get('reason',''),completed=self.policy.completed,
                        locks=s['locks'],rage=s['rage'],bullets=s['bullets'],multiplier=s.get('multiplier'))
                    previous=kind;last_metrics=time.monotonic()
                if kind=='finish':break
                if kind in ('enter','next','previous'):self.lobby_action(s,action)
                elif kind=='exit':
                    self.exit_room(s,action['reason']);self.policy.exited(action);self.pending_since=None
                    if action.get('finish'):break
                elif kind in ('lock','rage'):self.click_item(s,kind)
                elif kind=='fire':
                    # Never reuse a firing gesture after changing room or size.
                    if s['multiplier']!=self.options.low_multiplier:raise RuntimeError('高倍场禁止手动射击')
                    if not self.input.firing:
                        point=self.layout.aim(self.image());latest=self.snapshot();self.room_check(s,latest)
                        if self.policy.decide(latest)['kind']=='fire':self.input.start_fire(point)
                else:
                    self.input.release()
                    if self.policy.pending and self.pending_since is not None and time.monotonic()-self.pending_since>3:
                        self.exit_room(s,'锁定未及时确认，退出避免重复消耗道具')
                        raise RuntimeError('锁定道具未在3秒内回读确认，已请求退出')
                time.sleep(.02)
            self.input.release()
            current=self.snapshot()
            if current['screen']=='room':self.exit_room(current,'本次运行结束')
            self.emit('finished',completed=self.policy.completed,reason='达到轮数或时长上限')
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
