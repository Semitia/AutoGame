import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from coop import Battle,main
from coop_engine import Observation
from coop_ui import Label,Screen
from coop_replay import replay
from tactics import load_tactics

ROOT=Path(__file__).resolve().parents[2]
PROFILE=Path(__file__).with_name('tactics')/'veteran.json'
CELLS={(111,460)}|{(x,y) for x in (77,111,146) for y in (494,527)}


def make_bot(output):
    args=SimpleNamespace(host_device='host-device',guest_device='guest-device',
                         host_name='踏实的龙利鱼',guest_name='幽美的竹笋',stage=1,
                         host_tactics=PROFILE,guest_tactics=PROFILE,minutes=2,
                         host_state=None,guest_state=None)
    screen=Mock();screen.output=Path(output);screen.raw=np.full((1920,1080,3),100,np.uint8)
    screen.labels=[]
    bot=Battle(screen,'host',args,lambda:False)
    bot.log=Mock();bot.capture=Mock()
    return bot


class CoOpAdapterTests(unittest.TestCase):
    def test_visual_recovery_commits_unknown_ranks_then_reobserves(self):
        pos=(77,494)
        obs=Observation('battle',cells=CELLS,occupied={pos},units={pos:{'hero':'snow','tier':0}},
                        prices={'upgrade':100,'summon':80,'money':300},summon_count=5,board_verified=True)
        self.bot.top=Mock(return_value='battle')
        self.bot.vision.read=Mock(return_value=SimpleNamespace(verified=True,cells=CELLS,occupied={pos}))
        self.bot.tier_rescue=Mock()
        def recover(image,cells,occupied,units,pitch,log):
            self.assertEqual(pitch,34.5)
            units[pos].update(tier=2,tier_source='visual:structure')
            return 1
        self.bot.tier_rescue.recover.side_effect=recover
        with patch('coop.owner_side',return_value='host'):
            self.assertTrue(self.bot.recover_tiers(obs,None))
        self.assertEqual(self.bot.tracker.units[pos]['tier'],2)
        self.bot.s.tap.assert_not_called();self.bot.s.swipe.assert_not_called()
        self.assertIsNone(self.bot.last_board)

    def test_visual_recovery_never_resolves_pending_action(self):
        self.bot.tier_rescue=Mock()
        obs=Observation('battle',units={(77,494):{'hero':'snow','tier':0}})
        self.assertFalse(self.bot.recover_tiers(obs,{'kind':'merge'}))
        self.bot.tier_rescue.recover.assert_not_called()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        recorder=patch('coop.record_cards')
        self.record_cards=recorder.start();self.addCleanup(recorder.stop)
        self.bot=make_bot(self.temp.name)
        self.cfg=load_tactics(PROFILE)[0]

    def test_saved_screenshot_ocr_closes_reward_before_choice(self):
        labels=json.loads((ROOT/'docs/evidence/coop-20260923/reward-over-choice.ocr.json').read_text(encoding='utf8'))
        self.bot.s.labels=[Label(**p) for p in labels]
        self.assertTrue(self.bot.step())
        self.bot.s.tap.assert_called_once_with(216,628)
        self.bot.s.reader.lines.assert_not_called()

    def test_unmatched_cards_do_not_choose_middle(self):
        self.bot.observe=Mock(return_value=Observation('choice'))
        self.bot.s.reader.lines.side_effect=['熊熊烈火','地鼠接龙','雷电分身']
        self.assertFalse(self.bot.step());self.bot.s.tap.assert_not_called()
        self.record_cards.assert_called_once_with(['熊熊烈火','地鼠接龙','雷电分身'], self.bot.cfg)

    def test_native_input_scaling(self):
        screen=Screen.__new__(Screen);screen.platform=Mock();screen.width=1440;screen.height=2560
        screen.tap(216,384);screen.platform.tap.assert_called_once_with(720,1280)
        screen.swipe((77,494),(111,494))
        screen.platform.swipe.assert_called_once_with(257,1647,370,1647,650)

    def test_synthetic_replay(self):
        actions=replay(ROOT/'docs/evidence/coop-20260923/synthetic-replay.jsonl',self.cfg,'host')
        self.assertEqual([a['kind'] for a in actions],['close_reward','choose_buff','summon','verified'])

    def test_missing_device_rejected_before_constructing_device(self):
        with patch('sys.argv',['coop.py']),patch('coop.MuMuPlatform') as platform,patch('sys.stderr'):
            with self.assertRaises(SystemExit):main()
            platform.assert_not_called()

    def test_guest_only_constructs_only_guest(self):
        argv=['coop.py','--battle-only','--only-side','guest','--guest-device','guest-device',
              '--guest-tactics',str(PROFILE),'--runtime',self.temp.name]
        with patch('sys.argv',argv),patch('coop.MuMuPlatform') as platform,patch('coop.Screen'),patch('coop.Battle') as bot,patch('coop.device_lease',return_value=nullcontext()) as lease:
            bot.return_value.side='guest';bot.return_value.run.return_value='settled'
            main()
            platform.assert_called_once_with('guest-device')
            lease.assert_called_once_with('guest-device')

    def test_fresh_purchase_then_reward_then_verified_summon(self):
        empty=Observation('battle',prices={'upgrade':100,'summon':0,'money':0},cells=CELLS,board_verified=True)
        self.bot.observe=Mock(return_value=empty)
        self.bot.step();self.bot.s.tap.assert_not_called()
        self.bot.step();self.bot.s.tap.assert_called_once_with(290,741)
        self.assertEqual(self.bot.tracker.summons,0)
        self.bot.observe.return_value=Observation('reward',token='coins')
        self.bot.step()
        self.bot.observe.return_value=Observation('battle',prices={'upgrade':100,'summon':10,'money':400},
                                                 cells=CELLS,occupied={(77,494)},board_verified=True)
        self.bot.identify=Mock(return_value='sea')
        self.bot.step();self.bot.step()
        self.assertEqual(self.bot.tracker.summons,1)
        self.assertEqual(self.bot.tracker.units[(77,494)],{'hero':'sea','tier':1})
        self.assertIsNone(self.bot.engine.pending)
        state=json.loads(self.bot.state_path.read_text(encoding='utf8'))
        self.assertEqual(state['tracker']['summons'],1)
        self.assertIsNone(state['pending'])

    def test_stale_empty_board_not_new_run(self):
        self.bot.observe=Mock(return_value=Observation('battle',prices={'upgrade':600,'summon':190,'money':3800},cells=CELLS,board_verified=True))
        self.bot.step()
        with self.assertRaisesRegex(ValueError,'free summon'):self.bot.step()
        self.bot.s.tap.assert_not_called()

    def test_merge_execute_and_changed_hero_confirmed(self):
        units={(77,494):{'hero':'snow','tier':1},(111,494):{'hero':'snow','tier':1},(146,494):{'hero':'snow','tier':1}}
        self.bot.tracker.units=units;self.bot.tracker.summons=5;self.bot.tracker.cells=CELLS
        obs=Observation('battle',prices={'upgrade':200,'summon':80,'money':900},cells=CELLS,occupied=set(units),board_verified=True)
        self.bot.observe=Mock(return_value=obs)
        self.bot.step();self.bot.step()
        self.bot.s.swipe.assert_called_once()
        p=self.bot.engine.pending
        after=Observation('battle',prices=obs.prices,cells=CELLS,occupied=set(units)-{p['a']},board_verified=True)
        self.bot.observe.return_value=after;self.bot.identify=Mock(return_value='sea')
        self.bot.step();self.bot.step()
        self.assertEqual(self.bot.tracker.units[p['b']],{'hero':'sea','tier':2})
        self.assertNotIn(p['a'],self.bot.tracker.units)

    def test_checkpoint_write_failure_prevents_click(self):
        self.bot.observe=Mock(return_value=Observation('reward'))
        self.bot.save=Mock(side_effect=OSError('disk full'))
        with self.assertRaises(OSError):self.bot.step()
        self.bot.s.tap.assert_not_called()

    def test_unknown_screen_times_out_without_inputs(self):
        self.bot.observe=Mock(return_value=Observation('unknown'))
        self.bot.invalid_since=0
        with patch('coop.time.monotonic',return_value=30):self.assertFalse(self.bot.step())
        self.bot.s.tap.assert_not_called();self.bot.s.swipe.assert_not_called()

    def test_inspection_modal_does_not_get_closed_as_detail(self):
        self.bot.last_obs=Observation('battle',occupied={(77,494)})
        self.bot.top=Mock(return_value='reward');self.bot.s.reader.text.return_value='海王'
        with patch('coop.time.sleep'),self.assertRaisesRegex(RuntimeError,'Foreground changed'):
            self.bot.identify((77,494))
        self.bot.s.tap.assert_called_once_with(77,494)

    def test_complete_five_summons_upgrade_choice_and_settlement(self):
        positions=sorted(CELLS)
        occupied=set()
        self.bot.identify=Mock(return_value='sea')
        self.bot.observe=Mock()
        for count in range(6):
            self.bot.observe.return_value=Observation('battle',
                prices={'upgrade':100,'summon':count*20,'money':2000},
                cells=CELLS,occupied=set(occupied),board_verified=True)
            self.bot.step();self.bot.step()
            if count>0:
                self.assertEqual(self.bot.tracker.summons,count)
                self.bot.step()  # choose the next action from the verified state
            if count<5:
                self.assertEqual(self.bot.engine.pending['kind'],'summon')
                occupied.add(positions[count])
            else:
                self.assertEqual(self.bot.engine.pending['kind'],'upgrade')
        self.assertEqual([c.args for c in self.bot.s.tap.call_args_list],
                         [(290,741)]*5+[(153,741)])
        self.bot.observe.return_value=Observation('choice',token='sea-card')
        self.bot.s.reader.lines.side_effect=['海王强化','剑圣强化','雪姬强化']
        self.bot.step()
        self.bot.observe.return_value=Observation('battle',
            prices={'upgrade':200,'summon':100,'money':1900},cells=CELLS,
            occupied=set(occupied),board_verified=True)
        self.bot.step();self.bot.step()
        self.assertIsNone(self.bot.engine.pending)
        self.bot.observe.return_value=Observation('settled')
        self.assertFalse(self.bot.step())
        self.assertEqual(self.bot.status,'settled')
        # The actual worker observations are accepted by the offline replay CLI.
        actions=replay(Path(self.temp.name)/'observations.jsonl',self.cfg,'host')
        self.assertEqual(actions[-1]['kind'],'settled')

    def test_auto_setup_starts_once_and_runs_both_workers(self):
        argv=['coop.py','--host-device','h','--guest-device','g',
              '--host-tactics',str(PROFILE),'--guest-tactics',str(PROFILE),
              '--runtime',self.temp.name]
        host,guest=Mock(),Mock()
        host.room.return_value=guest.room.return_value=True
        button=object();host.find.return_value=button
        with patch('sys.argv',argv),patch('coop.MuMuPlatform'),patch('coop.Screen',side_effect=[host,guest]),patch('coop.Battle') as bot,patch('coop.device_lease',return_value=nullcontext()),patch('coop.setup_pair') as setup,patch('coop.time.sleep'):
            bot.return_value.run.return_value='settled'
            main()
            setup.assert_called_once()
            host.click.assert_called_once_with(button)
            guest.click.assert_not_called()
            self.assertEqual(bot.return_value.run.call_count,2)

    def test_inspect_image_never_constructs_platform(self):
        argv=['coop.py','--inspect-image',str(ROOT/'docs/evidence/coop-20260923/dual-battle-host-1080.png'),'--runtime',self.temp.name]
        with patch('sys.argv',argv),patch('coop.MuMuPlatform') as platform,patch('builtins.print'):
            main();platform.assert_not_called()
        self.assertTrue((Path(self.temp.name)/'host-board.png').exists())


if __name__=='__main__':unittest.main()
