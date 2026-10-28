"""Read only explicitly selected game's cached Unity bundles; fill missing local art.

Does not read account saves, messages or run scripts. Existing exports are kept.
"""
import argparse
import hashlib
import json
from pathlib import Path
import UnityPy
from extract_icons import wanted_art
import os


def discover_tata_caches():
    users=Path(os.environ.get('APPDATA',str(Path.home()/'AppData/Roaming')))/'Tencent/xwechat/radium/users'
    return list(users.glob('*/applet/local/wx6d4a348484faa57b/usr/__GAME_FILE_CACHE'))


def extract(roots, data, out):
    UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.62f3'
    wanted = wanted_art(data)
    out.mkdir(parents=True,exist_ok=True)
    existing = {p.stem for p in out.glob('*.png')}
    files = sorted({p for root in roots for p in root.rglob('*.bundle')},
                   key=lambda p:p.stat().st_mtime,reverse=True)
    added, errors = [], []
    for i,path in enumerate(files):
        try:
            raw=path.read_bytes()
            if not raw.startswith(b'UnityFS\0'): continue
            env=UnityPy.load(raw)
            for obj in env.objects:
                if obj.type.name not in ('Sprite','Texture2D'): continue
                name=obj.peek_name()
                if not name or Path(name).name!=name: continue
                name=Path(name).stem
                if name in existing or name not in wanted: continue
                obj.read().image.save(out/(name+'.png')); existing.add(name)
                added.append(dict(name=name,bundle=path.name,bundle_sha256=hashlib.sha256(raw).hexdigest()))
        except Exception as exc:
            errors.append(dict(bundle=path.name,error=str(exc)))
        if (i+1)%100==0: print(f'bundles={i+1}/{len(files)} added={len(added)} errors={len(errors)}',flush=True)
    report=dict(bundles=len(files),added=added,errors=errors,missing=sorted(wanted-existing))
    (out/'cache-art-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'added={len(added)} missing={len(report["missing"])} errors={len(errors)}')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root',type=Path,action='append',required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); extract(args.cache_root,args.data,args.out)
