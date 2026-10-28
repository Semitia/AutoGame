"""Read-only inventory/extraction of Tata's APK script package; no decryption.

Usage: python games/tata/mainline/inspect_apk.py APK --out runtime/tata/research/inventory
Requires lz4. Downloaded game files and extracted contents belong under runtime/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile

import lz4.block


def parse_index(encoded: bytes, package_size: int) -> list[dict]:
    """Parse size-prefixed LZ4 index; reject truncation, overlap and unsafe paths."""
    if len(encoded) < 4 or struct.unpack_from('<I', encoded)[0] > 64 * 1024 * 1024:
        raise ValueError('Invalid/oversized package index')
    data = lz4.block.decompress(encoded)
    if len(data) < 8:
        raise ValueError('Truncated index header')
    total, count = struct.unpack_from('<II', data)
    if total != package_size:
        raise ValueError('Index/package size mismatch')
    pos, rows, names = 8, [], set()
    for _ in range(count):
        if pos + 4 > len(data):
            raise ValueError('Truncated entry')
        length = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if pos + length + 8 > len(data):
            raise ValueError('Truncated entry path/extent')
        name = data[pos:pos + length].decode('utf-8')
        pos += length
        path = PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe entry path')
        if name.casefold() in names:
            raise ValueError('Duplicate entry path')
        names.add(name.casefold())
        size, offset = struct.unpack_from('<II', data, pos)
        pos += 8
        if size == 0 or offset + size > total:
            raise ValueError('Invalid entry extent')
        rows.append(dict(name=name, size=size, offset=offset))
    if pos != len(data):
        raise ValueError('Unexpected index trailer')
    end = 0
    for row in sorted(rows, key=lambda x: x['offset']):
        if row['offset'] != end:
            raise ValueError('Overlapping entries or unexplained gap')
        end += row['size']
    if end != total:
        raise ValueError('Index does not cover package')
    return rows


def inspect(apk: Path, out: Path, extract: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk) as archive:
        package = archive.read('assets/pgame.pkg')
        rows = parse_index(archive.read('assets/pgame.pkg.bin'), len(package))
        for row in rows:
            content = package[row['offset']:row['offset'] + row['size']]
            row['header_hex'] = content[:8].hex()
            row['sha256'] = hashlib.sha256(content).hexdigest()
            row['decoded'] = False
            if extract:
                target = out / 'encrypted' / row['name']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        unity_data = archive.read('assets/bin/Data/globalgamemanagers')
        metadata = archive.read('assets/bin/Data/Managed/Metadata/global-metadata.dat')
        import re
        match = re.search(rb'20\d\d\.\d+\.\d+[a-z]\d+', unity_data)
        digest = hashlib.sha256()
        with apk.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        report = {
            'apk_sha256': digest.hexdigest(),
            'apk_bytes': apk.stat().st_size,
            'unity_version': match[0].decode() if match else None,
            'metadata_magic_hex': metadata[:4].hex(),
            'package_bytes': len(package),
            'entries': len(rows),
            'categories': dict(Counter(r['name'].split('/')[0] for r in rows)),
            'relevant_counts': {prefix: sum(r['name'].startswith(prefix) for r in rows)
                                for prefix in ('Config/StageBattle/', 'Src/Battle/Logic/Heroes/',
                                               'Src/Battle/Logic/Skills/')},
            'payload_headers': dict(Counter(r['header_hex'][:8] for r in rows)),
            'decoded_entries': 0,
            'limitation': 'Paths and byte ranges recovered; encrypted payloads not decoded. '
                          'Counts do not imply playable mainline stages or usable skill formulas.',
        }
        (out / 'apk-files.json').write_text(json.dumps([
            dict(name=i.filename, size=i.file_size) for i in archive.infolist()
        ], ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'pkg-index.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--extract', action='store_true', help='Export encrypted entries without executing them')
    args = parser.parse_args()
    print(json.dumps(inspect(args.apk, args.out, args.extract), ensure_ascii=False, indent=2))
