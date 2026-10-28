"""Recorded-screen regressions and native input safety checks."""
import ctypes
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from desktop_vision import DesktopVision
from windows import DesktopWindow,Input
from panel import FishingPanel
from aim import SliderAim


class RecordedVisionTests(unittest.TestCase):
    def setUp(self):self.vision=DesktopVision()

    def observation(self,name):
        frame=cv2.imread(str(HERE/'testdata'/f'{name}.png'))
        self.assertIsNotNone(frame)
        return self.vision.observe(frame)

    def test_recorded_idle_and_bite(self):
        self.assertEqual(self.observation('idle').state,'idle')
        bite=self.observation('hook')
        self.assertEqual(bite.state,'hook')
        self.assertIsNone(bite.pointer)

    def test_recorded_slider_coordinates(self):
        obs=self.observation('slider')
        self.assertEqual(obs.state,'slider')
        self.assertAlmostEqual(obs.pointer,235,delta=2)
        self.assertAlmostEqual(obs.yellow[0],170,delta=2)
        self.assertAlmostEqual(obs.yellow[1],254,delta=2)

    def test_ordinary_and_rare_results_are_distinct(self):
        self.assertEqual(self.observation('ordinary').state,'reward_animation')
        self.assertEqual(self.observation('rare').state,'rare_reward')

    def test_unrelated_page_rejected(self):
        self.assertEqual(self.vision.observe(np.full((750,400,3),255,np.uint8)).state,'unknown')

    def test_personal_record_does_not_stop_as_unknown(self):
        self.assertEqual(self.observation('record').state,'record_reward')

    def test_success_text_above_track_cannot_expand_yellow_target(self):
        frame=cv2.imread(str(HERE/'testdata'/'slider.png'))
        before=self.vision.observe(frame)
        cv2.rectangle(frame,(95,455),(305,480),(0,240,255),-1)
        after=self.vision.observe(frame)
        self.assertEqual(after.state,'slider')
        self.assertEqual(after.yellow,before.yellow)
        self.assertEqual(after.pointer,before.pointer)

    def test_unknown_record_title_uses_fish_card_layout(self):
        frame=cv2.imread(str(HERE/'testdata'/'record.png'))
        frame[120:220,70:330]=frame[110,350]
        self.assertTrue(self.vision.is_result_card(frame))
        self.assertEqual(self.vision.observe(frame).state,'result_card')

    def test_three_pixel_target_and_full_occlusion_still_keep_slider(self):
        frame=cv2.imread(str(HERE/'testdata'/'slider.png'))
        hsv=cv2.cvtColor(frame[509:522,110:303],cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(18,100,150),(40,255,255))>0
        blue=frame[515,290].copy()
        frame[509:522,110:303][mask]=blue
        self.assertEqual(self.vision.observe(frame).state,'slider')
        self.assertIsNone(self.vision.observe(frame).yellow)
        frame[510:521,180:183]=(0,240,255)
        obs=self.vision.observe(frame)
        self.assertEqual(obs.state,'slider')
        self.assertEqual(obs.yellow,(180,183))


class PredictiveAimTests(unittest.TestCase):
    def feed(self,aim,target=(222,226),lead=.04):
        result=None
        for stamp,x in [(0.,200.),(.04,205.2),(.08,210.4)]:
            result=aim.update(stamp,x,target,stamp+.02,lead)
        return result

    def test_schedules_tiny_target_between_capture_frames(self):
        result=self.feed(SliderAim())
        self.assertIsNotNone(result.delay)
        self.assertGreater(result.delay,0)
        hit=result.predicted+result.speed*result.delay
        self.assertAlmostEqual(hit,224,delta=.1)

    def test_target_survives_pointer_occlusion(self):
        aim=SliderAim();self.feed(aim)
        result=aim.update(.12,215.6,None,.14)
        self.assertEqual(result.target,(222,226))
        self.assertAlmostEqual(result.speed,130,delta=1)

    def test_click_resets_target_and_blocks_success_animation(self):
        aim=SliderAim();self.feed(aim);aim.fired(.15)
        self.assertIsNone(aim.update(.18,220,(222,226),.20))

    def test_reflects_prediction_at_track_edge(self):
        aim=SliderAim()
        for stamp,x in [(0.,142.),(.04,136.8),(.08,131.6)]:
            result=aim.update(stamp,x,(116,121),stamp+.02,.15)
        self.assertAlmostEqual(result.predicted,118.5,delta=1)
        self.assertEqual(result.delay,0)


class InputSafetyTests(unittest.TestCase):
    def test_sendinput_matches_windows_abi(self):
        self.assertEqual(ctypes.sizeof(Input),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

    def test_lost_foreground_never_moves_or_clicks_mouse(self):
        window=DesktopWindow(123)
        with patch.object(window,'is_foreground',return_value=False),patch('windows.user.SendInput') as send:
            with self.assertRaisesRegex(RuntimeError,'Refusing input'):window.click()
            send.assert_not_called()


class PanelCounterTests(unittest.TestCase):
    def test_result_close_retry_does_not_count_the_same_fish_twice(self):
        panel=FishingPanel.__new__(FishingPanel)
        panel.counts={'cast':0,'reel':0,'collect':0}
        panel.metrics=unittest.mock.Mock()
        panel.add_log=unittest.mock.Mock()
        row=dict(event='click',action='dismiss_record',casts=1,slider_clicks=2,rewards=1)
        panel.handle(json.dumps(row));panel.handle(json.dumps(row))
        self.assertEqual(panel.counts,{'cast':1,'reel':2,'collect':1})


if __name__=='__main__':unittest.main()
