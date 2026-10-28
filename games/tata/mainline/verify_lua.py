"""Compile-check recovered Lua without executing any chunk."""
import argparse
import json
from pathlib import Path

from lupa.lua54 import LuaRuntime


def verify(root: Path):
    lua = LuaRuntime(register_eval=False, register_builtins=False, max_memory=256*1024*1024)
    check = lua.eval('''function(data, mode)
        local fn, err = load(data, "verify", mode, {})
        return fn ~= nil, err
    end''')
    errors, total = [], 0
    for path in sorted(root.rglob('*')):
        if path.suffix not in ('.lua', '.luae'):
            continue
        total += 1
        ok, error = check(path.read_bytes(), 'b' if path.suffix == '.luae' else 't')
        if not ok:
            errors.append(dict(path=path.relative_to(root).as_posix(), error=error))
    return dict(total=total, valid=total-len(errors), errors=errors)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"total={report['total']} valid={report['valid']} errors={len(report['errors'])}")
    raise SystemExit(bool(report['errors']))
