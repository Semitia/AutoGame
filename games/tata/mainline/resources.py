"""Install versioned, account-independent workbench resources from the checkout."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = Path(__file__).with_name('assets') / 'mainline-0.50.1.zip'
MANIFEST = BUNDLE.with_suffix('.json')
RUNTIME_ROOT = ROOT / 'runtime/tata'
_ready = False


def shared_resource(name):
    """Explicit allowlist: never package profiles, observations or input geometry."""
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        return False
    return any(name.startswith(prefix) and path.suffix in suffixes for prefix, suffixes in (
        ('research/decoded-0.50.1/', {'.luae', '.pbe'}),
        ('research/data-bytecode-0.50.1/', {'.json'}),
        ('research/dataset-bytecode-0.50.1/', {'.json'}),
        ('mainline/art/', {'.png'}),
        ('mainline/icons/', {'.png'}),
    ))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build_bundle(runtime=RUNTIME_ROOT, bundle=BUNDLE, provenance=None):
    runtime, bundle = Path(runtime), Path(bundle)
    paths = sorted(p for p in runtime.rglob('*') if p.is_file() and
                   shared_resource(p.relative_to(runtime).as_posix()))
    if not paths:
        raise ValueError('没有可打包的公共资源')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            info = zipfile.ZipInfo(path.relative_to(runtime).as_posix(), (2026, 10, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    manifest = dict(schema=1, version='0.50.1', files=len(paths),
                    unpacked_bytes=sum(p.stat().st_size for p in paths),
                    sha256=sha256(bundle), sources=provenance or [])
    bundle.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def ensure_resources(runtime=RUNTIME_ROOT, bundle=BUNDLE, manifest=MANIFEST, progress=None):
    runtime, bundle, manifest = Path(runtime).resolve(), Path(bundle), Path(manifest)
    if not bundle.is_file() or not manifest.is_file():
        raise FileNotFoundError('仓库缺少主线公共资源包，请更新完整仓库（包含 games/tata/mainline/assets）。无需旧电脑的账号文件。')
    metadata = json.loads(manifest.read_text(encoding='utf-8'))
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [entry.filename.casefold() for entry in entries]
        if (len(entries) != metadata['files'] or len(set(names)) != len(names) or
                any(not shared_resource(entry.filename) for entry in entries)):
            raise ValueError('公共资源包目录校验失败')
        missing = []
        for entry in entries:
            target = (runtime / entry.filename).resolve()
            if not target.is_relative_to(runtime):
                raise ValueError('公共资源目标超出运行目录')
            if not target.is_file() or target.stat().st_size != entry.file_size:
                missing.append((entry, target))
        if not missing:
            return 0
        if sha256(bundle) != metadata['sha256']:
            raise ValueError('公共资源包校验失败，请重新拉取 games/tata/mainline/assets')
        for index, (entry, target) in enumerate(missing):
            if progress and index % 100 == 0:
                progress(f'首次启动：正在准备公共资源 {index + 1}/{len(missing)}…')
            target.parent.mkdir(parents=True, exist_ok=True)
            # Each file becomes visible only after CRC-checked extraction completes.
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(archive.read(entry))
                except Exception:
                    stream.close()
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return len(missing)


def ensure_default_resources(progress=None):
    global _ready
    if not _ready:
        ensure_resources(progress=progress)
        _ready = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    print(build_bundle() if args.build else f'已准备 {ensure_resources(progress=print)} 个公共资源文件')
