"""Synthetic state-machine tests. No window queries or input."""
import copy
import unittest
from hunt_policy import Options,Policy,token
from hunt_config import room_for


def enemy(id=77,tid=2008,spawn=10,active=True,score=1500):
    return dict(id=id,tid=tid,spawn_time=spawn,exit_time=100,active=active,score=score)


def room(multiplier=200,locks=10,enemies=None,locked=False):
    return dict(screen='room',account_key='synthetic-account',room_token=[101,1234,room_for(multiplier)['id']],
        multiplier=multiplier,locks=locks,rage=1,bullets=1000000,total_bullets=100000000,
        lock_active=locked,rage_active=False,lock_target=77 if locked else 0,enemies=enemies or [])


def lobby(locks=10):
    return dict(screen='lobby',account_key='synthetic-account',locks=locks,rage=1,bullets=1000000,total_bullets=100000000,
                selected_dungeon=1,dungeons=list(range(1,11)),switching=False)


class PolicyTests(unittest.TestCase):
    def test_low_room_uses_rage_and_fires_without_spending_locks(self):
        p=Policy(Options());state=room(1,locks=0)
        self.assertEqual(p.decide(state)['kind'],'rage')
        state['rage_active']=True;self.assertEqual(p.decide(state)['kind'],'fire')
        p=Policy(Options(use_rage=False));self.assertEqual(p.decide(room(1,0))['kind'],'fire')

    def test_stock_threshold_exits_low_and_selects_200(self):
        p=Policy(Options(stock=3));self.assertEqual(p.decide(room(1,2))['kind'],'rage')
        self.assertEqual(p.decide(room(1,3))['kind'],'exit')
        state=lobby(3);self.assertEqual(p.decide(state)['kind'],'next')
        state['selected_dungeon']=8;self.assertEqual(p.decide(state),dict(kind='enter',dungeon=8))

    def test_high_room_is_idle_until_active_highest_score_shaman(self):
        p=Policy(Options())
        for enemies in ([],[enemy(tid=2007,score=1000)],[enemy(active=False)]):
            self.assertEqual(p.decide(room(enemies=enemies))['kind'],'wait')
        self.assertEqual(p.decide(room(enemies=[enemy()]))['kind'],'lock')

    def test_last_lock_acknowledgement_is_not_mistaken_for_empty_inventory(self):
        p=Policy(Options());p.mode='hunt';p.pending=True
        state=room(locks=0,enemies=[enemy()])
        self.assertEqual(p.decide(state)['kind'],'wait');self.assertEqual(p.mode,'hunt')
        state.update(lock_active=True,lock_target=77)
        self.assertEqual(p.decide(state)['kind'],'wait');self.assertEqual(p.target,token(enemy()))

    def test_existing_last_lock_can_be_adopted_without_using_another_item(self):
        p=Policy(Options());s=room(locks=0,enemies=[enemy()],locked=True)
        self.assertEqual(p.decide(s)['kind'],'wait');self.assertIsNotNone(p.target)

    def test_portrait_disappearance_is_not_death_body_can_remain_active(self):
        p=Policy(Options());s=room(enemies=[enemy()],locked=True)
        p.decide(s);s['edge_portrait_visible']=False
        self.assertEqual(p.decide(s)['kind'],'wait')

    def test_any_killer_or_natural_departure_exits_and_does_not_wait_for_loot(self):
        for reason in ('self-kill','other-kill','escaped'):
            p=Policy(Options());s=room(enemies=[enemy()],locked=True);p.decide(s)
            s['enemies']=[];s['reason']=reason
            action=p.decide(s);self.assertEqual(action['kind'],'exit');self.assertTrue(action['completed'])
            p.exited(action);self.assertEqual(p.completed,1)

    def test_recycled_instance_number_is_not_the_same_spawn(self):
        p=Policy(Options());s=room(enemies=[enemy()],locked=True);p.decide(s)
        s['enemies']=[enemy(spawn=11)]
        self.assertEqual(p.decide(s)['kind'],'exit')

    def test_game_retarget_or_lock_expiry_exits_without_claiming_a_kill(self):
        for update in (dict(lock_target=55),dict(lock_active=False)):
            p=Policy(Options());s=room(enemies=[enemy()],locked=True);p.decide(s);s.update(update)
            action=p.decide(s);self.assertEqual(action['kind'],'exit');self.assertFalse(action.get('completed',False))

    def test_reserve_also_stops_game_managed_locked_fire(self):
        p=Policy(Options(reserve=1000));s=room(enemies=[enemy()],locked=True);p.decide(s)
        s['bullets']=1100
        self.assertTrue(p.decide(s)['finish'])

    def test_entry_requires_unlock_and_actual_entry_balance(self):
        for change in (dict(total_bullets=0),dict(bullets=89999)):
            p=Policy(Options());s=lobby();s.update(change)
            with self.assertRaises(ValueError):p.decide(s)

    def test_empty_locks_refill_and_unknown_room_is_exited(self):
        p=Policy(Options());s=room(200,0)
        self.assertEqual(p.decide(s)['kind'],'exit');self.assertEqual(p.mode,'farm')
        self.assertEqual(p.decide(room(100,0))['kind'],'exit')

    def test_options_and_unexpected_reward_page_fail_without_input(self):
        for option in (Options(stock=0),Options(low_multiplier=200),Options(seconds=float('nan')),Options(reserve=-1)):
            with self.assertRaises(ValueError):option.validate()
        with self.assertRaises(ValueError):Policy(Options()).decide(dict(lobby(),screen='reward'))
