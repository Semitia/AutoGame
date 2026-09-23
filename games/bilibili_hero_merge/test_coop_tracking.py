import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from coop_engine import Observation
from coop_tracking import Tracker
from autogame.platforms.lease import device_lease


class TrackingTests(unittest.TestCase):
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
