"""Public-art fixtures only: no account screenshots and no desktop input."""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw

from auto_layout import AutoLayout, ASSETS, LayoutError, continue_button, yellow_button,chapter_start_button,center
from model import Catalog, RUNTIME


class AutoLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog();cls.detector=AutoLayout(cls.catalog)
        cls.state=dict(current_stage_id=826,field_offset=dict(x=-2.492,y=-5.188),
                       prepare={'_currentPrepareListRowCount':2},pet_list=list(range(1,15)))
        # Use a bundled map so clean checkouts need no old computer's cache.
        stage=cls.catalog.stage(cls.state['current_stage_id'])
        reference=cls.catalog.battle_resources[str(stage['battle']['ResID'])]['BackgroundRes']
        source=cv2.imread(str(cls.detector.image_path(reference)))
        cls.matrix=np.array([[.8,0,-105],[0,.8,-340]],dtype=float)
        background=cv2.warpAffine(source,cls.matrix,(856,1568))
        image=Image.fromarray(cv2.cvtColor(background,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,855,88),fill='white')
        draw.rectangle((193,165,663,400),fill='white')
        draw.rectangle((14,955,842,1310),fill='white')
        for index in range(12):
            x,y=37+(index//2)*136,997+(index%2)*151
            draw.rounded_rectangle((x,y,x+122,y+147),radius=5,fill='#7551bd',outline='#181b23',width=3)
            path=cls.detector.image_path(cls.catalog.resource(index+1,1)['IconName'])
            with Image.open(path) as icon:
                icon=icon.convert('RGBA');icon=icon.resize((round(icon.width*.75),round(icon.height*.75)))
                image.paste(icon,(x+3,y+2),icon)
        image.paste(Image.open(ASSETS/'prepare-controls.png'),(14,1311))
        image.paste(Image.open(ASSETS/'clear-arrow.png'),(748,738))
        cls.image=image

    def test_current_image_projection_and_controls_follow_scale(self):
        base=self.matrix@np.array([1334/2+(.5-2.492)*110,1875/2-(.5-5.188)*110,1])
        for scale in (.7,1,1.3):
            with self.subTest(scale=scale):
                image=self.image.resize((round(856*scale),round(1568*scale)))
                value=self.detector.recognize(image,self.state)
                np.testing.assert_allclose(value['grid'],base*scale,atol=3)
                self.assertAlmostEqual(value['gridStep'],88*scale,delta=2)
                self.assertAlmostEqual(value['start'][0],662.5*scale,delta=3)
                self.assertGreaterEqual(value['map_inliers'],8)
                self.assertEqual(set(value['filters']),{'2','3','4','5','6'})

    def test_visible_card_identity_and_scroll_use_current_images(self):
        pets={uid:dict(evoTID=1) for uid in self.state['pet_list']}
        found=self.detector.locate_card(self.image,self.state,1,pets)
        np.testing.assert_allclose(found['point'],[98.5,1071],atol=4)
        outside=self.detector.locate_card(self.image,self.state,13,pets)
        self.assertIn('swipe',outside)
        self.assertGreater(outside['swipe'][0],outside['swipe'][2])

    def test_card_lookup_does_not_require_a_start_button_on_every_transition_frame(self):
        geometry=self.detector.recognize(self.image,self.state)
        image=self.image.copy();draw=ImageDraw.Draw(image)
        draw.rectangle((490,1415,840,1530),fill='#46425a')
        pets={uid:dict(evoTID=1) for uid in self.state['pet_list']}
        with patch('auto_layout.yellow_button',side_effect=LayoutError('过渡帧开始按钮不可见')):
            found=self.detector.locate_card(image,self.state,1,pets,geometry=geometry)
        np.testing.assert_allclose(found['point'],[98.5,1071],atol=4)

    def test_filter_model_cannot_click_a_previous_frame_different_portrait(self):
        pets={uid:dict(evoTID=1) for uid in self.state['pet_list']}
        geometry=self.detector.recognize(self.image,self.state)
        state=dict(self.state,pet_list=[1,2])
        self.assertIn('point',self.detector.locate_card(self.image,state,1,pets,geometry=geometry))
        state=dict(self.state,pet_list=[13,14])
        with self.assertRaisesRegex(LayoutError,'筛选一致'):
            self.detector.locate_card(self.image,state,13,pets,geometry=geometry)

    def test_blank_or_wrong_screen_is_rejected_without_guessed_coordinates(self):
        with self.assertRaises(LayoutError):self.detector.recognize(Image.new('RGB',(856,1568),'white'),self.state)
        state=dict(self.state,field_offset={})
        with self.assertRaisesRegex(LayoutError,'战场偏移'):self.detector.recognize(self.image,state)

    def test_victory_continue_is_green_and_back_button_is_not_selected(self):
        image=Image.new('RGB',(856,1568),'#181421');draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((35,1415,410,1510),radius=12,fill='#b7b6c4')
        draw.rounded_rectangle((435,1415,810,1510),radius=12,fill='#83d527')
        frame=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)
        np.testing.assert_allclose(center(continue_button(frame)),[622.5,1462.5],atol=2)
        with self.assertRaises(LayoutError):yellow_button(frame)

    def test_chapter_button_requires_the_wide_bottom_start_button(self):
        image=Image.new('RGB',(856,1568),'#181421');draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((435,1120,810,1210),radius=12,fill='#f5cc20')
        draw.rounded_rectangle((25,1415,830,1510),radius=12,fill='#f5cc20')
        frame=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)
        np.testing.assert_allclose(center(chapter_start_button(frame)),[427.5,1462.5],atol=2)
        draw.rectangle((0,1400,855,1550),fill='#181421')
        with self.assertRaises(LayoutError):chapter_start_button(cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR))


