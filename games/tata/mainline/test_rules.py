import tempfile,unittest
from pathlib import Path
from model import Catalog,DATA,DATASET,validate_pet,load_roster,write_json
from rules import grid_areas,star_icons,evolution_gate,feed_candidates
from policy import slots_for


class StarRuleTests(unittest.TestCase):
    def test_color_and_special_boundaries(self):
        expected={0:[],6:[1]*6,7:[2]+[1]*5,12:[2]*6,13:[3]+[2]*5,
                  36:[6]*6,42:[7]*6,72:[12]*6,73:[13],78:[18],79:[19],84:[24]}
        for level,icons in expected.items():
            with self.subTest(level=level):self.assertEqual(star_icons(level),icons)


@unittest.skipUnless((DATA/'Config/Unit.json').exists() and (DATASET/'stages.json').exists(),'Local game data required')
class SourceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.catalog=Catalog()

    def test_geometry_from_battle_mode_and_gridy_x_bounds(self):
        first=self.catalog.stage(1);areas=grid_areas(first)
        self.assertEqual(areas['deploy'],dict(x=3,y=1,width=1,height=5))
        self.assertEqual(slots_for(first),[(3,y) for y in range(1,6)])
        later=self.catalog.stage(826);areas=grid_areas(later)
        self.assertEqual((areas['deploy']['width'],areas['deploy']['height']),(5,5))
        later['waves']['GridY']={}
        self.assertEqual(len(slots_for(later)),25)

    def test_per_pet_evolution_thresholds_and_rank_paths(self):
        c=self.catalog
        self.assertEqual(evolution_gate(c,11,2)['minimum'],3)
        self.assertEqual(evolution_gate(c,12,2)['minimum'],6)
        with self.assertRaises(ValueError):validate_pet(dict(unit_id=11,evolution=4,stars=3),c)
        self.assertEqual(validate_pet(dict(unit_id=11,evolution=4,stars=42),c)['stars'],42)
        a=feed_candidates(c,1,0)[0]['ranks'];b=feed_candidates(c,2,0)[0]['ranks']
        self.assertEqual(a['HP'],'D');self.assertEqual(b['HP'],'E')
        self.assertEqual(a['ATK'],'E');self.assertEqual(b['ATK'],'D')

    def test_legacy_invalid_star_and_numeric_stats_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'old.json'
            write_json(p,dict(schema_version=2,data_version='apk-0.50.1',shared_level=234,
                              pets=[dict(unit_id=11,evolution=4,stars=3,atk=123)]))
            # legacy numeric fields are archived; an invalid old star is left unknown.
            before=p.read_bytes();value=load_roster(p,self.catalog)
            self.assertEqual(value['schema_version'],3)
            self.assertIsNone(value['pets'][0]['stars'])
            self.assertEqual(value['pets'][0]['legacy_stats']['atk'],123)
            self.assertEqual(before,p.read_bytes())


if __name__=='__main__':unittest.main()
