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
                for i in range(4):
                    app.catalog_box.current(i); app.new_pet()
                    app.fields['level'].set(str(10+i)); app.save_pet()
                self.assertEqual(len(load_roster(path, catalog)['pets']), 4)
                app.plan()
                self.assertEqual(len(app.placements), 3)
                self.assertTrue(all(v in app.assign_ids for v in app.placements.values()))
                app.assign_box.current(0); app.place(next(iter(app.placements)))
                self.assertEqual(len(app.placements), 2)
                app.stage_query.set('2-21'); app.load_stage()
                self.assertEqual(app.stage_data['stage']['ID'], 101)
                self.assertFalse(app.placements)
            finally:
                root.destroy()
            root = tk.Tk(); root.withdraw()
            try:
                app = MainlinePanel(root, catalog, path)
                self.assertEqual(len(app.pets), 4)
                self.assertEqual(app.pets[0]['level'], 10)
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
