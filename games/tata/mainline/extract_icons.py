"""Export local pet head sprites from concatenated UnityFS bundles, for local UI use."""
import argparse
import json
from pathlib import Path
import struct
import UnityPy


def extract(path, out, data=None):
    UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f3'
    raw = path.read_bytes()
    out.mkdir(parents=True, exist_ok=True)
    position, count, exported, errors = 0, 0, set(), []
    wanted = set()
    if data:
        def collect(value):
            if isinstance(value, str) and value.lower().endswith(('.png', '.jpg')):
                wanted.add(Path(value).stem)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        for name in ('UnitRes', 'UnitCareer', 'UnitElement', 'UnitQuality', 'StageBattleRes'):
            collect(json.loads((data/'Config'/f'{name}.json').read_text(encoding='utf-8')))
    while position < len(raw):
        if raw[position:position+8] != b'UnityFS\0':
            raise ValueError(f'Invalid bundle boundary {position}')
        cursor = position+12
        for _ in range(2):
            cursor = raw.index(b'\0', cursor)+1
        size = struct.unpack_from('>Q', raw, cursor)[0]
        if size < cursor-position+8 or position+size > len(raw):
            raise ValueError('Invalid bundle size')
        try:
            env = UnityPy.load(raw[position:position+size])
            for obj in env.objects:
                if obj.type.name not in ('Sprite', 'Texture2D'):
                    continue
                name = obj.peek_name()
                if not name or Path(name).name != name:
                    continue
                name = Path(name).stem
                if name not in wanted and not name.startswith('txui_pet_head_'):
                    continue
                if name in exported:
                    continue
                obj.read().image.save(out / (name+'.png'))
                exported.add(name)
        except Exception as exc:
            errors.append(dict(offset=position, error=str(exc)))
        position += size
        count += 1
        if count % 250 == 0:
            print(f'bundles={count} icons={len(exported)} errors={len(errors)}', flush=True)
    report = dict(bundles=count, icons=len(exported), errors=errors,
                  missing=sorted(wanted-exported) if data else [])
    (out/'icon-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lpak', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--data', type=Path, help='Export map, enemy, element, career and quality art referenced by config')
    args = parser.parse_args()
    extract(args.lpak, args.out, args.data)
