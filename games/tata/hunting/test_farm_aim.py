import unittest
import cv2
import numpy as np
from PIL import Image
from farm_aim import FarmAim,farm_target,FIELD_ORIGIN,PIXELS_PER_UNIT
from hunt_layout import LayoutError


class AimTests(unittest.TestCase):
    def test_dense_ordinary_group_is_preferred_to_a_lone_boss(self):
        enemies=[dict(id=i,tid=1101,score=2,active=True,x=x,y=6) for i,x in [(1,6),(2,6.2),(3,5.8)]]
        enemies.append(dict(id=4,tid=2001,score=100,active=True,x=10,y=10))
        self.assertIn(farm_target(dict(enemies=enemies))['id'],(1,2,3))

    def test_native_coordinates_follow_original_art_projection_at_current_scale(self):
        aim=FarmAim();matrix=np.array([[.8,0,100],[0,.8,250]],dtype=np.float64)
        frame=cv2.warpAffine(aim.source,matrix,(800,1400))
        report=aim.recognize(Image.fromarray(frame),[1,2,1])
        self.assertGreaterEqual(report['inliers'],10)
        enemy=dict(id=1,tid=2001,score=100,active=True,x=-FIELD_ORIGIN[0],y=-FIELD_ORIGIN[1])
        expected=matrix@np.array([aim.source.shape[1]/2,aim.source.shape[0]/2,1])
        np.testing.assert_allclose(aim.point(enemy),expected,atol=2)
        self.assertIs(farm_target(dict(enemies=[enemy]),aim),enemy)

    def test_empty_field_waits_but_ordinary_mobs_are_valid_loot_targets(self):
        self.assertIsNone(farm_target(dict(enemies=[])))
        self.assertIsNotNone(farm_target(dict(enemies=[dict(id=1,tid=1101,score=1,active=True,x=6,y=6)])))
        with self.assertRaises(LayoutError):FarmAim().recognize(Image.new('RGB',(600,1200),'gray'),[1,2,1])

    def test_offscreen_boss_is_skipped_for_a_visible_boss(self):
        enemies=[dict(id=1,tid=2001,score=100,active=True,x=1,y=1),dict(id=2,tid=2001,score=100,active=True,x=6,y=6)]
        class Projector:
            def point(self,e):
                if e['id']==1:raise LayoutError('covered by HUD')
                return (300,600)
        self.assertEqual(farm_target(dict(enemies=enemies),Projector())['id'],2)
