import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from model import load_roster, snapshot, validate_pet, write_json
from formation import move_unit
from policy import recommend, slots_for


def catalog():
    units = {str(i): dict(UnitType=1, Enable=True, UnitElement=i+1, UnitQuality=i,
                         CanDeployNum=1, CounterElement={'1': 3}, WeakElement={}) for i in (1, 2, 3)}
    result = SimpleNamespace(pets=units, evolutions={str(i): {'1': {'UnitQuality': i}} for i in (1, 2, 3)})
    result.quality = lambda p: result.evolutions[str(p['unit_id'])][str(p['evolution'])]['UnitQuality']
    result.max_star=84;result.evolution_trials={}
    result.feed_ranks={'1':dict(RankID=1,RankName='E',ATKPRMax=0,DEFPRMax=0,HPPRMax=0),
                       '2':dict(RankID=2,RankName='D',ATKPRMax=5,DEFPRMax=5,HPPRMax=5)}
    result.feed_levels={str(i):{'0':dict(ATKPR=0,DEFPR=0,HPPR=0),'1':dict(ATKPR=5,DEFPR=0,HPPR=0)} for i in (1,2,3)}
    result.feed_limits={'1':dict(Star=0)}
    return result


def stage():
    return dict(battle_mode=dict(FieldGrids={'1':1,'2':1,'3':3,'4':12},DeployGrids={'1':1,'2':2,'3':3,'4':1}),
                waves=dict(GridY={'1':1,'2':2,'3':3}, ColumnCount=3, CanDeployNum=2, CanUsePetIDs={},
                           Frame={'8': {'Waves': {'1': {'EnemyID': 1101, 'Num': 3}}}}),
                enemy_units={'1101': {'UnitElement': 3}})


class WorkbenchTests(unittest.TestCase):
    def test_roster_roundtrip_and_validation(self):
        c = catalog()
        value = snapshot([{'unit_id': 1, 'attribute_ranks':{'ATK':'D'}, 'notes': '装备待确认'}], c, shared_level=234)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'roster.json'
            write_json(path, value)
            loaded = load_roster(path, c)
            self.assertEqual(loaded['pets'], value['pets'])
            self.assertEqual(loaded['source'], 'manual')
            self.assertEqual(loaded['shared_level'], 234)
            self.assertNotIn('level', loaded['pets'][0])
        for extra in [{'unit_id': 99}, {'level': '1.5'}, {'evolution': 9}, {'attribute_ranks':{'HP':'Z'}}, {'level': None}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_pet(dict({'unit_id': 1}, **extra), c)
        with self.assertRaises(ValueError):
            snapshot([{'unit_id': 1}, {'unit_id': 1}], c)

    def test_shared_level_migration_and_conflicts(self):
        c = catalog()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.json'
            old = dict(schema_version=1, data_version='apk-0.50.1', pets=[dict(unit_id=i, level=234) for i in (1,2)])
            write_json(path, old)
            value = load_roster(path, c)
            self.assertEqual(value['schema_version'], 3)
            self.assertEqual(value['shared_level'], 234)
            self.assertTrue(all('level' not in p for p in value['pets']))
            old['pets'][1]['level'] = 1
            write_json(path, old); before=path.read_bytes()
            with self.assertRaisesRegex(ValueError, '不同等级'): load_roster(path,c)
            self.assertEqual(before,path.read_bytes())
            migrated=load_roster(path,c,shared_level_override=234)
            self.assertEqual(migrated['shared_level'],234)
            self.assertEqual(len(migrated['pets']),2)
            self.assertEqual(before,path.read_bytes())
        for level in (0, '1.5', None, True):
            with self.assertRaises(ValueError): snapshot([],c,shared_level=level)

    def test_atomic_drag_swap_remove_and_invalid_drop(self):
        c, s = catalog(), stage()
        pets = snapshot([dict(unit_id=i) for i in (1,2,3)],c)['pets']
        board = {(1,2):1,(2,2):2}
        self.assertEqual(move_unit(s,pets,board,1,(2,2)),{(1,2):2,(2,2):1})
        self.assertEqual(move_unit(s,pets,board,1,None),{(2,2):2})
        self.assertEqual(move_unit(s,pets,board,3,(2,2)),{(1,2):1,(2,2):3})
        for uid,target in [(3,(3,2)),(3,(5,8)),(99,(1,2))]:
            with self.assertRaises(ValueError): move_unit(s,pets,board,uid,target)
            self.assertEqual(board,{(1,2):1,(2,2):2})

    def test_candidates_respect_slots_limits_and_allowed_pets(self):
        c, s = catalog(), stage()
        pets = snapshot([{'unit_id': i} for i in (1, 2, 3)], c)['pets']
        results = recommend(c, s, pets)
        self.assertEqual(len(results), 3)
        for candidate in results:
            positions = candidate['placements']
            self.assertEqual(len(positions), 2)
            self.assertEqual(len({p['unit_id'] for p in positions}), 2)
            self.assertFalse(candidate['simulated'])
            self.assertTrue(all((p['x'], p['y']) in slots_for(s) for p in positions))
        s['waves']['CanUsePetIDs'] = {'1': 1}
        self.assertEqual(recommend(c, s, pets)[0]['placements'][0]['unit_id'], 1)
        self.assertEqual(len(recommend(c, s, pets)[0]['placements']), 1)

    def test_empty_grid_uses_source_default_and_empty_rosters_rejected(self):
        c, s = catalog(), stage()
        with self.assertRaises(ValueError):
            recommend(c, s, [])
        s['waves']['GridY'] = {}
        self.assertEqual(len(slots_for(s)),5)
        del s['battle_mode']
        with self.assertRaises(KeyError):slots_for(s)

    def test_letter_ranks_are_not_numeric_stats(self):
        c=catalog()
        with self.assertRaisesRegex(ValueError,'评级组合'):
            validate_pet(dict(unit_id=1,attribute_ranks={'DEF':'D'}),c)
        self.assertEqual(validate_pet(dict(unit_id=1,attribute_ranks={'ATK':'D'}),c)['attribute_ranks']['ATK'],'D')


if __name__ == '__main__':
    unittest.main()
