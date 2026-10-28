import struct
import unittest

import lz4.block
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish

from decode_package import MAX_DECODED, decode_entry, reference_key, swap_words


KEY = b'0123456789abcdef0123456789abcdef'


def encrypt(data):
    length = len(data)
    data += b'\0' * (-length % 8)
    cipher = Cipher(Blowfish(KEY), modes.ECB()).encryptor()
    return b'\xff' * 4 + struct.pack('<I', length) + swap_words(
        cipher.update(swap_words(data)) + cipher.finalize())


class DecodeTests(unittest.TestCase):
    def test_wrapped_lua_and_binary(self):
        for payload in (b'\x1bLuaT' + bytes(range(256)), b'\0binary\xff'):
            raw = encrypt(struct.pack('<I', 6) + b'meta#$' + lz4.block.compress(payload))
            self.assertEqual(decode_entry(raw, KEY), payload)

    def test_known_word_order(self):
        self.assertEqual(swap_words(bytes(range(8))), bytes([3, 2, 1, 0, 7, 6, 5, 4]))

    def test_malformed_input(self):
        invalid = [b'', b'\0' * 16, b'\xff' * 4 + struct.pack('<I', 99) + b'\0' * 8,
                   encrypt(struct.pack('<I', 1000) + b'xxxx'),
                   encrypt(struct.pack('<II', 0, MAX_DECODED+1)),
                   encrypt(struct.pack('<II', 0, 10) + b'invalid lz4')]
        for raw in invalid:
            with self.subTest(raw=raw[:16]), self.assertRaises((ValueError, lz4.block.LZ4BlockError)):
                decode_entry(raw, KEY)

    def test_wrong_reference(self):
        with self.assertRaises(ValueError):
            reference_key(b'other version')


if __name__ == '__main__':
    unittest.main()
