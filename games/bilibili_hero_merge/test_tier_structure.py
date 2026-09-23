"""Regression fixtures used during development, not held-out accuracy claims."""
import json
import unittest
from pathlib import Path
import cv2
import numpy as np
from tier_structure import StructureVision,cell_crop

ROOT=Path(__file__).resolve().parents[2]/'docs/evidence/tier-vision'


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.vision=StructureVision()
        self.groups=json.loads((ROOT/'samples.json').read_text(encoding='utf8'))['images']

    def board(self,index):
        group=self.groups[index]
        image=cv2.imread(str(ROOT/group['file']))
        empty=cell_crop(image,group['empty_center'],group['pitch'])
        return group,image,empty

    def test_battle_occupancy_and_conservative_layout_veto(self):
        group,image,empty=self.board(1)
        results=self.vision.estimate_board(image,[c['center'] for c in group['cells']],group['pitch'],empty)
        for cell,result in zip(group['cells'],results):
            with self.subTest(cell=cell):
                if cell['center']==[345,603]:
                    # Different cells' animation/scale is not guaranteed to
                    # align: this true pair currently becomes ambiguous.
                    self.assertIsNone(result.tier)
                    self.assertEqual(result.reason,'lowered_pair_possible_occluded_third')
                else:self.assertEqual(result.tier,cell['expected'])
                self.assertEqual(result.occupied,cell['expected'] is not None)

    def test_repetition_calibrates_singles_but_large_hero_stays_unknown(self):
        group,image,empty=self.board(0)
        results=self.vision.estimate_board(image,[c['center'] for c in group['cells']],group['pitch'],empty)
        for cell,result in zip(group['cells'],results):
            with self.subTest(cell=cell):
                self.assertTrue(result.occupied)
                self.assertEqual(result.tier,None if cell['expected']==4 else cell['expected'])

    def test_uniform_brightness_change_is_not_a_unit(self):
        group,image,empty=self.board(1)
        bright=np.clip(image.astype(np.int16)+12,0,255).astype(np.uint8)
        result=self.vision.estimate(bright,group['empty_center'],group['pitch'],empty)
        self.assertIs(result.occupied,False)
        self.assertIsNone(result.tier)

    def test_missing_background_or_clipped_cell_cannot_claim_occupancy(self):
        group,image,empty=self.board(1)
        self.assertIsNone(self.vision.estimate(image,(87,603),43,None).occupied)
        self.assertIsNone(self.vision.estimate(image,(1,1),43,empty).occupied)

    def test_occluded_back_unit_is_an_unresolved_failure_case(self):
        group,image,empty=self.board(0)
        image[150:216,716:801]=(150,150,150)
        # Records a known limitation explicitly. This output is advisory only.
        result=self.vision.estimate(image,(761,271),149,empty)
        self.assertEqual(result.tier,2)

    def test_board_layout_rejects_occluded_three_as_two(self):
        group,image,empty=self.board(0)
        image[150:216,716:801]=(150,150,150)
        results=self.vision.estimate_board(image,[c['center'] for c in group['cells']],149,empty)
        result=results[4]
        self.assertIsNone(result.tier)
        self.assertEqual(result.reason,'lowered_pair_possible_occluded_third')
        self.assertGreaterEqual(result.layout_shift,6/96)


if __name__=='__main__':unittest.main()