@unittest.skipUnless(os.name=='nt','Windows point transport')
class WindowAdaptationTests(unittest.TestCase):
    def test_layout_cli_uses_selected_window_background_without_input(self):
        import sys
        from unittest.mock import Mock
        import auto_layout
        image=Image.new('RGB',(400,750))
        live=SimpleNamespace(snapshot=lambda:dict(battle=dict(state=1)),close=Mock())
        capture=Mock(return_value=image)
        detector=SimpleNamespace(recognize=Mock(return_value=dict(width=400,height=750,map_inliers=20)))
        runtime=SimpleNamespace(window_pids=Mock(return_value=[999]),background_input=Mock(return_value=SimpleNamespace(capture=capture)))
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'windows_runtime':runtime}),\
             patch.object(sys,'argv',['auto_layout','--hwnd','123','--out',str(Path(directory)/'layout.json')]),\
             patch('desktop_input.find_game_window',return_value=123),patch('live_battle.LiveBattle',return_value=live) as create,\
             patch.object(auto_layout,'AutoLayout',return_value=detector):
            self.assertEqual(auto_layout.main(),0)
        create.assert_called_once_with(pids=[999]);runtime.background_input.assert_called_once_with(123)
        capture.assert_called_once();live.close.assert_called_once()

    def test_fast_gesture_retains_segmented_drag_and_always_releases_on_failure(self):
        import desktop_input as transport
        game=transport.GameInput.__new__(transport.GameInput)
        game.window=SimpleNamespace(bounds=lambda:(0,0,400,750));game.gesture_bounds=None
        game.point=lambda x,y:SimpleNamespace(x=x,y=y)
        buttons=[];moves=[];sleeps=[]
        game.button=buttons.append;game.stop_check=lambda:None
        fake=SimpleNamespace(SetCursorPos=lambda x,y:moves.append((x,y)))
        with patch.object(transport,'user',fake),patch.object(transport.time,'sleep',side_effect=sleeps.append):
            game.drag(10,20,70,80)
        self.assertEqual(buttons,[True,False])
        self.assertEqual(moves[-1],(70,80))
        self.assertEqual(len(moves),13)
        self.assertAlmostEqual(sum(sleeps),.23)
        buttons.clear()
        checks=iter([None,RuntimeError('游戏失去前台')])
        def check():
            error=next(checks)
            if error:raise error
        game.stop_check=check
        with patch.object(transport,'user',fake),patch.object(transport.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'失去前台'):game.drag(10,20,70,80)
        self.assertEqual(buttons,[True,False])
        self.assertIsNone(game.gesture_bounds)

    def test_default_cli_uses_automatic_recognition_without_a_geometry_file(self):
        from autoplay import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runner=SimpleNamespace(run=lambda:None,live=SimpleNamespace(close=lambda:None))
            with patch('sys.argv',['autoplay','--stages','1','--run-dir',str(root)]),patch('autoplay.RUNTIME',root),\
                 patch('autoplay.Runner',return_value=runner) as create,patch('msvcrt.locking'),\
                 patch('desktop_input.find_game_window',return_value=123):
                main()
            self.assertIsNone(create.call_args.args[0])

    def test_moving_window_rebases_points_and_resizing_requires_fresh_recognition_only(self):
        import desktop_input as transport
        bounds=[100,200,400,750]
        window=SimpleNamespace(hwnd=1,bounds=lambda:tuple(bounds),is_foreground=lambda:True,emergency_stop=lambda:False)
        game=transport.GameInput.__new__(transport.GameInput)
        game.window=window;game.reference=(400,750);game.initial_dimensions=(400,750)
        game.adaptive=True;game.gesture_bounds=None
        fake=SimpleNamespace(WindowFromPoint=lambda point:1,GetAncestor=lambda hwnd,kind:hwnd)
        with patch.object(transport,'user',fake):
            p=game.point(100,300);self.assertEqual((p.x,p.y),(200,500))
            bounds[:2]=[500,600]
            p=game.point(100,300);self.assertEqual((p.x,p.y),(600,900))
            bounds[2:]=[800,1500]
            with self.assertRaises(transport.LayoutChanged):game.point(100,300)
            game.set_reference(800,1500)
            p=game.point(200,600);self.assertEqual((p.x,p.y),(700,1200))
            game.gesture_bounds=tuple(bounds);bounds[0]+=10
            with self.assertRaises(transport.LayoutChanged) as caught:game.stop_check()
            self.assertTrue(caught.exception.gesture)
