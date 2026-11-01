"""No real screenshots or input: verify local coordinates and account isolation."""
import ctypes
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
import hunt_paths
import background_input as transport
import window_binding as binding


class BackgroundTests(unittest.TestCase):
    def test_background_fire_pulses_respect_native_interval(self):
        game,_,_=self.driver();game.last_pulse=float('-inf');game.click=Mock();game.release=Mock()
        with patch.object(transport.time,'monotonic',return_value=0):game.fire_at((100,300),.33)
        with patch.object(transport.time,'monotonic',return_value=.1):game.fire_at((101,301),.33)
        with patch.object(transport.time,'monotonic',return_value=.34):game.fire_at((102,302),.33)
        self.assertEqual(game.click.call_count,2)

    def test_partial_gpu_frame_is_rejected_even_with_a_complete_title_bar(self):
        image=Image.new('RGB',(400,750),'black');draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,399,50),fill='white');draw.rectangle((0,100,200,180),fill='purple')
        with self.assertRaises(transport.CaptureFrameError):transport.validate_frame(image)

    def driver(self):
        bounds=[100,200,400,750]
        game=transport.BackgroundHuntInput.__new__(transport.BackgroundHuntInput)
        game.window=SimpleNamespace(hwnd=7,bounds=lambda:tuple(bounds),emergency_stop=lambda:False,
            is_foreground=lambda:False)
        game.owner=99;game.reference=(400,750);game.initial_dimensions=(400,750)
        game.gesture_bounds=None;game.firing=False;game.held_point=None
        def client(hwnd,point):point._obj.x-=110;point._obj.y-=220;return 1
        def rect(hwnd,value):value._obj.right=400;value._obj.bottom=750;return 1
        fake=SimpleNamespace(ScreenToClient=client,GetClientRect=rect,PostMessageW=Mock(return_value=1))
        return game,bounds,fake

    def test_background_click_uses_client_coordinates_without_global_mouse_or_focus(self):
        game,_,fake=self.driver()
        with patch.object(transport,'user',fake),patch.object(transport,'owner_pid',return_value=99),patch.object(transport.time,'sleep'):
            game.click(100,300)
        calls=[call.args for call in fake.PostMessageW.call_args_list]
        self.assertEqual([c[1] for c in calls],[0x200,0x201,0x202])
        self.assertTrue(all(c[0]==7 and c[3]==(90|(280<<16)) for c in calls))
        self.assertIsNone(game.gesture_bounds)

    def test_held_fire_releases_on_size_change_and_never_posts_to_reused_hwnd(self):
        game,bounds,fake=self.driver()
        with patch.object(transport,'user',fake),patch.object(transport,'owner_pid',return_value=99):
            game.start_fire((100,300));self.assertTrue(game.firing)
            bounds[2]=800
            with self.assertRaises(transport.LayoutChanged):game.stop_check()
            game.release()
        self.assertEqual(fake.PostMessageW.call_args_list[-1].args[1],0x202)
        fake.PostMessageW.reset_mock()
        game.firing=True
        with patch.object(transport,'user',fake),patch.object(transport,'owner_pid',return_value=100):
            with self.assertRaisesRegex(RuntimeError,'替换'):game.stop_check()
            game.release()
        fake.PostMessageW.assert_not_called();self.assertFalse(game.firing)

    def test_capture_failure_stays_background_and_does_not_send_input(self):
        game,_,fake=self.driver()
        with patch.object(transport,'user',fake),patch.object(transport,'owner_pid',return_value=99),\
             patch.object(transport,'print_window',side_effect=RuntimeError('unsupported')):
            with self.assertRaisesRegex(RuntimeError,'unsupported'):game.capture()
        fake.PostMessageW.assert_not_called()

    def test_renderer_binding_excludes_other_wechat_process_and_rejects_ambiguous_owner(self):
        rows=[dict(ProcessId=p,ParentProcessId=parent,Renderer=renderer) for p,parent,renderer in
              [(10,1,False),(11,10,False),(12,11,True),(20,1,False),(21,20,True)]]
        result=SimpleNamespace(returncode=0,stdout=json.dumps(rows))
        with patch.object(binding,'find_game_window'),patch.object(binding,'game_windows',return_value=[7,8]),\
             patch.object(binding,'owner_pid',side_effect=lambda hwnd:{7:10,8:20}[hwnd]),\
             patch.object(binding.subprocess,'run',return_value=result):
            self.assertEqual(binding.bound_renderers(7),[12])
        with patch.object(binding,'find_game_window'),patch.object(binding,'game_windows',return_value=[7,8]),\
             patch.object(binding,'owner_pid',return_value=10):
            with self.assertRaisesRegex(RuntimeError,'无法唯一绑定'):binding.bound_renderers(7)
