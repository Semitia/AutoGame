import copy
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest

from combat import outcome_score
from experience import Experience,context_for,stable_hash
from tactics import Tactics,BASE_WEIGHTS,stage_profile
from test_workbench import catalog,stage


def fixture():
    c=catalog();c.name=lambda uid,evo=1:str(uid)
    s=stage();s['stage']=dict(ID=1,DisplayName='1-1')
    s['waves']['Frame']['8']['Waves']['1']['Cols']={'1':1,'2':2}
    sim=SimpleNamespace(catalog=c,rows={i:dict(tid=i,gs=100,evoTID=1) for i in (1,2,3)},
                        pet_facts={},engine_fingerprint='engine-A')
    return sim,s,Tactics(sim,s)


def outcome(kills,seed=123,won=False,seconds=20):
    row=dict(won=won,kills=kills,total_enemies=10,battle_secs=seconds,seed=seed)
    return dict(row,score=outcome_score(row))


class TacticalTests(unittest.TestCase):
    def test_wave_counts_are_not_duplicated_for_each_column(self):
        sim,s,t=fixture();p=stage_profile(s)
        self.assertEqual(p['total'],3)
        self.assertEqual(sum(sum(v.values()) for v in p['lanes'].values()),3)
        self.assertEqual(p['lanes'][1][3],1.5)

    def test_actual_range_and_toughness_matter_more_than_career(self):
        sim,s,t=fixture()
        sim.catalog.pets['1'].update(UnitCareer=5,PositionType='Back')
        sim.catalog.pets['2'].update(UnitCareer=1,PositionType='Front')
        sim.pet_facts.update({1:dict(hp=1000,defense=100,range_grids=[(0,1)]),
                              2:dict(hp=50,defense=1,range_grids=[(0,9)])})
        t=Tactics(sim,s)
        self.assertGreater(t.front_fit(1),t.front_fit(2))

    def test_counter_alignment_responds_to_lane_elements(self):
        sim,s,t=fixture();sim.catalog.pets['1']['CounterElement']={'1':3}
        sim.catalog.pets['2']['CounterElement']={'1':4}
        self.assertGreater(t.counter(1,1),t.counter(2,1))

    def test_tactical_seeds_mutations_and_case_repair_are_legal(self):
        sim,s,t=fixture();rng=random.Random(19);slots=set(t.slots)
        for plan in [t.seed(rng,i) for i in range(10)]+[p for p,_,_ in t.community_seeds()]:
            for _ in range(50):
                plan,_=t.mutate(plan,rng)
                self.assertEqual(len(plan),t.count)
                self.assertEqual(len({p['unit_id'] for p in plan}),t.count)
                self.assertEqual(len({(p['x'],p['y']) for p in plan}),t.count)
                self.assertTrue(all((p['x'],p['y']) in slots for p in plan))
        repaired=t.repair([dict(unit_id=9999,x=99,y=99)])
        self.assertEqual(len(repaired),t.count)
        self.assertTrue(all(p['unit_id'] in t.ids for p in repaired))

    def test_kills_dominate_damage_and_victory_speed_has_right_sign(self):
        a=outcome(4);b=outcome(3);b['damage']=10**20
        self.assertGreater(outcome_score(a),outcome_score(b))
        self.assertGreater(outcome_score(outcome(10,won=True,seconds=50)),outcome_score(outcome(10,won=True,seconds=100)))
        b.update(total_enemies=10000,kills=9999)
        self.assertGreater(outcome_score(outcome(1,won=True)),outcome_score(b))


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'experience.sqlite3'
        self.memory=Experience(self.path);self.sim,self.stage,self.tactics=fixture()
        self.context=context_for(self.sim,self.stage,self.tactics)
        self.plans=[[dict(unit_id=uid,x=x,y=2) for uid,x in ((1,1),(2,2))],
                    [dict(unit_id=uid,x=x,y=2) for uid,x in ((1,2),(2,1))]]

    def tearDown(self):self.memory.close();self.directory.cleanup()

    def record(self,index,kills,seed=123,context=None,engine='engine-A'):
        return self.memory.record(engine,context or self.context,self.plans[index],
            dict(counter=float(index)),outcome(kills,seed))

    def test_controlled_preferences_change_next_run_weights_and_deduplicate(self):
        a=self.record(0,3);b=self.record(1,8);before=self.memory.weights('engine-A')[0]['counter']
        self.assertTrue(self.memory.learn('engine-A',a,b))
        self.assertFalse(self.memory.learn('engine-A',b,a))
        self.memory.close();self.memory=Experience(self.path)
        self.assertGreater(self.memory.weights('engine-A')[0]['counter'],before)
        self.assertEqual(self.memory.weights('engine-A')[1],1)
        self.assertEqual(self.memory.weights('engine-B'),(BASE_WEIGHTS,0))
        self.assertEqual(self.record(1,8),b)

    def test_cross_context_or_seed_comparison_is_rejected(self):
        a=self.record(0,3);b=self.record(1,8,seed=456)
        with self.assertRaises(ValueError):self.memory.learn('engine-A',a,b)
        changed=dict(self.context,roster_hash='different-roster')
        b=self.record(1,8,context=changed)
        with self.assertRaises(ValueError):self.memory.learn('engine-A',a,b)

    def test_successful_cases_transfer_to_nearby_stages_and_version_isolation(self):
        self.record(1,10)
        context=dict(self.context,stage_id=2,stage_hash='next-stage')
        retrieved=self.memory.retrieve('engine-A',context)
        self.assertEqual(retrieved[0]['placements'],self.plans[1])
        self.assertFalse(retrieved[0]['exact_stage'])
        self.assertEqual(self.memory.retrieve('engine-B',context),[])

    def test_user_reports_remain_separate_and_do_not_train_simulated_preferences(self):
        self.record(0,10);self.memory.record_feedback('engine-A',stable_hash(self.context),self.plans[0],False)
        result=self.memory.retrieve('engine-A',self.context)[0]
        self.assertIs(result['user_report'],False)
        self.assertEqual(result['source'],'simulation')
        self.assertEqual(self.memory.stats('engine-A')['preference_updates'],0)
        self.assertEqual(self.memory.stats('engine-A')['user_reports'],1)
        changed=dict(self.context,roster_hash='new-growth')
        self.assertIsNone(self.memory.retrieve('engine-A',changed)[0]['user_report'])

    def test_capture_time_does_not_invalidate_identical_roster(self):
        self.sim.rows[1]['captured_at']='new timestamp'
        self.assertEqual(context_for(self.sim,self.stage,self.tactics)['roster_hash'],self.context['roster_hash'])

    def test_observed_results_are_not_relabelled_as_player_reports(self):
        self.record(0,10)
        self.memory.record_feedback('engine-A',stable_hash(self.context),self.plans[0],True,source='live_observation')
        item=self.memory.retrieve('engine-A',self.context)[0]
        self.assertIsNone(item['user_report']);self.assertIs(item['live_observation'],True)
        stats=self.memory.stats('engine-A')
        self.assertEqual(stats['live_observations'],1);self.assertEqual(stats['user_reports'],0)
        self.assertEqual(stats['preference_updates'],0)

    def test_battle_cache_distinguishes_input_order_of_same_formation(self):
        from experience import plan_key,formation_key
        first=self.plans[0];second=list(reversed(first))
        self.assertNotEqual(plan_key(first),plan_key(second))
        self.assertEqual(formation_key(first),formation_key(second))
        a=self.memory.record('engine-A',self.context,first,{},outcome(3))
        b=self.memory.record('engine-A',self.context,second,{},outcome(10))
        self.assertNotEqual(a,b)
        self.assertEqual(self.memory.stats('engine-A')['battles'],2)


if __name__=='__main__':unittest.main()
