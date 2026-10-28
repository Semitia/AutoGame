"""Local integration smoke test; uses an isolated profile, never the real roster."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from model import Catalog, DATA, DATASET, load_roster
from panel import MainlinePanel


@unittest.skipUnless((DATA/'Config/Unit.json').exists() and (DATASET/'stages.json').exists(), 'Local extracted data required')
class PanelIntegrationTests(unittest.TestCase):
    def test_edit_save_restart_and_plan(self):
        catalog = Catalog()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'qa-roster.json'
            root = tk.Tk(); root.withdraw()
            try:
                app = MainlinePanel(root, catalog, path)
                self.assertNotIn('level',app.fields)
                app.level.set('234'); app.save_level()
                for uid in list(sorted(map(int,catalog.pets)))[:4]:
                    app.select_pet(uid); app.save_pet()
                self.assertEqual(len(load_roster(path, catalog)['pets']), 4)
                app.plan()
                self.assertEqual(len(app.placements), 3)
                self.assertTrue(all(v in {p['unit_id'] for p in app.pets} for v in app.placements.values()))
                app.place(next(iter(app.placements.values())),None)
                self.assertEqual(len(app.placements), 2)
                app.set_filter('element',2)
                self.assertTrue(all(catalog.pets[str(k)]['UnitElement']==2 for k in app.visible_ids()))
                app.set_filter('career',3)
                self.assertTrue(all(catalog.pets[str(k)]['UnitCareer']==3 for k in app.visible_ids()))
                app.reset_filters()
                app.stage_query.set('2-21'); app.load_stage()
                self.assertEqual(app.stage_data['stage']['ID'], 101)
                self.assertFalse(app.placements)
            finally:
                root.destroy()
            root = tk.Tk(); root.withdraw()
            try:
                app = MainlinePanel(root, catalog, path)
                self.assertEqual(len(app.pets), 4)
                self.assertEqual(app.level.get(),'234')
                self.assertTrue(all('level' not in p for p in app.pets))
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
