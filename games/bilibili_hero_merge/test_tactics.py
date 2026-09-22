import copy
import unittest
from unittest.mock import Mock,patch
from pathlib import Path
from types import SimpleNamespace
from tactics import compile_tactics,load_tactics,choose_card
from policy import merge_pair,price_action
from tactical import TacticalBot,TacticalReader

ROOT=Path(__file__).parent

class TacticsTests(unittest.TestCase):
    def setUp(self):self.cfg,self.fingerprint=load_tactics(ROOT/'tactics/beginner.json')
    def test_roles_and_slot_order(self):
        self.assertEqual(self.cfg['buff_priority'],['bomb','archer','ice','athena'])
        self.assertTrue(self.cfg['heroes']['archer']['keep_if_space'])
        self.assertEqual(self.cfg['heroes']['ice']['reserve'],2)
    def test_three_support_and_one_damage(self):
        catalog={key:{'name':key,'buff_keywords':[key]} for key in 'abcd'}
        cfg=compile_tactics({'slots':[{'hero':key,'role':'damage' if key=='a' else 'support'} for key in 'abcd']},catalog)
        self.assertEqual(sum(h['keep_if_space'] for h in cfg['heroes'].values()),1)
        self.assertEqual(cfg['heroes']['d']['reserve'],2)
    def test_price_ratio_and_tie(self):
        self.assertEqual(price_action(100,50,self.cfg),'summon')
        self.assertEqual(price_action(100,60,self.cfg),'upgrade')
    def test_protected_carry_does_not_hide_other_merge(self):
        units={0:{'hero':'bomb','tier':1},1:{'hero':'bomb','tier':1},2:{'hero':'archer','tier':1},3:{'hero':'archer','tier':1}}
        self.assertEqual(merge_pair(units,self.cfg,True),(2,3))
        del units[2];del units[3]
        self.assertIsNone(merge_pair(units,self.cfg,True))
    def test_low_tier_control_first_and_unknown_excluded(self):
        units={0:{'hero':'ice','tier':2},1:{'hero':'ice','tier':2},2:{'hero':'ice','tier':1},3:{'hero':'ice','tier':1},4:{'hero':'bomb','tier':0}}
        self.assertEqual(merge_pair(units,self.cfg),(2,3))
    def test_buff_priority_and_within_hero_order(self):
        self.assertEqual(choose_card(['双重炸弹','分裂炸弹','弹簧箭矢'],self.cfg),1)
        self.assertEqual(choose_card(['冰爆冻结','弹簧箭矢','祝福'],self.cfg),1)
        self.assertEqual(choose_card(['未知A','未知B','未知C'],self.cfg),1)
    def test_resume_rejects_wrong_device_stage_tactics_and_settlement(self):
        state={'device':'test','stage':2,'tactics':self.fingerprint,'status':'paused'}
        TacticalBot.validate_resume(state,'test',2,self.fingerprint)
        for changes in [{'device':'other'},{'stage':3},{'tactics':'wrong'},{'status':'settled'}]:
            with self.assertRaises(ValueError):TacticalBot.validate_resume(dict(state,**changes),'test',2,self.fingerprint)
    def test_single_and_repeat_stop_rules(self):
        self.assertFalse(TacticalBot.should_repeat(1,1,False,True,False))
        self.assertTrue(TacticalBot.should_repeat(1,2,False,True,False))
        self.assertTrue(TacticalBot.should_repeat(4,1,True,False,False))
        self.assertFalse(TacticalBot.should_repeat(1,5,False,False,True))
    def test_ninety_requires_two_matching_crops(self):
        reader=TacticalReader.__new__(TacticalReader)
        reader.text=Mock(side_effect=['90','90'])
        with patch('tactical.Reader.prices',return_value=({'money':9,'upgrade':100,'summon':20},{'money':'9'})):
            self.assertEqual(reader.prices(None)[0]['money'],90)
        reader.text=Mock(side_effect=['90',''])
        with patch('tactical.Reader.prices',return_value=({'money':9,'upgrade':100,'summon':20},{'money':'9'})):
            self.assertEqual(reader.prices(None)[0]['money'],9)
    def test_stage_number_allows_ocr_missing_dot(self):
        bot=TacticalBot.__new__(TacticalBot);bot.raw=None;bot.reader=Mock()
        for text,expected in [('1荒原启程',1),('3.异变山谷',3),('为 34.炎山试炼',34),('变强攻略',None)]:
            bot.reader.lines.return_value=text
            self.assertEqual(bot.stage_number(home=True)[0],expected)
    def test_known_unit_details_are_closed_before_stopping(self):
        bot=TacticalBot.__new__(TacticalBot);bot.raw=None;bot.cfg=self.cfg
        bot.reader=Mock();bot.reader.text.return_value='冰法师'
        bot.tap=Mock();bot.log=Mock()
        with patch('tactical.time.sleep'):
            self.assertTrue(bot.close_unit_details())
        bot.tap.assert_called_once_with(15,400)
        bot.tap.reset_mock();bot.reader.text.return_value='未知提示'
        self.assertFalse(bot.close_unit_details());bot.tap.assert_not_called()
    def test_invalid_profile(self):
        with self.assertRaises(ValueError):compile_tactics({'slots':[]},{})
    def test_low_stamina_does_not_click_start(self):
        bot=TacticalBot.__new__(TacticalBot)
        bot.stage=2;bot.raw=None;bot.shot=Mock();bot.home=Mock(return_value=True)
        bot.stage_number=Mock(return_value=(2,'2.野猪沙场'))
        bot.reader=Mock();bot.reader.lines.return_value='';bot.reader.text.return_value='9/60';bot.tap=Mock();bot.log=Mock()
        self.assertFalse(bot.start_home(float('inf')))
        bot.tap.assert_not_called()
    def test_wrong_stage_does_not_start(self):
        bot=TacticalBot.__new__(TacticalBot)
        bot.stage=2;bot.raw=None;bot.reader=Mock();bot.reader.lines.return_value='';bot.shot=Mock();bot.home=Mock(return_value=True)
        bot.stage_number=Mock(return_value=(7,'7.未知'));bot.tap=Mock();bot.log=Mock()
        self.assertFalse(bot.start_home(float('inf')))
        bot.tap.assert_not_called()

if __name__=='__main__':unittest.main()
