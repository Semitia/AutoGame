"""Local integration smoke test; uses an isolated profile, never the real roster."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from model import Catalog, DATA, DATASET, RUNTIME, load_roster
from panel import MainlinePanel
from test_live_roster import capture


@unittest.skipUnless((DATA/'Config/Unit.json').exists() and (DATASET/'stages.json').exists(), 'Local extracted data required')
class PanelIntegrationTests(unittest.TestCase):
    def test_feedback_keeps_real_reports_separate_and_rejects_changed_plan_or_growth(self):
        from experience import Experience,stable_hash
        catalog=Catalog();source=capture()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);root=tk.Tk();root.withdraw()
            try:
                app=MainlinePanel(root,catalog,folder/'roster.json');app.apply_live_capture(source)
                plan=[dict(unit_id=1,x=3,y=1)]
                report=dict(simulated=True,stage_id=1,placements=plan,engine_fingerprint='ui-test',
                    context_hash='ui-context',context=dict(roster_hash=stable_hash(source['pets'])),
                    evaluation=dict(won=False,kills=1,total_enemies=2,battle_secs=10,score=1),
                    experience=dict(enabled=True,after=dict(battles=4,preference_updates=2),retrieved=[]))
                from model import write_json
                write_json(folder/'report.json',report);app.load_simulation(folder/'report.json')
                app.record_battle_feedback(True,folder/'memory.sqlite3')
                memory=Experience(folder/'memory.sqlite3')
                try:
                    self.assertEqual(memory.stats('ui-test')['user_reports'],1)
                    self.assertEqual(memory.stats('ui-test')['battles'],0)
                finally:memory.close()
                app.placements={(3,2):1}
                with self.assertRaises(ValueError):app.record_battle_feedback(False,folder/'memory.sqlite3')
                app.placements={(3,1):1};app.level.set('235')
                with self.assertRaises(ValueError):app.record_battle_feedback(False,folder/'memory.sqlite3')
            finally:root.destroy()

    def test_live_sync_keeps_notes_backup_and_rejects_bad_capture(self):
        catalog=Catalog()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'roster.json';root=tk.Tk();root.withdraw()
            try:
                app=MainlinePanel(root,catalog,path)
                app.persist([dict(unit_id=1,notes='我的装备备注')]);before=path.read_bytes()
                app.apply_live_capture(capture())
                self.assertEqual(app.level.get(),'234')
                self.assertEqual(app.pets[0]['notes'],'我的装备备注')
                self.assertEqual(path.with_suffix('.previous.json').read_bytes(),before)
                self.assertEqual(load_roster(path,catalog)['pets'][0]['game_observed']['gs'],100)
                before=path.read_bytes();bad=capture();bad['pets'][0]['tid']=999999
                with self.assertRaises(ValueError):app.apply_live_capture(bad)
                self.assertEqual(path.read_bytes(),before)
            finally:root.destroy()

    @unittest.skipUnless((RUNTIME/'search-11-26.json').exists(),'Local experimental simulation required')
    def test_simulated_plan_enemy_elements_and_replay(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk();root.withdraw()
            try:
                app=MainlinePanel(root,Catalog(),Path(directory)/'roster.json')
                app.apply_live_capture(json.loads((RUNTIME/'combat-capture.json').read_text(encoding='utf-8')))
                app.load_simulation(RUNTIME/'search-11-26.json')
                self.assertEqual(len(app.placements),15)
                self.assertEqual(app.stage_data['stage']['ID'],826)
                self.assertEqual(len(app.board.enemy_regions),15)
                app.toggle_replay();self.assertIsNotNone(app.replay_frame)
                self.assertEqual(app.replay_index,1)
                app.replay_playing=False
                app.choose_candidate(1)
                if app.placements!={(p['x'],p['y']):p['unit_id'] for p in app.current_report['placements']}:
                    with self.assertRaises(ValueError):app.toggle_replay()
            finally:root.destroy()

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
