"""Replay annotated observations without constructing a device or OCR reader.

Each JSONL row: layer, prices, cells, occupied, units [{pos, hero, tier}],
summon_count, board_verified, token; optional expected action kind.
"""
import argparse
import json
from pathlib import Path
from coop_engine import Engine, Observation
from tactics import load_tactics


def replay(path, config, side):
    engine = Engine(config, side)
    results = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        data = json.loads(line)
        expected = data.pop('expected', None)
        for key in ('cells', 'occupied'):
            data[key] = {tuple(p) for p in data.get(key, [])}
        data['units'] = {tuple(u['pos']): {k:v for k,v in u.items() if k != 'pos'}
                         for u in data.get('units', [])}
        action = engine.next(Observation(**data))
        if expected and action['kind'] != expected:
            raise AssertionError(f'Line {number}: expected {expected}, got {action}')
        results.append(action)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observations', type=Path)
    parser.add_argument('--tactics', required=True, type=Path)
    parser.add_argument('--side', required=True, choices=('host','guest'))
    args = parser.parse_args()
    for action in replay(args.observations, load_tactics(args.tactics)[0], args.side):
        print(json.dumps(action, ensure_ascii=False))
