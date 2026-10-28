import tempfile
import unittest
from pathlib import Path

from lupa.lua54 import LuaError
from export_config import read_config


class ConfigTests(unittest.TestCase):
    def evaluate(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.lua'
            path.write_text(text, encoding='utf-8')
            return read_config(path)

    def test_preserves_sparse_frame_and_unicode(self):
        data = self.evaluate('config.Waves = {[8]={name="宠物"},[60]={count=3}}')
        self.assertEqual(data, {'Waves': {'8': {'name': '宠物'}, '60': {'count': 3}}})

    def test_environment_has_no_file_access(self):
        with self.assertRaises(LuaError):
            self.evaluate('config.x = io.open("missing")')

    def test_infinite_loop_bounded(self):
        with self.assertRaisesRegex(LuaError, 'instruction budget'):
            self.evaluate('while true do end')

    def test_non_data_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Non-data'):
            self.evaluate('config.x = function() end')


if __name__ == '__main__':
    unittest.main()
