import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from strategic import StrategicBot, ROOT
from policy import merge_pair

class RecoveryTests(unittest.TestCase):
 def bot(self):
  b=StrategicBot.__new__(StrategicBot)
  b.args=SimpleNamespace(until_stamina=True)
  b.units={};b.available={(87,603)};b.pending_action=None
  b.repair_due={};b.last_repair=0;b.repair_mode=True;b.templates={'tile_frame':None};b.im=None
  b.save=Mock();b.log=Mock();b.shot=Mock();b.battle=Mock(return_value=True)
  b.identify=Mock(return_value='sea');b.occupied=Mock(return_value=True)
  return b
 def test_failure_keeps_other_units_usable(self):
  b=self.bot();b.units={(1,1):{'hero':'sea','tier':1},(2,2):{'hero':'sea','tier':1},(3,3):{'hero':'sword','tier':2}}
  b.pending_action={'kind':'merge','a':[1,1],'b':[2,2]}
  self.assertTrue(b.recover_battle('test'))
  self.assertTrue(b.units[(1,1)]['uncertain'])
  self.assertNotIn('uncertain',b.units[(3,3)])
  self.assertIsNone(b.pending_action)
 def test_repair_is_incremental_and_does_not_guess_tier(self):
  b=self.bot()
  with patch('strategic.tile_scores',return_value=[]),patch('strategic.time.monotonic',return_value=100):
   self.assertTrue(b.repair_one())
   self.assertFalse(b.repair_one())
  self.assertEqual(b.identify.call_count,1)
  self.assertEqual(b.units[(87,603)],{'hero':'sea','tier':0})
 def test_unknown_and_uncertain_units_are_not_merged(self):
  cfg=json.loads((ROOT/'strategy.json').read_text(encoding='utf8'))
  for unit in ({'hero':'sea','tier':0},{'hero':'sea','tier':1,'uncertain':True}):
   self.assertIsNone(merge_pair({(1,1):unit,(2,2):unit},cfg,True))
  units={(1,1):{'hero':'sea','tier':0},(2,2):{'hero':'sword','tier':1},(3,3):{'hero':'sword','tier':1}}
  self.assertEqual(merge_pair(units,cfg,True),((2,2),(3,3)))
 def test_state_save_retries_transient_file_lock(self):
  b=self.bot();b.state_path=Mock();b.summons=8;b.rounds=7
  tmp=b.state_path.with_suffix.return_value
  tmp.replace.side_effect=[PermissionError('locked'),None]
  with patch('strategic.time.sleep'):
   self.assertTrue(StrategicBot.save(b))
  self.assertEqual(tmp.replace.call_count,2)
  self.assertFalse(b.save_pending)
 def test_state_save_failure_keeps_state_and_recovers_later(self):
  b=self.bot();b.state_path=Mock();b.summons=8;b.rounds=7
  b.units={(87,603):{'hero':'sword','tier':2}}
  tmp=b.state_path.with_suffix.return_value;tmp.replace.side_effect=PermissionError('locked')
  with patch('strategic.time.sleep'):
   self.assertFalse(StrategicBot.save(b))
  self.assertTrue(b.save_pending)
  self.assertEqual(b.units[(87,603)]['tier'],2)
  tmp.replace.side_effect=None
  self.assertTrue(StrategicBot.save(b))
  self.assertFalse(b.save_pending)

if __name__=='__main__':unittest.main()
