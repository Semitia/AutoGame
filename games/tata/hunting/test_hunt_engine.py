"""Use a fake desktop transport. Tests never move the real mouse or activate windows."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from hunt_engine import Runner
from hunt_policy import Options
from test_hunt_policy import room,lobby,enemy


class Controls:
    def __init__(self):
        self.firing=False;self.clicks=[];self.window=SimpleNamespace(bounds=lambda:(0,0,400,750))
        self.on_click=lambda *p:None;self.fire_calls=0
    def stop_check(self):pass
    def set_reference(self,*args):pass
    def release(self):self.firing=False
    def click(self,*point):
        assert not self.firing
        self.clicks.append(point);self.on_click(*point)
    def start_fire(self,point):self.fire_calls+=1;self.firing=True


class EngineTests(unittest.TestCase):
    def driver(self,state,folder):
        current=[state];controls=Controls();events=[]
        live=SimpleNamespace(snapshot=lambda:copy.deepcopy(current[0]),refresh=lambda:None)
        layout=SimpleNamespace(close=lambda _: (10,10),icon=lambda *a:(20,20),aim=lambda _: (100,200))
        runner=Runner(Options(stock=2,rounds=1),live,controls,layout,lambda ev,**data:events.append((ev,data)),folder/'STOP')
        runner.image=lambda:Image.new('RGB',(400,750))
        return runner,current,controls,events

    def test_full_high_room_cycle_spends_one_lock_and_exits_without_any_manual_shot(self):
        with tempfile.TemporaryDirectory() as directory,patch('hunt_engine.time.sleep'):
            folder=Path(directory)
            with patch('hunt_engine.RUNTIME',folder):
                runner,current,controls,events=self.driver(room(locks=2,enemies=[enemy()]),folder)
                reads=[0]
                def snapshot():
                    if current[0].get('lock_active'):
                        reads[0]+=1
                        if reads[0]>=2:current[0]['enemies']=[]
                    return copy.deepcopy(current[0])
                runner.live.snapshot=snapshot
                def click(x,y):
                    if (x,y)==(20,20):current[0].update(lock_active=True,lock_target=77,locks=1)
                    elif (x,y)==(10,10):current[0]=lobby(1)
                controls.on_click=click;runner.run()
                self.assertEqual(controls.clicks,[(20,20),(10,10)])
                self.assertEqual(controls.fire_calls,0);self.assertEqual(runner.policy.completed,1)
                self.assertIn('room_exited',[ev for ev,_ in events])

    def test_exit_handles_own_reward_popup_and_confirms_lobby(self):
        with tempfile.TemporaryDirectory() as directory,patch('hunt_engine.time.sleep'):
            folder=Path(directory)
            with patch('hunt_engine.RUNTIME',folder):
                state=room(enemies=[],locked=True);runner,current,controls,events=self.driver(state,folder)
                def click(x,y):
                    current[0]=dict(lobby(),screen='reward') if len(controls.clicks)==1 else lobby()
                controls.on_click=click;controls.firing=True
                runner.exit_room(state,'目标结束')
                self.assertEqual(controls.clicks,[(10,10),(10,10)])
                self.assertFalse(controls.firing);self.assertEqual(events[-1][0],'room_exited')

    def test_target_gone_during_icon_recognition_does_not_spend_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            runner,current,controls,_=self.driver(room(enemies=[enemy()]),Path(directory))
            state=copy.deepcopy(current[0]);current[0]['enemies']=[]
            runner.click_item(state,'lock')
            self.assertFalse(controls.clicks);self.assertFalse(runner.policy.pending)

    def test_room_change_and_f8_cancel_without_input_and_release_held_mouse(self):
        with tempfile.TemporaryDirectory() as directory:
            runner,current,controls,_=self.driver(room(),Path(directory));before=copy.deepcopy(current[0])
            current[0]['room_token']=[202,2000,8]
            with self.assertRaisesRegex(RuntimeError,'房间已改变'):runner.exit_room(before,'test')
            self.assertFalse(controls.clicks)
            controls.firing=True;controls.stop_check=Mock(side_effect=RuntimeError('F8 stop'))
            with self.assertRaisesRegex(RuntimeError,'F8'):runner.run()
            self.assertFalse(controls.firing)
