"""Reproduce the shared resource bundle from hash-pinned archives; never install APKs.

Normal users need only the checked-in bundle. This is the maintainer rebuild path.
Requires requirements.txt plus UnityPy==1.25.3.
"""
import io
from pathlib import Path
import urllib.request
import zipfile

from resources import RUNTIME_ROOT, build_bundle, sha256

SOURCES = [
    dict(name='tata-0.50.1.apk',
         url='https://vda.lilithcdn.com/10090/2/0.50.1/com.lilithgame.pgame.android.cn/pgame_98fbe6189b7e11f18abe1211e0661fee.apk',
         sha256='281b2645b9e00dfd4ff5b302eeaacc1301d3faa2cee9fb24b34655e559fc5f5e'),
    dict(name='tata-overseas-0.31.11.xapk',
         url='https://d.apkpure.net/b/XAPK/com.farlightgames.pgame.gp?versionCode=2321',
         sha256='55d99255b0ac6eea36f3d6611625ba162be378649686b99ea20952e6f12ac345'),
]


def obtain(source, directory):
    path = directory / source['name']
    if not path.is_file() or sha256(path) != source['sha256']:
        print('下载 ' + source['name'], flush=True)
        temporary = path.with_suffix('.download')
        try:
            with urllib.request.urlopen(source['url'], timeout=60) as response, temporary.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if sha256(temporary) != source['sha256']:
                raise ValueError('下载文件与固定版本 SHA-256 不符：' + source['name'])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def main():
    from decode_package import decode, REFERENCE_SHA256
    from export_config import export
    from build_dataset import build
    from extract_icons import extract
    research = RUNTIME_ROOT / 'research'
    research.mkdir(parents=True, exist_ok=True)
    apk, old = [obtain(source, research) for source in SOURCES]
    reference = research / 'overseas-0.31.11/libigame.so'
    reference.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(old) as archive:
        with zipfile.ZipFile(io.BytesIO(archive.read('config.armeabi_v7a.apk'))) as arm:
            reference.write_bytes(arm.read('lib/armeabi-v7a/libigame.so'))
    if sha256(reference) != REFERENCE_SHA256:
        raise ValueError('参考库哈希不符')
    decoded = research / 'decoded-0.50.1'
    data = research / 'data-bytecode-0.50.1'
    dataset = research / 'dataset-bytecode-0.50.1'
    print('恢复原始配置与字节码…', flush=True)
    report = decode(apk, reference, decoded)
    if report['errors'] or report['decoded'] != 6038:
        raise ValueError('脚本包恢复不完整，请查看 decode-report.json')
    print('导出配置…', flush=True)
    report = export(decoded, data)
    # This pinned source contains 44 non-data configs. They are explicitly reported,
    # and remain available to the original VM; they are never fabricated as JSON.
    if report['total'] != 3166 or report['exported'] != 3122 or len(report['errors']) != 44:
        raise ValueError('配置导出数量不符，请查看 export-report.json')
    print('关联关卡…', flush=True)
    report = build(data, dataset)
    if report['errors'] or report['joined'] != 6400:
        raise ValueError('关卡关联不完整，请查看 dataset-report.json')
    lpak = research / 'inpackage_aa_1.lpak'
    with zipfile.ZipFile(apk) as archive:
        lpak.write_bytes(archive.read('assets/aa/Android/inpackage_aa_1.lpak'))
    print('提取公共图片…', flush=True)
    extract(lpak, RUNTIME_ROOT / 'mainline/art', data)
    print('打包公共资源…', flush=True)
    print(build_bundle(provenance=SOURCES), flush=True)


if __name__ == '__main__':
    main()
