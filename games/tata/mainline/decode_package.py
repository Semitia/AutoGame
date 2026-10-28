"""Decode Tata package offline, deriving its key from a verified old reference library."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import zipfile

import lz4.block
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish

from inspect_apk import parse_index

REFERENCE_SHA256 = '79a1028da49a1b639f964176127f1e1aaeddd0abbe8429387cc95c8956892dc5'
MAX_DECODED = 64 * 1024 * 1024


def reference_key(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != REFERENCE_SHA256:
        raise ValueError('Reference must be the verified overseas 0.31.11 ARM32 libigame.so')
    values = struct.unpack_from('<44I', data, 0x111070)
    key = bytes(v & 255 for v in values if v >= 0x30)
    if len(key) != 32:
        raise ValueError('Unexpected reference key layout')
    return key


def swap_words(data: bytes) -> bytes:
    if len(data) % 4:
        raise ValueError('Unaligned word buffer')
    result = bytearray(len(data))
    for i in range(4):
        result[i::4] = data[3-i::4]
    return bytes(result)


def decode_entry(raw: bytes, key: bytes) -> bytes:
    if len(raw) < 16 or raw[:4] != b'\xff' * 4 or (len(raw)-8) % 8:
        raise ValueError('Invalid encrypted entry header/alignment')
    length = struct.unpack_from('<I', raw, 4)[0]
    if not 8 <= length <= min(len(raw)-8, MAX_DECODED):
        raise ValueError('Invalid decrypted length')
    decoder = Cipher(Blowfish(key), modes.ECB()).decryptor()
    data = swap_words(decoder.update(swap_words(raw[8:])) + decoder.finalize())[:length]
    skip = struct.unpack_from('<I', data)[0] + 4
    if skip > len(data)-4:
        raise ValueError('Invalid metadata extent')
    size = struct.unpack_from('<I', data, skip)[0]
    if not 0 < size <= MAX_DECODED:
        raise ValueError('Invalid decompressed length')
    payload = lz4.block.decompress(data[skip:])
    if len(payload) != size:
        raise ValueError('Decompressed length mismatch')
    return payload


def decode(apk: Path, reference: Path, out: Path) -> dict:
    key = reference_key(reference.read_bytes())
    with zipfile.ZipFile(apk) as archive:
        package = archive.read('assets/pgame.pkg')
        rows = parse_index(archive.read('assets/pgame.pkg.bin'), len(package))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    entries, errors = [], []
    for row in rows:
        try:
            target = (out / row['name']).resolve()
            if not target.is_relative_to(out):
                raise ValueError('Output escapes destination')
            payload = decode_entry(package[row['offset']:row['offset']+row['size']], key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            entries.append(dict(name=row['name'], size=len(payload),
                                sha256=hashlib.sha256(payload).hexdigest(),
                                kind='lua54' if payload.startswith(b'\x1bLuaT') else 'resource'))
        except Exception as exc:
            errors.append(dict(name=row['name'], error=str(exc)))
    report = dict(package_sha256=hashlib.sha256(package).hexdigest(),
                  reference_sha256=REFERENCE_SHA256, total=len(rows), decoded=len(entries),
                  kinds=dict(Counter(e['kind'] for e in entries)), errors=errors)
    (out / 'decoded-index.json').write_text(json.dumps(entries, indent=2), encoding='utf-8')
    (out / 'decode-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--reference-lib', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = decode(args.apk, args.reference_lib, args.out)
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report['errors']))
