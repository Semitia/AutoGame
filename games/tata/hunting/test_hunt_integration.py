"""Headless shell/CLI integration: no Tk windows, game process reads or input."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from hunt_paths import HERE


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class IntegrationTests(unittest.TestCase):
    def test_unified_shell_blocks_conflicting_input_but_allows_local_search_and_readonly_hunt(self):
        module=load('hunt_test_assistant',HERE.parent/'assistant.py')
        app=module.TataAssistant.__new__(module.TataAssistant);app.closing=False
        worker=SimpleNamespace(poll=lambda:None)
        app.mainline=SimpleNamespace(combat_process=worker);app.fishing=None;app.hunting=None
        app.check_start('hunting')
        app.hunting=SimpleNamespace(process=worker,observing=False)
        for mode in ('mainline','fishing'):
            with self.assertRaisesRegex(ValueError,'围猎正在运行'):app.check_start(mode)
        app.hunting.observing=True;app.check_start('fishing')
        app.mainline.autoplay_process=worker
        with self.assertRaisesRegex(ValueError,'自动推关正在运行'):app.check_start('hunting')

    def test_loading_panel_never_starts_worker_or_queries_game(self):
        module=load('hunt_test_assistant_loader',HERE.parent/'assistant.py')
        with patch('subprocess.Popen',side_effect=AssertionError('worker must not start')):
            panel=module.load_panel('hunting')
        self.assertTrue(hasattr(panel,'HuntPanel'))

    def test_explicit_run_acquires_shared_window_lease_before_focusing(self):
        module=load('hunt_desktop_test',HERE/'desktop.py');calls=[]
        @contextmanager
        def lease(key,**kwargs):
            calls.append(('lease',key));yield
        controls=SimpleNamespace(focus=lambda:calls.append(('focus',)),release=Mock())
        fake_input=SimpleNamespace(HuntInput=lambda:controls)
        fake_desktop=SimpleNamespace(find_game_window=lambda:123)
        live=SimpleNamespace(close=Mock());runner=SimpleNamespace(run=Mock())
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'hunt_input':fake_input,'desktop_input':fake_desktop}),\
             patch('autogame.platforms.lease.device_lease',side_effect=lease),patch('hunt_live.HuntLive',return_value=live),\
             patch('hunt_engine.Runner',return_value=runner),patch('hunt_layout.Layout'),patch('builtins.print'),\
             patch.object(sys,'argv',['hunting','--run','--activate','--run-dir',directory]):
            module.main()
        self.assertEqual(calls,[('lease','windows-fishing-123'),('focus',)])
        runner.run.assert_called_once();live.close.assert_called_once();controls.release.assert_called_once()

    def test_observe_has_no_control_transport_or_focus_even_with_activate_flag(self):
        module=load('hunt_desktop_observe_test',HERE/'desktop.py')
        state=dict(screen='lobby',locks=4,rage=2,bullets=99000,enemies=[])
        live=SimpleNamespace(snapshot=lambda:state,close=Mock())
        with tempfile.TemporaryDirectory() as directory,patch('hunt_live.HuntLive',return_value=live),\
             patch('autogame.platforms.lease.device_lease',side_effect=AssertionError('no lease in observe mode')),\
             patch('hunt_input.HuntInput',side_effect=AssertionError('no input transport')),patch('builtins.print'),\
             patch.object(sys,'argv',['hunting','--observe','--activate','--seconds','0.001','--run-dir',directory]):
            module.main()
            self.assertEqual(json.loads((Path(directory)/'observation.json').read_text())['locks'],4)
        live.close.assert_called_once()
