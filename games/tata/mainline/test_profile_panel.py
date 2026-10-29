import tempfile
from pathlib import Path
import tkinter as tk
import unittest

from model import Catalog, DATA
from panel import MainlinePanel
from profiles import Profiles
from test_profiles import session


@unittest.skipUnless((DATA/'Config/Unit.json').exists(),'Shared game resources required')
class ProfilePanelTests(unittest.TestCase):
    def test_current_stage_account_switch_and_restart_remember_independent_workspaces(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);store=Profiles(folder/'accounts',legacy=None)
            root=tk.Tk();root.withdraw()
            try:
                app=MainlinePanel(root,Catalog(),folder/'unused.json',profile_store=store,auto_sync=False)
                app.apply_sessions([session(123,566)])
                self.assertEqual(app.stage_query.get(),'8-6')
                self.assertEqual(app.stage_data['stage']['ID'],566)
                a=store.active
                app.pets[0]['notes']='A 独立备注';app.persist()
                app.apply_sessions([session(456,1)])
                b=store.active;self.assertNotEqual(a,b)
                self.assertEqual(app.pets[0]['notes'],'')
                self.assertEqual(app.stage_query.get(),'1-1')
                app.switch_profile(a)
                self.assertEqual(app.stage_query.get(),'8-6')
                self.assertEqual(app.pets[0]['notes'],'A 独立备注')
                app.stage_query.set('1-1');app.load_manual_stage()
                app.apply_sessions([session(123,566)])
                self.assertEqual(app.stage_query.get(),'1-1')
                self.assertFalse(app.follow_game.get())
                app.follow_game.set(True);app.apply_sessions([session(123,566)])
                self.assertEqual(app.stage_query.get(),'8-6')
                app.save_workspace()
                root.destroy()
                root=tk.Tk();root.withdraw()
                restarted=MainlinePanel(root,Catalog(),folder/'unused.json',profile_store=Profiles(store.root,legacy=None),auto_sync=False)
                self.assertEqual(restarted.stage_query.get(),'8-6')
                self.assertEqual(restarted.profiles.active,a)
                self.assertEqual(restarted.pets[0]['notes'],'A 独立备注')
            finally:root.destroy()
