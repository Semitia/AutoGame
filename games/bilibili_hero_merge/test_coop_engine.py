import unittest
from dataclasses import replace
from pathlib import Path
from coop_engine import Engine, Observation
from tactics import load_tactics


class CoOpEngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_tactics(Path(__file__).with_name('tactics')/'veteran.json')[0]
        self.engine = Engine(self.cfg, 'host')
        self.obs = Observation('battle', prices={'upgrade':200,'summon':80,'money':1000},
                               cells={(77,494),(111,494),(146,494)},
                               summon_count=5, board_verified=True)

    def test_ratio_uses_next_prices(self):
        self.assertEqual(self.engine.next(self.obs)['kind'], 'summon')

    def test_free_first_summon(self):
        obs = replace(self.obs, summon_count=0, prices={'upgrade':100,'summon':0,'money':0})
        self.assertEqual(self.engine.next(obs)['kind'], 'summon')

    def test_first_five_summons_override_cheaper_upgrade(self):
        # Upgrade is much cheaper by ratio, but it is still locked at 0..4.
        for count in range(5):
            with self.subTest(count=count):
                obs=replace(self.obs, summon_count=count,
                            prices={'upgrade':100,'summon':80,'money':1000})
                self.assertEqual(Engine(self.cfg,'host').next(obs)['kind'],'summon')

    def test_fifth_confirmed_summon_enables_price_policy(self):
        obs=replace(self.obs, summon_count=5,
                    prices={'upgrade':100,'summon':80,'money':1000})
        self.assertEqual(self.engine.next(obs)['kind'],'upgrade')

    def test_locked_upgrade_not_used_when_summon_unaffordable(self):
        obs=replace(self.obs, summon_count=4,
                    prices={'upgrade':100,'summon':200,'money':150})
        self.assertEqual(self.engine.next(obs)['kind'],'wait')

    def test_reward_blocks_background_purchase(self):
        self.assertEqual(self.engine.next(replace(self.obs,layer='reward'))['kind'], 'close_reward')
        self.assertEqual(self.engine.next(replace(self.obs,layer='choice'))['kind'], 'choose_buff')

    def test_stuck_modal_stops(self):
        obs = replace(self.obs, layer='reward')
        self.engine.next(obs)
        kinds = [self.engine.next(obs)['kind'] for _ in range(4)]
        self.assertEqual(kinds, ['wait','wait','wait','stop'])

    def test_failed_click_never_counted(self):
        self.engine.next(self.obs)
        self.assertEqual([self.engine.next(self.obs)['kind'] for _ in range(4)],
                         ['wait','wait','wait','stop'])

    def test_summon_needs_counter_price_and_new_unit(self):
        self.engine.next(self.obs)
        pos=(77,494)
        after=replace(self.obs, summon_count=6, occupied={pos},
                      units={pos:{'hero':'sea','tier':1}},
                      prices={'upgrade':200,'summon':90,'money':920})
        self.assertEqual(self.engine.next(after), {'kind':'verified','action':'summon'})

    def test_price_alone_not_success(self):
        self.engine.next(self.obs)
        after=replace(self.obs, prices={'upgrade':200,'summon':90,'money':920})
        self.assertEqual(self.engine.next(after)['kind'], 'wait')

    def test_unknown_total_not_assumed_zero(self):
        self.assertEqual(self.engine.next(replace(self.obs,summon_count=None))['kind'],'stop')

    def test_partner_cells_rejected(self):
        self.assertEqual(self.engine.next(replace(self.obs,cells={(285,494)}))['kind'],'stop')

    def test_guest_region(self):
        engine=Engine(self.cfg,'guest')
        self.assertEqual(engine.next(replace(self.obs,cells={(285,494)}))['kind'],'summon')

    def test_unverified_layout_stops(self):
        self.assertEqual(self.engine.next(replace(self.obs,board_verified=False))['kind'],'stop')

    def test_expansion_observation_preserves_new_cell(self):
        obs=replace(self.obs,cells=self.obs.cells|{(111,425)})
        self.assertEqual(self.engine.next(obs)['kind'],'summon')

    def test_support_merge_and_changed_result_hero(self):
        units={p:{'hero':'snow','tier':1} for p in self.obs.cells}
        obs=replace(self.obs,units=units,occupied=set(units))
        action=self.engine.next(obs)
        self.assertEqual(action['kind'],'merge')
        a,b=action['source'],action['target']
        result={p:dict(u) for p,u in units.items() if p!=a}
        result[b]={'hero':'sea','tier':2}
        self.assertEqual(self.engine.next(replace(obs,units=result,occupied=set(result)))['kind'],'verified')

    def test_unknown_tier_never_merged(self):
        units={p:{'hero':'snow','tier':0} for p in self.obs.cells}
        action=self.engine.next(replace(self.obs,units=units,occupied=set(units)))
        self.assertEqual(action['reason'],'full_board_has_unknown_units')

    def test_damage_kept_when_space(self):
        units={p:{'hero':'sea','tier':1} for p in list(self.obs.cells)[:2]}
        self.assertEqual(self.engine.next(replace(self.obs,units=units,occupied=set(units)))['kind'],'summon')

    def test_damage_merged_on_full_board(self):
        units={p:{'hero':'sea','tier':1} for p in self.obs.cells}
        self.assertEqual(self.engine.next(replace(self.obs,units=units,occupied=set(units)))['kind'],'merge')

    def test_upgrade_requires_price_change_after_choice(self):
        obs=replace(self.obs,prices={'upgrade':100,'summon':80,'money':1000})
        self.assertEqual(self.engine.next(obs)['kind'],'upgrade')
        self.assertEqual(self.engine.next(replace(obs,layer='choice'))['kind'],'choose_buff')
        self.assertEqual(self.engine.next(obs)['kind'],'wait')
        self.assertEqual(self.engine.next(replace(obs,prices={'upgrade':200,'summon':80,'money':900}))['kind'],'verified')

    def test_unknown_screen_stops(self):
        self.assertEqual(self.engine.next(replace(self.obs,layer='unknown'))['kind'],'stop')

    def test_settlement_clears_pending(self):
        self.engine.next(self.obs)
        self.assertEqual(self.engine.next(replace(self.obs,layer='settled'))['kind'],'settled')
        self.assertIsNone(self.engine.pending)


if __name__ == '__main__':
    unittest.main()
