"""Evaluate recovered Config tables in a restricted Lua VM; export JSON.

Requires lupa.lua54. Numeric Lua keys are preserved as JSON object keys (including
frame numbers); this intentionally does not guess which tables are arrays.
"""
import argparse
import hashlib
import json
from pathlib import Path

from lupa.lua54 import LuaRuntime, lua_type


def read_config(path: Path):
    lua = LuaRuntime(register_eval=False, register_builtins=False, max_memory=128*1024*1024)
    evaluate = lua.eval('''function(source, mode)
        local env = {config = {}}
        local chunk = assert(load(source, "config", mode, env))
        local ticks = 0
        debug.sethook(function()
            ticks = ticks + 1
            if ticks > 10000 then error("instruction budget exceeded") end
        end, "", 1000)
        local ok, err = pcall(chunk)
        debug.sethook()
        if not ok then error(err) end
        return env.config
    end''')
    result = evaluate(path.read_bytes(), 'b' if path.suffix == '.luae' else 't')

    def convert(value, depth=0):
        if depth > 64:
            raise ValueError('Config nesting limit')
        if lua_type(value) == 'table':
            output = {}
            for key, item in value.items():
                if not isinstance(key, (str, int, float, bool)):
                    raise ValueError('Unsupported table key')
                name = ('true' if key else 'false') if isinstance(key, bool) else str(key)
                if name in output:
                    raise ValueError('JSON key collision')
                output[name] = convert(item, depth+1)
            return output
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError('Non-data value in config')

    return convert(result)


def export(source: Path, out: Path):
    out = out.resolve()
    source = source.resolve()
    if out.is_relative_to(source):
        raise ValueError('Output must be outside input')
    out.mkdir(parents=True, exist_ok=True)
    successes, errors = [], []
    pattern = '*.luae' if any((source / 'Config').glob('*.luae')) else '*.lua'
    for path in sorted((source / 'Config').rglob(pattern)):
        relative = path.relative_to(source)
        try:
            data = read_config(path)
            target = out / relative.with_suffix('.json')
            if not target.resolve().is_relative_to(out):
                raise ValueError('Unsafe output path')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            successes.append(dict(path=relative.as_posix(), tables=list(data),
                                  source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        except Exception as exc:
            errors.append(dict(path=relative.as_posix(), error=str(exc)))
    report = dict(total=len(successes)+len(errors), exported=len(successes), errors=errors)
    (out / 'export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'export-index.json').write_text(json.dumps(successes, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = export(args.source, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report['errors']))
