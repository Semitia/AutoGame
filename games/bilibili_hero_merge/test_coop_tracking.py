import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from coop_engine import Observation
from coop_tracking import Tracker
from autogame.platforms.lease import device_lease
from autogame.platforms.lease import assert_no_legacy_controller


class TrackingTests(unittest.TestCase):
    def test_windows_process_scan_explicit_utf8_and_chinese_controller(self):
        rows=[{'ProcessId':987654, 'CommandLine':'python run.py blue_planet --device 测试设备'}]
        with patch('autogame.platforms.lease.os.name','nt'), patch('autogame.platforms.lease.subprocess.check_output',return_value=json.dumps(rows,ensure_ascii=False).encode('utf-8-sig')) as run:
            with self.assertRaisesRegex(RuntimeError,'987654'):
                assert_no_legacy_controller('测试设备')
            self.assertIn('[Console]::OutputEncoding',run.call_args.args[0][-1])
            self.assertIn('UTF8Encoding',run.call_args.args[0][-1])

    def setUp(self):
        self.cells={(77,494),(111,494),(146,494)}
        self.tracker=Tracker()
        self.obs=Observation('battle',prices={'upgrade':100,'summon':0,'money':0},
                             cells=self.cells,board_verified=True)

    def test_initialize_requires_empty_free_verified_board(self):
        self.tracker.initialize(self.obs);self.assertEqual(self.tracker.summons,0)
        self.obs.prices['summon']=190
        with self.assertRaises(ValueError):Tracker().initialize(self.obs)

    def test_failed_summon_does_not_increment(self):
        self.tracker.initialize(self.obs)
        p={'kind':'summon','count':0,'occupied':set(),'price':0}
        result=self.tracker.reconcile(self.obs,p,Mock())
        self.assertEqual(result.summon_count,0);self.assertEqual(result.units,{})

    def test_paid_initial_summon_requires_first_wave_and_seven_empty_cells(self):
        self.obs.cells={(111,460)}|{(x,y) for x in (77,111,146) for y in (494,527)}
        self.obs.prices['summon']=10
        with self.assertRaises(ValueError):Tracker().initialize(self.obs)
        tracker=Tracker();tracker.initialize(self.obs,first_wave=True)
        self.assertEqual(tracker.summons,0)
        self.obs.prices['summon']=190
        with self.assertRaises(ValueError):Tracker().initialize(self.obs,first_wave=True)
        self.obs.prices['summon']=10;self.obs.occupied={(111,460)}
        with self.assertRaises(ValueError):Tracker().initialize(self.obs,first_wave=True)

    def test_price_change_without_new_unit_does_not_increment(self):
        self.tracker.initialize(self.obs);self.obs.prices['summon']=10
        identify=Mock()
        result=self.tracker.reconcile(self.obs,{'kind':'summon','count':0,'occupied':set(),'price':0},identify)
        self.assertEqual(result.summon_count,0);identify.assert_not_called()

    def test_external_board_change_rejected(self):
        self.tracker.initialize(self.obs);self.obs.occupied={(77,494)}
        with self.assertRaisesRegex(ValueError,'without a recorded action'):
            self.tracker.reconcile(self.obs,None,Mock())

    def test_disappeared_tile_rejected(self):
        self.tracker.initialize(self.obs);self.obs.cells={(77,494)}
        with self.assertRaisesRegex(ValueError,'wall cells disappeared'):
            self.tracker.reconcile(self.obs,None,Mock())

    def test_restore_drops_historical_ranks(self):
        self.obs.occupied={(77,494)}
        data={'units':[{'pos':[77,494],'hero':'sea','tier':3}],
              'cells':list(self.cells),'prices':self.obs.prices,'summons':9,'wave':2}
        self.tracker.restore(data,self.obs,lambda pos:'sea')
        self.assertEqual(self.tracker.units[(77,494)]['tier'],0)
        self.assertEqual(self.tracker.summons,9)

    def test_restore_rejects_different_hero(self):
        self.obs.occupied={(77,494)}
        data={'units':[{'pos':[77,494],'hero':'sea','tier':3}],
              'cells':list(self.cells),'prices':self.obs.prices,'summons':9}
        with self.assertRaises(ValueError):self.tracker.restore(data,self.obs,lambda pos:'sword')

    def test_device_lease_excludes_other_runtime_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            with device_lease('host-device',temp,False):
                with self.assertRaises(RuntimeError):
                    with device_lease('host-device',temp,False):pass
                with device_lease('guest-device',temp,False):pass
            with device_lease('host-device',temp,False):pass


if __name__=='__main__':unittest.main()
