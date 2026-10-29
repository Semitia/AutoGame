"""Portability and separation of shared resources from local account state."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from resources import build_bundle, ensure_resources, sha256


class ResourceTests(unittest.TestCase):
    def test_clean_machine_restore_and_preserve_account_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root/'old', root/'new'
            shared = 'research/data-bytecode-0.50.1/Config/Unit.json'
            for relative, content in ((shared, b'{"UnitTable":{}}'),
                                      ('mainline/art/pet.png', b'picture'),
                                      ('mainline/roster.json', b'OLD ACCOUNT'),
                                      ('mainline/live-capture.json', b'PRIVATE'),
                                      ('mainline/autoplay-geometry.json', b'OLD SCREEN')):
                path = source/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            account = target/'mainline/roster.json'
            account.parent.mkdir(parents=True)
            account.write_bytes(b'NEW ACCOUNT')
            bundle = root/'assets/shared.zip'
            manifest = build_bundle(source, bundle)
            self.assertEqual(manifest['files'], 2)
            self.assertEqual(ensure_resources(target, bundle, bundle.with_suffix('.json')), 2)
            self.assertEqual((target/shared).read_bytes(), (source/shared).read_bytes())
            self.assertEqual(account.read_bytes(), b'NEW ACCOUNT')
            self.assertFalse((target/'mainline/live-capture.json').exists())
            self.assertFalse((target/'mainline/autoplay-geometry.json').exists())
            self.assertEqual(ensure_resources(target, bundle, bundle.with_suffix('.json')), 0)
            (target/shared).write_bytes(b'truncated')
            self.assertEqual(ensure_resources(target, bundle, bundle.with_suffix('.json')), 1)

    def test_rejects_corrupt_archive_before_installing_any_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source/mainline/art'
            source.mkdir(parents=True)
            (source/'pet.png').write_bytes(b'picture')
            bundle = root/'shared.zip'
            build_bundle(root/'source', bundle)
            manifest = bundle.with_suffix('.json')
            value = json.loads(manifest.read_text(encoding='utf-8'))
            value['sha256'] = '0'*64
            manifest.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                ensure_resources(root/'target', bundle, manifest)
            self.assertFalse((root/'target').exists())

    def test_rejects_unexpected_or_escaping_entries(self):
        for name in ('mainline/roster.json', 'research/decoded-0.50.1/../../outside.luae'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                bundle = root/'shared.zip'
                with zipfile.ZipFile(bundle, 'w') as archive:
                    archive.writestr(name, b'private or unsafe')
                manifest = bundle.with_suffix('.json')
                manifest.write_text(json.dumps(dict(files=1, sha256=sha256(bundle))), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '目录校验失败'):
                    ensure_resources(root/'target', bundle, manifest)


if __name__ == '__main__':
    unittest.main()
