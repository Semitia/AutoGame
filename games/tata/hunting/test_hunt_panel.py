"""Withdrawn Tk panel: account selection and worker flags only, no game input."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
import importlib.util
import hunt_paths
spec=importlib.util.spec_from_file_location('hunting_panel_test_module',Path(__file__).with_name('panel.py'))
panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=tk.Tk();self.root.withdraw()
        self.runtime=patch.object(panel,'RUNTIME',Path(self.directory.name));self.runtime.start()
        with patch('window_binding.window_choices',return_value=[(11,(100,200,400,750)),(22,(600,200,400,750))]):
            self.app=panel.HuntPanel(self.root)

    def tearDown(self):
        self.root.destroy();self.runtime.stop();self.directory.cleanup()

    def test_two_accounts_require_explicit_window_selection(self):
        self.assertEqual(self.app.window_choice.get(),'')
        with patch.object(panel.subprocess,'Popen') as create:self.app.start()
        create.assert_not_called();self.assertIn('请选择',self.app.status.get())

    def test_targets_default_to_shaman_and_optional_electric_reaches_worker(self):
        self.assertEqual(self.app.options().target_ids,(2008,))
        self.app.targets[2007].set(True);self.app.window_choice.set(list(self.app.window_map)[0])
        with patch.object(panel.subprocess,'Popen',return_value=Mock()) as create,patch.object(panel.threading,'Thread'):
            self.app.start()
        args=create.call_args.args[0]
        self.assertEqual(args[args.index('--targets')+1],'2008,2007')

    def test_background_setting_and_window_are_passed_without_activation(self):
        self.app.window_choice.set(list(self.app.window_map)[1]);self.app.background.set(True)
        with patch.object(panel.subprocess,'Popen',return_value=Mock()) as create,patch.object(panel.threading,'Thread'):
            self.app.start()
        args=create.call_args.args[0]
        self.assertIn('--background',args);self.assertNotIn('--activate',args)
        self.assertEqual(args[args.index('--hwnd')+1],'22')
