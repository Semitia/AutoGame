import json,unittest
from pathlib import Path
from policy import price_action,merge_pair
CFG=json.loads(Path(__file__).with_name('strategy.json').read_text(encoding='utf8'))
class PolicyTests(unittest.TestCase):
 def test_next_prices_not_total_spend(self):
  self.assertEqual(price_action(100,10,CFG),'summon')
  self.assertEqual(price_action(100,60,CFG),'upgrade')
  self.assertEqual(price_action(100,50,CFG),'summon')
 def test_keep_damage_when_space_exists(self):
  u={0:{'hero':'sea','tier':1},1:{'hero':'sea','tier':1}}
  self.assertIsNone(merge_pair(u,CFG));self.assertEqual(merge_pair(u,CFG,True),(0,1))
 def test_two_support_units_are_preserved(self):
  u={0:{'hero':'snow','tier':1},1:{'hero':'snow','tier':1}}
  self.assertIsNone(merge_pair(u,CFG))
  self.assertIsNone(merge_pair(u,CFG,True))
  u[2]={'hero':'snow','tier':2}
  self.assertEqual(merge_pair(u,CFG),(0,1))
 def test_low_tier_first(self):
  u={0:{'hero':'snow','tier':2},1:{'hero':'snow','tier':2},2:{'hero':'snow','tier':1},3:{'hero':'snow','tier':1}}
  self.assertEqual(merge_pair(u,CFG),(2,3))
 def test_never_merge_different_roles_or_ranks_or_max_rank(self):
  u={0:{'hero':'snow','tier':1},1:{'hero':'sea','tier':1},2:{'hero':'snow','tier':2},3:{'hero':'sea','tier':4},4:{'hero':'sea','tier':4}}
  self.assertIsNone(merge_pair(u,CFG,True))
 def test_full_board_preserves_control_and_uses_damage(self):
  u={0:{'hero':'snow','tier':1},1:{'hero':'snow','tier':1},2:{'hero':'sea','tier':2},3:{'hero':'sea','tier':2}}
  self.assertEqual(merge_pair(u,CFG,True),(2,3))
 def test_blocked_pair_does_not_hide_alternatives(self):
  u={0:{'hero':'sword','tier':1},1:{'hero':'sword','tier':1},2:{'hero':'sword','tier':1}}
  self.assertEqual(merge_pair(u,CFG,True,[(0,1)]),(0,2))
if __name__=='__main__':unittest.main()
