"""Regression coverage for stale frames during settlement/home transitions."""
import itertools
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from strategic import StrategicBot

class TransitionTests(unittest.TestCase):
    def bot(self, frames):
        bot=StrategicBot.__new__(StrategicBot)
        bot.args=SimpleNamespace(hide=False,resume=False,until_stamina=False,minutes=10,runs=1)
        bot.cfg={};bot.stage=34;bot.rounds=1;bot.out=Path('unused-test-output')
        bot.raw=None;bot.im=__import__("numpy").zeros((768,432,3),dtype="uint8");bot.pending_action=None
        bot.save=Mock();bot.log=Mock();bot.tap=Mock();bot.pause_stop=Mock()
        bot.reader=Mock();bot.reader.lines.return_value='战斗胜利'
        sequence=iter(frames)
        def shot():bot.frame_kind=next(sequence)
        bot.shot=shot
        bot.home=lambda:bot.frame_kind=='home'
        bot.battle=lambda:bot.frame_kind=='battle'
        bot.has=lambda name,*a: name=='return' and bot.frame_kind=='settlement'
        return bot
    def test_return_tapped_once_despite_delayed_or_flickering_home(self):
        bot=self.bot(['settlement','settlement','home','transition','home','home'])
        with patch('strategic.time.monotonic',side_effect=itertools.count()),patch('strategic.time.sleep'),patch('strategic.cv2.imwrite'),patch('pathlib.Path.exists',return_value=False):
            bot.run()
        bot.tap.assert_called_once_with(215,710)
        self.assertTrue(any(c.args[0]=='return_verified' for c in bot.log.call_args_list))
    def test_start_not_repeated_while_old_home_frame_lingers(self):
        bot=self.bot(['home','home','home','battle'])
        bot.rounds=0;bot.reader.lines.return_value='';bot.reader.text.return_value='151/80'
        bot.decide=Mock(return_value=False)
        with patch('strategic.time.monotonic',side_effect=(x/10 for x in itertools.count())),patch('strategic.time.sleep'),patch('strategic.cv2.imwrite'),patch('pathlib.Path.exists',return_value=False):
            bot.run()
        bot.tap.assert_called_once_with(216,610)
        bot.decide.assert_called_once()

if __name__=='__main__':unittest.main()

