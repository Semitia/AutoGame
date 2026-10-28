import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from model import load_roster, snapshot, validate_pet, write_json
from policy import recommend, slots_for


def catalog():
    units = {str(i): dict(UnitType=1, Enable=True, UnitElement=i+1, UnitQuality=i,
                         CanDeployNum=1, CounterElement={'1': 3}, WeakElement={}) for i in (1, 2, 3)}
    result = SimpleNamespace(pets=units, evolutions={str(i): {'1': {'UnitQuality': i}} for i in (1, 2, 3)})
    result.quality = lambda p: result.evolutions[str(p['unit_id'])][str(p['evolution'])]['UnitQuality']
    return result


def stage():
    return dict(waves=dict(GridY={'1': 2}, ColumnCount=3, CanDeployNum=2, CanUsePetIDs={},
                           Frame={'8': {'Waves': {'1': {'EnemyID': 1101, 'Num': 3}}}}),
                enemy_units={'1101': {'UnitElement': 3}})


class WorkbenchTests(unittest.TestCase):
    def test_roster_roundtrip_and_validation(self):
        c = catalog()
        value = snapshot([{'unit_id': 1, 'level': 12, 'atk': '2.5', 'notes': '装备待确认'}], c)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'roster.json'
            write_json(path, value)
            loaded = load_roster(path, c)
            self.assertEqual(loaded['pets'], value['pets'])
            self.assertEqual(loaded['source'], 'manual')
        for extra in [{'unit_id': 99}, {'level': '1.5'}, {'evolution': 9}, {'atk': 'nan'}, {'level': None}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_pet(dict({'unit_id': 1}, **extra), c)
        with self.assertRaises(ValueError):
            snapshot([{'unit_id': 1}, {'unit_id': 1}], c)

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

    def test_unknown_grids_and_empty_rosters_rejected(self):
        c, s = catalog(), stage()
        with self.assertRaises(ValueError):
            recommend(c, s, [])
        s['waves']['GridY'] = {}
        with self.assertRaises(ValueError):
            recommend(c, s, snapshot([{'unit_id': 1}], c)['pets'])


if __name__ == '__main__':
    unittest.main()
