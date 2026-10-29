"""Combat integration uses local extracted bytecode and an ignored player capture."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from model import Catalog, RUNTIME, read_json
from headless import SOURCE
from combat import Simulator, pet_proto
from policy import recommend, slots_for
from search_policy import search
from test_workbench import catalog,stage


class SearchTests(unittest.TestCase):
    def test_search_keeps_legal_plans_and_validates_on_other_seeds(self):
        c=catalog();c.stages=[]
        c.name=lambda uid,evo=1:str(uid)
        s=stage();s['stage']=dict(ID=1,DisplayName='1-1')
        class Oracle:
            catalog=c
            rows={i:dict(gs=i*100) for i in (1,2,3)}
            roster=dict(pets=[dict(unit_id=i,evolution=1) for i in (1,2,3)])
            capture={'captured_at':'2026-10-28T00:00:00+00:00'}
            attribute_validation={'matched':3}
            def __init__(self):self.seeds=[]
            def evaluate(self,stage,placements,seed,trace=False):
                self.seeds.append(seed)
                self_ids=[p['unit_id'] for p in placements]
                assert len(self_ids)==len(set(self_ids))==2
                assert len({(p['x'],p['y']) for p in placements})==2
                assert all((p['x'],p['y']) in slots_for(stage) for p in placements)
                score=sum(self_ids)+sum(p['x'] for p in placements if p['unit_id']==3)
                return dict(score=score,won=score>=8,kills=score,total_enemies=10,battle_secs=5,seed=seed)
        oracle=Oracle();result=search(oracle,s,budget=12,review_mode='full')
        self.assertEqual(result['evaluated'],12)
        self.assertEqual(set(oracle.seeds),{123456,701,2029,8191})
        self.assertFalse(result['calibrated'])
        self.assertEqual(len(result['finalists']),3)

    def test_missing_exact_growth_data_requires_sync(self):
        with self.assertRaisesRegex(ValueError,'重新从游戏同步'):pet_proto(dict(tid=1))


@unittest.skipUnless((SOURCE/'Src/game_battle.luae').exists() and (RUNTIME/'combat-capture.json').exists(),
                     'Local bytecode and private combat capture required')
class OriginalCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog();cls.stage=cls.catalog.stage(826)
        cls.sim=Simulator(read_json(RUNTIME/'combat-capture.json'),cls.catalog)
        cls.plan=recommend(cls.catalog,cls.stage,cls.sim.roster['pets'])[0]['placements']

    def test_all_observed_attributes_match(self):
        v=self.sim.attribute_validation
        self.assertEqual(v['matched'],v['checked'])
        self.assertFalse(v['mismatches'])

    def test_deterministic_reset_and_actual_combat(self):
        first=self.sim.evaluate(self.stage,self.plan,701)
        self.sim.evaluate(self.stage,self.plan,8191)
        again=self.sim.evaluate(self.stage,self.plan,701)
        for key in ('result','kills','damage','battle_secs','survivors'):
            self.assertEqual(first[key],again[key],key)
        self.assertGreater(first['damage'],0)
        self.assertGreater(first['kills'],0)
        self.assertIn(first['result'],(1,2,3))

    def test_replay_trace_and_illegal_deployment(self):
        result=self.sim.evaluate(self.stage,self.plan,701,trace=True)
        frames=result['frames'];times=[f['time'] for f in frames]
        self.assertEqual(times[0],0)
        self.assertEqual(times[-1],result['battle_secs'])
        self.assertEqual(times,sorted(set(times)))
        self.assertEqual(len([u for u in frames[0]['units'] if u['camp']==1]),15)
        with self.assertRaises(ValueError):self.sim.evaluate(self.stage,[self.plan[0],self.plan[0]])
        with self.assertRaises(ValueError):self.sim.evaluate(self.stage,[dict(unit_id=99999,x=1,y=1)])


if __name__=='__main__':unittest.main()
