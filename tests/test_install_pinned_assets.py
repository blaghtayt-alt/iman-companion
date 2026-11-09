"""API transport tests use synthetic pinned ZIPs; production pins stay unchanged."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import install_pinned_assets as assets


def zipped(members):
    stream = BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as package:
        warnings.simplefilter('ignore', UserWarning)
        for name, data in members:
            package.writestr(name, data)
    return stream.getvalue()


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repo'
        (self.root / 'books/assets/covers').mkdir(parents=True)
        (self.root / 'books/assets/fonts').mkdir()
        (self.root / 'books/assets/covers/retained.txt').write_bytes(b'unchanged existing cover')
        (self.root / 'books/assets/fonts/retained.txt').write_bytes(b'unchanged existing font')
        self.payload = {
            1: zipped([('sub/', b''), ('sub/cover.txt', b'pinned cover fixture')]),
            2: zipped([('font.ttf', b'pinned font fixture')]),
        }
        self.fail_downloads = 0
        self.fail_metadata = False
        self.timeout_downloads = False
        self.wrong_metadata = False
        self.wrong_bytes = False
        self.calls, self.pauses = [], []
        self.refresh_manifest()

    def refresh_manifest(self):
        entries = []
        self.metadata = []
        for identifier, destination in ((1, 'covers'), (2, 'fonts')):
            name = destination + '.zip'
            url = assets.PREFIX + 'book-assets-v2/' + name
            digest = hashlib.sha256(self.payload[identifier]).hexdigest()
            entries.append({'url': url, 'sha256': digest, 'destination': 'books/assets/' + destination})
            self.metadata.append({'id': identifier, 'name': name, 'size': len(self.payload[identifier]),
                'digest': 'sha256:' + digest, 'state': 'uploaded', 'browser_download_url': url,
                'url': f'https://api.github.com/repos/{assets.REPOSITORY}/releases/assets/{identifier}'})
        self.manifest = self.root / 'books/assets.json'
        self.manifest.write_text(json.dumps({'archives': entries}, indent=2) + '\n')

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()}

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs['timeout']))
        self.assertEqual(command[:4], ['gh', 'api', '--method', 'GET'])
        endpoint = command[4]
        if '/releases/tags/' in endpoint:
            if self.fail_metadata:
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'SENSITIVE REDIRECT')
            rows = [dict(row) for row in self.metadata]
            if self.wrong_metadata:
                rows[0]['digest'] = 'sha256:' + '0' * 64
            response = {'tag_name': 'book-assets-v2', 'draft': False, 'prerelease': False, 'assets': rows}
            return SimpleNamespace(returncode=0, stdout=json.dumps(response).encode(), stderr=b'')
        self.assertEqual(command[5:], ['-H', 'Accept: application/octet-stream'])
        if self.timeout_downloads:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        if self.fail_downloads:
            self.fail_downloads -= 1
            kwargs['stdout'].write(b'partial transport output')
            return SimpleNamespace(returncode=1, stdout=None, stderr=b'SENSITIVE REDIRECT')
        identifier = int(endpoint.rsplit('/', 1)[1])
        payload = self.payload[identifier]
        if self.wrong_bytes:
            payload = b'X' + payload[1:]
        kwargs['stdout'].write(payload)
        return SimpleNamespace(returncode=0, stdout=None, stderr=b'')

    def install(self):
        return assets.install(self.root, runner=self.runner, pause=self.pauses.append)

    def test_current_production_manifest_pins_are_read_unchanged(self):
        before = (ROOT / 'books/assets.json').read_bytes()
        original, specs = assets.archive_specs(ROOT)
        self.assertEqual(original, before)
        self.assertEqual([row['sha256'] for row in specs], [
            '0fb5ba453dc88b6ed051a3d9ec9b0e4b4eca9f18dbaf2ec26a487e1bffa69377',
            '67446b9c1bcb8d86a212285b306e98213e60f1157fa77d0aca19ccb4dec4bb9e'])
        self.assertEqual({row['destination'] for row in specs}, assets.DESTINATIONS)
        self.assertEqual((ROOT / 'books/assets.json').read_bytes(), before)

    def test_success_uses_exact_api_assets_and_preserves_pins(self):
        before = self.manifest.read_bytes()
        result = self.install()
        self.assertTrue(result['pinsUnchanged'])
        self.assertEqual([row['attempts'] for row in result['archives']], [1, 1])
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertEqual((self.root / 'books/assets/covers/sub/cover.txt').read_bytes(), b'pinned cover fixture')
        self.assertEqual((self.root / 'books/assets/fonts/font.ttf').read_bytes(), b'pinned font fixture')
        self.assertEqual((self.root / 'books/assets/covers/retained.txt').read_bytes(), b'unchanged existing cover')
        self.assertEqual([timeout for _, timeout in self.calls], [30, 180, 30, 180])
        self.assertFalse(list(self.root.glob('.pinned-book-assets-*')))

    def test_transient_download_retries_are_bounded(self):
        self.fail_downloads = 2
        result = self.install()
        self.assertEqual(result['archives'][0]['attempts'], 3)
        self.assertEqual(self.pauses, [1, 2])
        self.assertEqual(sum('/releases/assets/1' in call[0][4] for call in self.calls), 3)

    def test_download_and_metadata_failures_leave_all_assets_unchanged(self):
        for failure in ('fail_downloads', 'fail_metadata', 'timeout_downloads'):
            with self.subTest(failure=failure):
                self.fail_downloads = 4 if failure == 'fail_downloads' else 0
                self.fail_metadata = failure == 'fail_metadata'
                self.timeout_downloads = failure == 'timeout_downloads'
                self.calls.clear(); self.pauses.clear()
                before = self.snapshot()
                with self.assertRaisesRegex(assets.TransportError, 'after 3 attempts') as error:
                    self.install()
                self.assertNotIn('SENSITIVE', str(error.exception))
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.pauses, [1, 2])

    def test_wrong_metadata_or_download_hash_aborts_before_writes(self):
        for failure in ('wrong_metadata', 'wrong_bytes'):
            with self.subTest(failure=failure):
                self.wrong_metadata = failure == 'wrong_metadata'
                self.wrong_bytes = failure == 'wrong_bytes'
                self.calls.clear(); self.pauses.clear()
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.install()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.pauses, [])

    def test_unsafe_zip_inventory_aborts_without_outside_writes(self):
        symlink = zipfile.ZipInfo('link')
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [
            [('../escape.txt', b'bad')], [('/escape.txt', b'bad')],
            [('sub\\escape.txt', b'bad')], [('C:/escape.txt', b'bad')],
            [('file.txt', b'a'), ('file.txt', b'b')],
            [('FILE.txt', b'a'), ('file.txt', b'b')],
            [(symlink, b'../elsewhere')], [('parent', b'a'), ('parent/child', b'b')],
        ]
        for members in cases:
            with self.subTest(members=str(members)):
                # Use the second archive so the first valid archive has already
                # been fully downloaded and staged when preflight rejects this.
                self.payload[2] = zipped(members)
                self.refresh_manifest()
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.install()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((Path(self.temporary.name) / 'escape.txt').exists())

    def test_destination_and_nested_symlinks_are_refused(self):
        external = Path(self.temporary.name) / 'external'
        external.mkdir()
        (external / 'sentinel').write_bytes(b'preserve')
        cover = self.root / 'books/assets/covers'
        shutil.rmtree(cover)
        cover.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install()
        self.assertEqual(self.calls, [])
        cover.unlink(); cover.mkdir()
        (cover / 'sub').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install()
        self.assertEqual(list(external.iterdir()), [external / 'sentinel'])
        self.assertEqual((external / 'sentinel').read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
