import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'books'))
import install_assets


URL = ('https://github.com/blaghtayt-alt/iman-companion/releases/download/'
       'book-assets-v2/pinned.zip')
TOKEN = 'test-token-must-not-appear-in-errors'


def archive_bytes(name='nested/font.ttf', value=b'exact approved font bytes'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(name, value)
    return buffer.getvalue()


def release_metadata(**asset_changes):
    asset = {'name': 'pinned.zip', 'browser_download_url': URL, 'id': 717550662}
    asset.update(asset_changes)
    return {'tag_name': 'book-assets-v2', 'assets': [asset]}


class InstallAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / 'download.zip'

    def install(self, content, *, digest=None):
        (self.root / 'books').mkdir(exist_ok=True)
        configuration = {'archives': [{
            'url': URL,
            'sha256': digest or hashlib.sha256(content).hexdigest(),
            'destination': 'books/assets/fonts',
        }]}
        (self.root / 'books/assets.json').write_text(json.dumps(configuration), encoding='utf-8')
        with patch.object(sys, 'argv', ['install_assets.py', '--root', str(self.root)]):
            install_assets.main()

    def fake_gh(self, content, metadata=None):
        metadata = release_metadata() if metadata is None else metadata

        def run(command, **kwargs):
            if '/releases/tags/' in command[4]:
                return subprocess.CompletedProcess(command, 0, json.dumps(metadata).encode(), b'')
            kwargs['stdout'].write(content)
            return subprocess.CompletedProcess(command, 0, None, b'')
        return run

    def test_authenticated_api_resolves_exact_asset_and_preserves_binary_bytes(self):
        content = archive_bytes()
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', side_effect=self.fake_gh(content)) as run, \
                patch.object(install_assets.urllib.request, 'urlopen') as public:
            install_assets.download_archive(URL, self.destination)
        self.assertEqual(self.destination.read_bytes(), content)
        public.assert_not_called()
        self.assertEqual(run.call_count, 2)
        metadata_call, asset_call = run.call_args_list
        self.assertEqual(metadata_call.args[0], [
            'gh', 'api', '--hostname', 'github.com',
            'repos/blaghtayt-alt/iman-companion/releases/tags/book-assets-v2',
            '-H', 'Accept: application/vnd.github+json',
        ])
        self.assertEqual(asset_call.args[0], [
            'gh', 'api', '--hostname', 'github.com',
            'repos/blaghtayt-alt/iman-companion/releases/assets/717550662',
            '-H', 'Accept: application/octet-stream',
        ])
        self.assertEqual(metadata_call.kwargs['timeout'], 60)
        self.assertEqual(asset_call.kwargs['timeout'], 300)
        self.assertNotIn(TOKEN, repr(run.call_args_list))

    def test_no_token_keeps_original_public_url_and_bounds_reads(self):
        content = archive_bytes()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(install_assets.urllib.request, 'urlopen', return_value=io.BytesIO(content)) as public, \
                patch.object(install_assets.subprocess, 'run') as run:
            install_assets.download_archive(URL, self.destination)
        self.assertEqual(self.destination.read_bytes(), content)
        public.assert_called_once_with(URL, timeout=60)
        run.assert_not_called()

    def test_token_is_not_forwarded_to_non_github_public_host(self):
        public_url = 'https://example.org/pinned.zip'
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.urllib.request, 'urlopen', return_value=io.BytesIO(b'bytes')) as public, \
                patch.object(install_assets.subprocess, 'run') as run:
            install_assets.download_archive(public_url, self.destination)
        public.assert_called_once_with(public_url, timeout=60)
        run.assert_not_called()

    def test_wrong_name_url_tag_duplicate_or_invalid_id_stops_before_download(self):
        duplicate = release_metadata()
        duplicate['assets'].append(dict(duplicate['assets'][0]))
        wrong_tag = release_metadata()
        wrong_tag['tag_name'] = 'another-release'
        for metadata in [release_metadata(name='different.zip'),
                         release_metadata(browser_download_url=URL + '?changed=true'),
                         release_metadata(id=0), release_metadata(id=True),
                         duplicate, wrong_tag, {'assets': []}]:
            with self.subTest(metadata=metadata), \
                    patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                    patch.object(install_assets.subprocess, 'run', side_effect=self.fake_gh(b'bad', metadata)) as run:
                with self.assertRaises(install_assets.AssetDownloadError):
                    install_assets.download_archive(URL, self.destination)
                self.assertEqual(run.call_count, 1)
                self.assertFalse(self.destination.exists())

    def test_malformed_metadata_stops_before_download(self):
        result = subprocess.CompletedProcess([], 0, b'not json', b'')
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(install_assets.AssetDownloadError, 'Invalid GitHub release metadata'):
                install_assets.download_archive(URL, self.destination)
        self.assertEqual(run.call_count, 1)

    def test_api_http_errors_fail_without_downgrade_retry_or_secret_output(self):
        for status in (403, 404, 504):
            error = f'gh: signed redirect https://example.org/?token={TOKEN} (HTTP {status})'.encode()
            result = subprocess.CompletedProcess([], 1, b'', error)
            with self.subTest(status=status), \
                    patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                    patch.object(install_assets.subprocess, 'run', return_value=result) as run, \
                    patch.object(install_assets.urllib.request, 'urlopen') as public:
                with self.assertRaisesRegex(install_assets.AssetDownloadError, f'HTTP {status}') as caught:
                    install_assets.download_archive(URL, self.destination)
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertEqual(run.call_count, 1)
                public.assert_not_called()

    def test_api_download_timeout_is_bounded_and_does_not_extract_partial_archive(self):
        content = archive_bytes()

        def timeout_after_metadata(command, **kwargs):
            if '/releases/tags/' in command[4]:
                return subprocess.CompletedProcess(command, 0, json.dumps(release_metadata()).encode(), b'')
            kwargs['stdout'].write(content[:20])
            raise subprocess.TimeoutExpired(command, kwargs['timeout'], stderr=TOKEN.encode())

        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', side_effect=timeout_after_metadata) as run:
            with self.assertRaisesRegex(install_assets.AssetDownloadError, 'timed out after 300 seconds') as caught:
                self.install(content)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(run.call_count, 2)
        self.assertFalse((self.root / 'books/assets/fonts/nested/font.ttf').exists())

    def test_token_without_gh_fails_explicitly_without_public_downgrade(self):
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', side_effect=FileNotFoundError), \
                patch.object(install_assets.urllib.request, 'urlopen') as public:
            with self.assertRaisesRegex(install_assets.AssetDownloadError, 'requires the GitHub CLI'):
                install_assets.download_archive(URL, self.destination)
        public.assert_not_called()

    def test_public_transfer_deadline_stops_slow_download(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(install_assets.urllib.request, 'urlopen', return_value=io.BytesIO(b'slow')), \
                patch.object(install_assets.time, 'monotonic', side_effect=[0, 301]):
            with self.assertRaisesRegex(install_assets.AssetDownloadError, 'transfer deadline'):
                install_assets.download_archive(URL, self.destination)

    def test_valid_authenticated_bytes_pass_original_hash_and_extract_nested_file(self):
        content = archive_bytes()
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', side_effect=self.fake_gh(content)):
            self.install(content)
        self.assertEqual((self.root / 'books/assets/fonts/nested/font.ttf').read_bytes(),
                         b'exact approved font bytes')

    def test_wrong_authenticated_hash_does_not_overwrite_existing_file(self):
        approved = archive_bytes(value=b'approved font')
        changed = archive_bytes(value=b'changed font')
        target = self.root / 'books/assets/fonts/nested/font.ttf'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'previous verified font')
        with patch.dict(os.environ, {'GH_TOKEN': TOKEN}, clear=True), \
                patch.object(install_assets.subprocess, 'run', side_effect=self.fake_gh(changed)) as run:
            with self.assertRaisesRegex(ValueError, 'Asset archive hash mismatch'):
                self.install(approved)
        self.assertEqual(target.read_bytes(), b'previous verified font')
        self.assertEqual(run.call_count, 2)

    def test_truncated_public_archive_fails_hash_before_extraction(self):
        approved = archive_bytes()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(install_assets.urllib.request, 'urlopen', return_value=io.BytesIO(approved[:-10])):
            with self.assertRaisesRegex(ValueError, 'Asset archive hash mismatch'):
                self.install(approved)
        self.assertFalse((self.root / 'books/assets/fonts/nested/font.ttf').exists())

    def test_original_archive_path_escape_guard_remains_in_effect(self):
        content = archive_bytes(name='../escaped.ttf')
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(install_assets.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
            with self.assertRaisesRegex(ValueError, 'Archive path escapes destination'):
                self.install(content)
        self.assertFalse((self.root / 'books/assets/escaped.ttf').exists())


if __name__ == '__main__':
    unittest.main()
