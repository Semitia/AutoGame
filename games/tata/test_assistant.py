"""Unified UI integration checks with isolated profiles and no game operations."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from assistant import TataAssistant,MultiAccountAssistant,load_panel


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = TataAssistant(self.root, mainline_options={
            'state': Path(self.directory.name)/'roster.json', 'auto_sync': False})

    def tearDown(self):
        self.root.destroy()
        self.directory.cleanup()

    def test_both_panels_embed_and_switch_without_losing_state(self):
        mainline = load_panel('mainline')
        if not (mainline.DATA/'Config/Unit.json').exists():
            self.skipTest('Local catalog required')
        title = self.root.title()
        with patch('resources.ensure_default_resources'):
            self.app.show('mainline')
        self.assertIsNotNone(self.app.mainline)
        self.app.mainline.level.set('234')
        self.app.mainline.tabs.select(1)
        self.root.update_idletasks()
        self.app.show('fishing')
        self.assertIsNotNone(self.app.fishing)
        self.app.fishing.minutes.set('45')
        self.assertEqual(self.root.title(), title)
        self.assertEqual(ttk_color(self.root), '#211e39')
        self.app.show('mainline')
        self.assertEqual(self.app.mainline.level.get(), '234')
        self.assertEqual(self.app.mainline.tabs.index('current'), 1)
        self.app.show('fishing')
        self.assertEqual(self.app.fishing.minutes.get(), '45')
        self.assertEqual(len(self.app.pages), 3)

    def test_cross_feature_guard_blocks_only_automatic_game_control(self):
        worker = SimpleNamespace(poll=lambda: None)
        self.app.fishing = SimpleNamespace(process=worker)
        with self.assertRaisesRegex(ValueError, '钓鱼正在运行'):
            self.app.check_start('mainline')
        self.app.fishing = None
        self.app.mainline = SimpleNamespace(combat_process=worker)
        self.app.check_start('fishing')
        self.app.mainline.autoplay_process = worker
        with self.assertRaisesRegex(ValueError, '自动推关正在运行'):
            self.app.check_start('fishing')

    def test_stop_signals_and_close_wait_for_owned_worker(self):
        folder = Path(self.directory.name)
        state = {'active': True}
        worker = SimpleNamespace(poll=lambda: None if state['active'] else 0)
        fishing = SimpleNamespace(process=worker, stop=Mock(), status=tk.StringVar(value='运行中'),
                                  metrics=tk.StringVar(value='出杆 1'))
        self.app.fishing = fishing
        with patch('assistant.RUNTIME', folder):
            self.app.stop_all()
            self.assertTrue((folder/'mainline/AUTOPLAY-STOP').exists())
            self.assertTrue((folder/'fishing/STOP').exists())
            fishing.stop.assert_called_once()
            self.app.close()
            self.app.poll()
            self.assertTrue(self.root.winfo_exists())
            state['active'] = False
            with patch.object(self.root, 'after') as after:
                self.app.poll()
                after.assert_called_once_with(600, self.root.destroy)

    def test_failed_module_can_retry_and_other_page_stays_available(self):
        with patch('assistant.load_panel', side_effect=ImportError('test missing dependency')):
            self.app.show('fishing')
        self.assertIsNone(self.app.fishing)
        self.app.show('home')
        self.app.retry('fishing')
        self.assertIsNotNone(self.app.fishing)


def ttk_color(root):
    from tkinter import ttk
    return ttk.Style(root).lookup('TFrame', 'background')


class ControlLeaseTests(unittest.TestCase):
    def test_different_account_workspaces_can_run_different_tools(self):
        from windows_runtime import prepare
        prepare()
        root=tk.Tk();root.withdraw()
        try:
            with patch('window_binding.window_choices',return_value=[(11,(0,0,400,750)),(22,(500,0,400,750))]),\
                 patch('windows_runtime.window_identity',side_effect=lambda hwnd:dict(key=str(hwnd),name=f'账号{hwnd}')):
                app=MultiAccountAssistant(root)
            first,second=app.workspaces[11],app.workspaces[22]
            worker=SimpleNamespace(poll=lambda:None)
            first.hunting=SimpleNamespace(process=worker,observing=False)
            second.check_start('fishing')
            second.fishing=SimpleNamespace(process=worker,observe=False)
            first.check_start('hunting');second.check_start('fishing')
            with self.assertRaises(ValueError):first.check_start('fishing')
            self.assertEqual(set(app.workspaces),{11,22})
        finally:root.destroy()

    def test_autoplay_cannot_focus_or_construct_runner_while_fishing_holds_lease(self):
        load_panel('mainline')
        import autoplay
        import desktop_input
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
        from autogame.platforms import lease
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            original = lease.device_lease
            def isolated(key, **kwargs):
                return original(key, directory=folder/'locks', **kwargs)
            with isolated('windows-fishing-123', check_processes=False):
                with patch.object(autoplay, 'RUNTIME', folder/'mainline'), \
                     patch.object(sys, 'argv', ['autoplay.py']), \
                     patch.object(desktop_input, 'find_game_window', return_value=123), \
                     patch.object(lease, 'device_lease', side_effect=isolated), \
                     patch.object(autoplay, 'Runner') as runner:
                    with self.assertRaisesRegex(RuntimeError, 'already controlled'):
                        autoplay.main()
                    runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
