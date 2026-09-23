"""Offline prototype regression, not a claim of general skin coverage."""
import json
import unittest
from pathlib import Path
import cv2
from tier_vision import TierVision, TierConsensus, TierEstimate

ROOT=Path(__file__).resolve().parents[2]/'docs/evidence/tier-vision'


class TierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=TierVision()

    def test_development_image_count_and_large_unit(self):
        im=cv2.imread(str(ROOT/'player-example.jpg'))
        group=json.loads((ROOT/'samples.json').read_text())['images'][0]
        for cell in group['cells']:
            with self.subTest(cell=cell):
                self.assertEqual(self.vision.estimate(im,cell['center'],group['pitch']).tier,cell['expected'])

    def test_independent_frame_supported_and_unknown_appearances(self):
        im=cv2.imread(str(ROOT/'independent-battle.png'))
        for center,tier in [((259,560),2),((216,603),1),((302,603),2),((345,603),2),
                            ((87,603),None),((173,560),None),((173,603),None),
                            ((259,603),None),((130,603),None)]:
            with self.subTest(center=center):
                self.assertEqual(self.vision.estimate(im,center,43).tier,tier)

    def test_temporal_evidence_resets_on_uncertainty_or_input(self):
        votes=TierConsensus()
        estimate=TierEstimate(3,'knight',.9,[],'candidate')
        self.assertIsNone(votes.observe((1,1),estimate))
        self.assertIsNone(votes.observe((1,1),estimate))
        self.assertEqual(votes.observe((1,1),estimate),3)
        votes.observe((1,1),TierEstimate(None,None,0,[],'occluded'))
        self.assertIsNone(votes.observe((1,1),estimate))
        votes.clear()
        self.assertIsNone(votes.observe((1,1),estimate))

    def test_clipped_cells_are_not_assigned_tiers(self):
        im=cv2.imread(str(ROOT/'player-example.jpg'))
        self.assertIsNone(self.vision.estimate(im,(1,1),149).tier)
