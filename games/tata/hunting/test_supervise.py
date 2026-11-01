import io
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import supervise


class SupervisorTests(unittest.TestCase):
    def create(self,folder):
        return supervise.Supervisor([dict(hwnd=123,account_key='a'*24,stock=10,use_rage=True,
            allow_electric_last_hour=True)],datetime(2026,11,2,tzinfo=timezone.utc),folder)

    def test_launch_is_explicitly_bound_background_normal_hunting_with_rage(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.create(folder);job=supervisor.jobs[0]
            with patch.object(supervise.subprocess,'Popen',return_value=SimpleNamespace(pid=55)) as create:
                supervisor.launch(job)
            args=create.call_args.args[0]
            self.assertIn('--background',args);self.assertIn('--account-key',args)
            self.assertNotIn('--no-rage',args);self.assertNotIn('--spend-coins',args)
            self.assertEqual(args[args.index('--stock')+1],'10');job['stream'].close()

    def test_stop_or_account_change_is_not_automatically_restarted(self):
        for reason in ('F8 stop','用户停止','账号已切换','游戏已关闭','窗口最小化'):
            self.assertFalse(supervise.recoverable(reason))
        self.assertTrue(supervise.recoverable('不支持的 Lua 表布局'))
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.create(folder);job=supervisor.jobs[0]
            job.update(phase='running',process=SimpleNamespace(poll=lambda:1,returncode=1),stream=io.StringIO())
            with patch.object(supervisor,'observation',return_value=dict(reason='F8 stop')),patch.object(supervisor,'launch') as launch:
                supervisor.tick()
            self.assertEqual(job['phase'],'attention');launch.assert_not_called()

    def test_third_failure_within_ten_minutes_needs_attention(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.create(folder);job=supervisor.jobs[0]
            job.update(phase='running',process=SimpleNamespace(poll=lambda:1,returncode=1),stream=io.StringIO(),failures=[980,990])
            with patch.object(supervise.time,'monotonic',return_value=1000),\
                 patch.object(supervisor,'observation',return_value=dict(reason='Lua 表布局改变')),patch.object(supervisor,'launch') as launch:
                supervisor.tick()
            self.assertEqual(job['phase'],'attention');launch.assert_not_called()

    def test_electric_is_added_only_in_last_hour_when_measured_rate_is_insufficient(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.create(folder);job=supervisor.jobs[0];job['control']=Path(folder)/'control.json'
            with patch.object(supervisor,'observation',return_value=dict(bullets=100000)),\
                 patch.object(supervise,'datetime') as clock:
                clock.now.return_value=datetime(2026,11,1,22,30,tzinfo=timezone.utc)
                supervisor.update_last_hour(job,1000);self.assertFalse(job['electric_added'])
                job['history']=[(100,110000)]
                clock.now.return_value=datetime(2026,11,1,23,30,tzinfo=timezone.utc)
                supervisor.update_last_hour(job,1000)
            self.assertTrue(job['electric_added'])
            self.assertEqual(json.loads(job['control'].read_text())['targets'],[2008,2007])

    def test_last_hour_does_not_expand_when_rate_is_sufficient(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor=self.create(folder);job=supervisor.jobs[0];job['history']=[(100,200000)]
            with patch.object(supervisor,'observation',return_value=dict(bullets=100000)),patch.object(supervise,'datetime') as clock:
                clock.now.return_value=datetime(2026,11,1,23,30,tzinfo=timezone.utc)
                supervisor.update_last_hour(job,1000)
            self.assertFalse(job['electric_added'])
