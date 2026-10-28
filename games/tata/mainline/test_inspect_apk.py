import struct
import unittest

import lz4.block

from inspect_apk import parse_index


def index(entries, total=16):
    raw = struct.pack('<II', total, len(entries))
    for name, size, offset in entries:
        path = name.encode()
        raw += struct.pack('<I', len(path)) + path + struct.pack('<II', size, offset)
    return lz4.block.compress(raw)


class IndexTests(unittest.TestCase):
    def test_roundtrip_extents(self):
        rows = parse_index(index([('Config/Unit.luae', 8, 0), ('Src/Test.luae', 8, 8)]), 16)
        self.assertEqual(rows[1], dict(name='Src/Test.luae', size=8, offset=8))

    def test_bad_paths_and_extents(self):
        for entries in [[('../escape', 16, 0)], [('C:/escape', 16, 0)],
                        [('a', 17, 0)], [('a', 8, 0), ('b', 8, 4)],
                        [('a', 8, 0), ('A', 8, 8)]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                parse_index(index(entries), 16)

    def test_truncation_and_size_mismatch(self):
        with self.assertRaises(ValueError):
            parse_index(lz4.block.compress(struct.pack('<II', 16, 1)), 16)
        with self.assertRaises(ValueError):
            parse_index(index([('a', 16, 0)]), 17)


if __name__ == '__main__':
    unittest.main()
