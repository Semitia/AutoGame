"""Name resolution must use evidence, never emulator-number order."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_devices as devices

FIRST = '11111111-1111-1111-1111-111111111111'
SECOND = '22222222-2222-2222-2222-222222222222'


class DiscoveryTests(unittest.TestCase):
    def test_manager_boot_sections_and_online_filter(self):
        self.assertEqual(devices.parse_boots(f'### mumu-7 ###:\n{FIRST}\n### mumu-2 ###:\n{SECOND}\n'), {'7': FIRST, '2': SECOND})
        self.assertEqual(devices.parse_online('List of devices attached\none device model:Test\ntwo offline\nthree unauthorized\none device\n'), ['one'])

    def test_reversed_serials_match_identity_not_numeric_order(self):
        instances = {'0': {'name': '大号'}, '1': {'name': '小号'}}
        labels, identities = devices.match_names(['emulator-5554', 'emulator-5556'], instances,
            {'0': FIRST, '1': SECOND}, {'emulator-5554': SECOND, 'emulator-5556': FIRST})
        self.assertEqual(identities, {'emulator-5554': '1', 'emulator-5556': '0'})
        self.assertIn('小号', labels['emulator-5554'])
        self.assertIn('大号', labels['emulator-5556'])

    def test_ambiguous_or_missing_identity_does_not_guess(self):
        info = {'0': {'name': 'A'}, '1': {'name': 'B'}}
        for serial_boots in ({'serial': FIRST}, {'serial': ''}, {}):
            self.assertEqual(devices.match_names(['serial'], info, {'0': FIRST, '1': FIRST}, serial_boots), ({}, {}))

    def test_manager_unavailable_keeps_adb_devices(self):
        with patch.object(devices, 'run_text', side_effect=['one device\n', OSError('not installed')]):
            result = devices.discover_devices('adb', 'missing-manager')
        self.assertEqual(result['serials'], ['one'])
        self.assertEqual(result['labels'], {})

    def test_discovery_only_reads_live_metadata(self):
        import json
        calls = []
        def fake(args, timeout=8):
            calls.append(args)
            if args == ['adb', 'devices', '-l']: return 'serial-A device\nserial-B device\n'
            if args == ['manager', 'info', '-v', 'all']:
                return json.dumps({'0': {'name': 'MuMu A', 'index': '0', 'is_android_started': True},
                                   '1': {'name': 'MuMu B', 'index': '1', 'is_android_started': True}})
            if args[:2] == ['manager', 'sh']: return f'### mumu-0 ###:\n{FIRST}\n### mumu-1 ###:\n{SECOND}\n'
            if args == ['adb', '-s', 'serial-A', 'shell', 'cat', devices.BOOT_FILE]: return SECOND
            if args == ['adb', '-s', 'serial-B', 'shell', 'cat', devices.BOOT_FILE]: return FIRST
            raise AssertionError(args)
        with patch.object(devices, 'run_text', side_effect=fake):
            result = devices.discover_devices('adb', 'manager')
        self.assertEqual(result['identities'], {'serial-A': '1', 'serial-B': '0'})
        self.assertEqual(len(calls), 5)
        self.assertFalse(any('connect' in cmd or 'input' in cmd for cmd in calls))


if __name__ == '__main__': unittest.main()
