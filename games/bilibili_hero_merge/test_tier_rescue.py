import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from tier_rescue import TierRescue
from tier_structure import StructureEvidence
from tier_vision import TierEstimate
from tactical import TacticalBot


class RescueTests(unittest.TestCase):
    def test_only_unknown_identified_ranks_are_recovered_and_can_merge(self):
        from policy import merge_pair
        bot=TierRescue();bot.structure=Mock();bot.templates=Mock()
        a,b,c=(50,100),(100,100),(150,100)
        units={a:{'hero':'x','tier':0},b:{'hero':'x','tier':2},c:{'hero':'x','tier':0,'uncertain':True}}
        bot.structure.estimate_board.return_value=[StructureEvidence(True,2,'pair')]*3
        log=Mock()
        self.assertEqual(bot.recover(np.zeros((200,200,3),np.uint8),set(units),set(units),units,43,log),1)
        self.assertEqual(units[a]['tier_source'],'visual:structure')
        self.assertNotIn('tier_source',units[b]);self.assertEqual(units[c]['tier'],0)
        bot.templates.estimate.assert_not_called()
        cfg={'buff_priority':['x'],'max_tier':4,
             'heroes':{'x':{'keep_if_space':False,'reserve':1,'min_remaining':0}}}
        self.assertEqual(set(merge_pair(units,cfg)),{a,b})

    def test_template_fallback_and_unknown_are_distinct(self):
        bot=TierRescue();bot.structure=Mock();bot.templates=Mock()
        bot.structure.estimate_board.return_value=[StructureEvidence(True,None,'ambiguous')]
        bot.templates.estimate.return_value=TierEstimate(4,'hat',.8,[],'candidate')
        units={(50,100):{'hero':'x','tier':0}}
        image=np.zeros((200,200,3),np.uint8)
        self.assertEqual(bot.recover(image,set(units),set(units),units,43,Mock()),1)
        self.assertEqual(units[(50,100)]['tier'],4)
        units[(50,100)]={'hero':'x','tier':0}
        bot.templates.estimate.return_value=TierEstimate(None,None,0,[],'unknown')
        self.assertEqual(bot.recover(image,set(units),set(units),units,43,Mock()),0)
        self.assertEqual(units[(50,100)]['tier'],0)

    def test_single_player_skips_pending_and_refreshes_after_recovery(self):
        bot=TacticalBot.__new__(TacticalBot)
        bot.args=SimpleNamespace();bot.pending_action={'kind':'merge'}
        bot.tier_rescue=Mock();bot.units={(50,100):{'hero':'x','tier':0}}
        bot.recover_tiers();bot.tier_rescue.recover.assert_not_called()
        bot.pending_action=None;bot.last_tier_rescue=-1000
        bot.available=set(bot.units);bot.occupied=Mock(return_value=True)
        bot.im=np.zeros((200,200,3),np.uint8);bot.log=Mock();bot.save=Mock();bot.shot=Mock()
        bot.tier_rescue.recover.return_value=1
        self.assertTrue(bot.recover_tiers());bot.save.assert_called_once();bot.shot.assert_called_once()
        bot.recover_tiers();bot.tier_rescue.recover.assert_called_once()


if __name__=='__main__':unittest.main()
