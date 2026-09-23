import unittest
import json
from pathlib import Path
import cv2
import numpy as np
from coop_vision import BoardVision,layer,read_prices,owner_side,wave_number
from coop_ui import Label

ROOT=Path(__file__).resolve().parents[2]
LEFT={(111,460)}|{(x,y) for x in (77,111,146) for y in (494,527)}
RIGHT={(320,460),(355,460),(320,562)}|{(x,y) for x in (285,320,355) for y in (494,527)}


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=BoardVision()

    def test_both_viewpoints_empty_and_occupied_and_expansion(self):
        for view in ('host','guest'):
            image=cv2.imread(str(ROOT/f'docs/evidence/coop-20260923/dual-battle-{view}-1080.png'))
            for side,cells,occupied in [('host',LEFT,set()),('guest',RIGHT,RIGHT)]:
                with self.subTest(view=view,side=side):
                    result=self.vision.read(image,side)
                    self.assertTrue(result.verified)
                    self.assertEqual(result.cells,cells)
                    self.assertEqual(result.occupied,occupied)
                    self.assertNotIn((285,460),result.cells)  # adjacent decorative platform

    def test_real_ocr_labels_and_owner_match_both_devices(self):
        for view in ('host','guest'):
            labels=[Label(**p) for p in json.loads((ROOT/f'docs/evidence/coop-20260923/dual-battle-{view}.ocr.json').read_text(encoding='utf8'))]
            image=cv2.imread(str(ROOT/f'docs/evidence/coop-20260923/dual-battle-{view}-1080.png'))
            self.assertEqual(layer(labels,'踏实的龙利鱼','幽美的竹笋',1),'battle')
            self.assertEqual(layer(labels,'踏实的龙利鱼','幽美的竹笋',2),'unknown')
            self.assertEqual(owner_side(image),view)
            self.assertEqual(wave_number(labels),7)

    def test_rescaled_native_screenshot(self):
        image=cv2.imread(str(ROOT/'docs/evidence/coop-20260923/dual-battle-guest-1080.png'))
        native=cv2.resize(image,(1440,2560))
        result=self.vision.read(native,'guest')
        self.assertTrue(result.verified);self.assertEqual(result.cells,RIGHT)

    def test_reward_image_not_a_board(self):
        image=cv2.imread(str(ROOT/'docs/evidence/coop-20260923/reward-over-choice.png'))
        for side in ('host','guest'):self.assertFalse(self.vision.read(image,side).verified)

    def test_blank_image_not_a_board(self):
        self.assertFalse(self.vision.read(np.zeros((1920,1080,3),np.uint8),'host').verified)

    def test_wrong_floor_not_battle(self):
        labels=[Label('踏实的龙利鱼',80,70),Label('幽美的竹笋',320,70),Label('第1层',216,60),Label('波次:7',216,86)]
        self.assertEqual(layer(labels,'踏实的龙利鱼','幽美的竹笋',1),'battle')
        self.assertEqual(layer(labels,'踏实的龙利鱼','幽美的竹笋',2),'unknown')
        self.assertEqual(layer(labels+[Label('请选择',216,147),Label('点击空白处关闭',216,628)],'踏实的龙利鱼','幽美的竹笋',1),'reward')


if __name__=='__main__':unittest.main()
