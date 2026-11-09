"""Negative cases for published-table and deployed-download reconciliation."""
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlparse
import copy
import io
import json
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'books'))
import check_book_downloads as health
import download_page


class Response(io.BytesIO):
    def __init__(self, *, status=200, filename='test.pdf', size=4):
        super().__init__(b'data')
        self.status = status
        self.url = 'https://release-assets.githubusercontent.com/asset'
        self.headers = {'Content-Length': str(size), 'Content-Type': 'application/pdf',
                        'Content-Disposition': f'attachment; filename={filename}'}
        self.reads = []

    def read(self, size=-1):
        self.reads.append(size)
        return super().read(size)


class DownloadHealthTests(unittest.TestCase):
    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

    def coverage(self, root, ready, *, conf=None):
        return {key: {'includedIds': [u['id'] for u in book['units']],
                      'includedNumbers': {u['id']: (1, i + 1) for i, u in enumerate(book['units'])},
                      'presentation': {'unitLabels': {}}} for key, book in ready.items()}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(patch.object(health, 'current', return_value=True))
        self.enterContext(patch.object(health, 'limited_continuity', return_value=False))
        self.enterContext(patch.object(health, 'catalog_members', side_effect=lambda root, key:
                                      ([r for r in health.read(root / 'materials/catalog.json')['entries']
                                        if (r['language'], r['scope']) == key], None)))
        self.enterContext(patch.object(health, 'download_coverage', side_effect=self.coverage))
        self.conf = health.read(ROOT / 'books/config.json')
        self.font = b'exact fixture font'
        for font in self.conf['fonts'].values():
            font['sha256'] = dict.fromkeys(('Regular', 'Bold'), health.digest(self.font))
        self.write('books/config.json', self.conf)
        self.entries, catalog = [], []
        for language, collection, ids, titles in [
                ('en', 'hadith', ['essential-01-001', 'essential-01-002'], ['First lesson', 'Second lesson']),
                ('ar', 'articles', ['article-1', 'article-2'], ['المقالة الأولى', 'المقالة الثانية'])]:
            book = {'language': language, 'collection': collection,
                    'collectionLabel': self.conf['languages'][language]['titles'][collection],
                    'file': f'Iman_Companion_{language}_{collection}.docx',
                    'sha256': health.digest((language + 'docx').encode()),
                    'pdfSha256': health.digest((language + 'pdf').encode()),
                    'exportVerified': True, 'previewOnly': False, 'pages': 3,
                    'units': [{'id': ident, 'title': title} for ident, title in zip(ids, titles)]}
            if collection == 'hadith':
                book['hadithEdition'] = 'new-extended'
            members = [{'collection': 'essential-hadith' if collection == 'hadith' else collection,
                        'language': language, 'id': ident} for ident in ids]
            self.entries.append({'releaseTag': 'fixture', 'book': book,
                                 'snapshot': {'unitIds': ids.copy(), 'catalogMemberKeys': members}})
            catalog.extend({**member, 'scope': collection} for member in members)
        self.write('materials/catalog.json', {'entries': catalog})
        self.write('books/published-library.json', {'schema': health.LIBRARY_SCHEMA, 'entries': self.entries})
        (self.root / 'books/merge_public_books.py').write_bytes((ROOT / 'books/merge_public_books.py').read_bytes())
        ready, _ = health.recorded_inventory(self.root)
        bundles = {}
        for language in ('en', 'ar'):
            books = health.inventory(ready, language)
            assets = [{'name': f'Iman_Companion_{language}_all-books.zip', 'bytes': 123,
                       'sha256': health.digest((language + 'zip').encode())}]
            bundles[language] = {'releaseTag': 'fixture-bundles',
                                 'fingerprint': health.fingerprint(self.root, books),
                                 'parts': [{k: b[k] for k in ('language', 'collection', 'sha256', 'pdfSha256')}
                                           for b in books], 'assets': assets,
                                 'verification': {'zipFiles': {name: b[hashkey] for b in books
                                                              for name, hashkey in health.asset_names(b)}}}
        self.write('books/published-bundles.json', {'schema': health.BUNDLE_SCHEMA, 'languages': bundles})
        links, _ = health.recorded_bundles(self.root, ready)
        (self.root / 'README.md').write_text('# Fixture\n', encoding='utf8')
        font_path = 'assets/fonts/' + health.digest(self.font) + '.ttf'
        with patch('book_content_coverage.download_coverage', side_effect=self.coverage), \
                patch.object(download_page, 'font_assets', return_value={'regular': font_path, 'bold': font_path}), \
                patch.object(download_page, 'source_file', return_value=Path('unused.pdf')), \
                patch.object(download_page, 'cover_asset', side_effect=lambda root, pdf, sha: 'assets/covers/' + sha + '.webp'):
            download_page.write_catalog(self.root, self.root / 'unused', ready, links)
        target = self.root / 'docs/books' / font_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.font)
        for book in ready.values():
            target = self.root / 'docs/books/assets/covers' / (book['pdfSha256'] + '.webp')
            target.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            Image.new('RGB', (2, 2), 'white').save(target, format='WEBP')
        for name in health.STATIC_FILES:
            (self.root / 'docs/books' / name).write_bytes((ROOT / 'docs/books' / name).read_bytes())

    def change(self, relative, mutation):
        value = health.read(self.root / relative)
        mutation(value)
        self.write(relative, value)

    def assert_bad(self, text):
        result = health.audit(self.root)
        self.assertFalse(result['passed'])
        self.assertIn(text, result['errors'][0]['message'])

    def releases(self, tag):
        assets = []
        if tag == 'fixture':
            for entry in self.entries:
                assets.extend({'name': name, 'state': 'uploaded', 'size': 100,
                               'digest': 'sha256:' + entry['book'][hashkey],
                               'browser_download_url': health.release_url(health.REPO, tag, name)}
                              for name, hashkey in health.asset_names(entry['book']))
        else:
            for entry in health.read(self.root / 'books/published-bundles.json')['languages'].values():
                assets.extend({'name': a['name'], 'state': 'uploaded', 'size': a['bytes'],
                               'digest': 'sha256:' + a['sha256'],
                               'browser_download_url': health.release_url(health.REPO, tag, a['name'])}
                              for a in entry['assets'])
        return {'tag_name': tag, 'draft': False, 'prerelease': False, 'assets': assets}

    def site(self, url, expected_size):
        relative = urlparse(url).path.removeprefix('/books/')
        return (self.root / 'docs/books' / relative).read_bytes()

    def test_local_only_labels_unchecked_remote_scopes(self):
        result = health.audit(self.root)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['counts']['bookPairs'], 2)
        self.assertEqual(result['counts']['downloadURLs'], 6)
        self.assertEqual(result['checks']['deployedSite']['status'], 'not-requested')
        self.assertEqual(result['checks']['releaseMetadata']['status'], 'not-requested')

    def test_same_count_identity_substitution_in_catalog(self):
        self.change('docs/books/catalog.json', lambda d: d['languages']['en']['books'][0]['contents'][0].update(id='other-lesson'))
        self.assert_bad('contents[0].id')

    def test_current_snapshot_cannot_omit_selected_unit(self):
        def omit(d):
            entry = d['entries'][0]
            entry['book']['units'].pop()
            entry['snapshot']['unitIds'].pop()
            entry['snapshot']['catalogMemberKeys'].pop()
        self.change('books/published-library.json', omit)
        self.assert_bad('omits selected identities')

    def test_wrong_release_url_in_catalog(self):
        self.change('docs/books/catalog.json', lambda d: d['languages']['en']['books'][0].update(docx='https://example.test/wrong.docx'))
        self.assert_bad('.docx')

    def test_wrong_hash_in_catalog(self):
        self.change('docs/books/catalog.json', lambda d: d['languages']['en']['books'][0].update(pdfSha256='0' * 64))
        self.assert_bad('.pdfSha256')

    def test_changed_bundle_member(self):
        self.change('books/published-bundles.json', lambda d: d['languages']['en']['parts'][0].update(sha256='0' * 64))
        self.assert_bad('Bundle membership')

    def test_duplicate_bundle_asset(self):
        self.change('books/published-bundles.json', lambda d: d['languages']['en']['assets'].append(copy.deepcopy(d['languages']['en']['assets'][0])))
        self.assert_bad('duplicate bundle assets')

    def test_root_table_drift(self):
        path = self.root / 'README.md'
        path.write_text(path.read_text().replace('/fixture/', '/wrong/'), encoding='utf8')
        self.assert_bad('Root README')

    def test_native_interface_drift(self):
        path = self.root / 'books/downloads/ja/README.md'
        path.write_text(path.read_text().replace('?lang=ja', '?lang=en'), encoding='utf8')
        self.assert_bad('interface link differs: ja')

    def test_missing_language(self):
        self.change('docs/books/catalog.json', lambda d: d['languages'].pop('ja'))
        self.assert_bad('languages (keys)')

    def test_missing_static_module(self):
        (self.root / 'docs/books/copy.mjs').unlink()
        self.assert_bad('copy.mjs')

    def test_nonempty_broken_cover(self):
        next((self.root / 'docs/books/assets/covers').glob('*.webp')).write_bytes(b'This is not an image')
        self.assert_bad('cannot identify image')

    def test_broken_browser_bootstrap(self):
        path = self.root / 'docs/books/index.html'
        path.write_text(path.read_text().replace('src="books.mjs"', 'src="missing.js"'), encoding='utf8')
        self.assert_bad('Browser bootstrap')

    def test_unchecked_module_dependency(self):
        path = self.root / 'docs/books/books.mjs'
        path.write_text(path.read_text().replace("'./copy.mjs'", "'./missing.mjs'"), encoding='utf8')
        self.assert_bad('checked labels')

    def test_changed_pinned_font(self):
        next((self.root / 'docs/books/assets/fonts').glob('*.ttf')).write_bytes(b'changed')
        self.assert_bad('pinned font hash')

    def test_complete_requested_remote_checks(self):
        result = health.audit(self.root, site_url='https://example.test/books/', verify_releases=True,
                              verify_downloads=True, release_fetch=self.releases, site_fetch=self.site,
                              download_probe=lambda url, size: {'status': 200, 'method': 'HEAD'})
        self.assertTrue(result['passed'], result)
        self.assertTrue(all(c['status'] == 'pass' for c in result['checks'].values()))
        self.assertEqual(result['checks']['publicDownloadHTTP']['checkedURLs'], 6)

    def test_missing_remote_release_asset_fails(self):
        def missing(tag):
            release = self.releases(tag)
            release['assets'].pop()
            return release
        result = health.audit(self.root, verify_releases=True, release_fetch=missing)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['releaseMetadata']['status'], 'fail')

    def test_release_failures_are_fetched_once_per_tag(self):
        calls = []
        def unavailable(tag):
            calls.append(tag)
            raise TimeoutError('Release metadata unavailable')
        result = health.audit(self.root, verify_releases=True, release_fetch=unavailable)
        self.assertFalse(result['passed'])
        self.assertEqual(sorted(calls), ['fixture', 'fixture-bundles'])
        self.assertEqual(result['checks']['releaseMetadata']['checkedRecords'], 0)

    def test_deployed_catalog_mismatch_is_not_success(self):
        def stale(url, size):
            return b'old catalog' if url.endswith('/catalog.json') else self.site(url, size)
        result = health.audit(self.root, site_url='https://example.test/books/', site_fetch=stale)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['deployedSite']['status'], 'fail')
        self.assertEqual([e['path'] for e in result['errors']], ['catalog.json'])

    def test_pages_propagation_stops_before_repeating_release_probes(self):
        with patch.object(health, 'fetch_release') as release, patch.object(health, 'probe_download') as public:
            result = health.audit(self.root, site_url='https://example.test/books/', verify_releases=True,
                                  verify_downloads=True, site_fetch=lambda url, size: b'old catalog')
        self.assertFalse(result['passed'])
        release.assert_not_called()
        public.assert_not_called()
        self.assertEqual(result['checks']['publicDownloadHTTP']['status'], 'blocked-by-site-catalog')

    def test_public_timeout_reports_unverified_not_success(self):
        def unavailable(url, size):
            raise TimeoutError('Public availability could not be verified')
        result = health.audit(self.root, verify_downloads=True, download_probe=unavailable)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['publicDownloadHTTP']['checkedURLs'], 0)
        self.assertEqual(len(result['errors']), result['counts']['downloadURLs'])


class TransportTests(unittest.TestCase):
    URL = 'https://github.com/blaghtayt-alt/iman-companion/releases/download/test/test.pdf'

    def test_head_uses_no_body_and_requires_attachment_identity(self):
        response = Response()
        with patch.object(health, 'urlopen', return_value=response):
            self.assertEqual(health.probe_download(self.URL, 4)['filename'], 'test.pdf')
        self.assertEqual(response.reads, [])
        with patch.object(health, 'urlopen', return_value=Response(filename='wrong.pdf')):
            with self.assertRaisesRegex(ValueError, 'attachment filename'):
                health.probe_download(self.URL, 4)

    def test_range_fallback_only_after_405_and_reads_one_byte(self):
        response = Response(status=206, size=1)
        response.headers['Content-Range'] = 'bytes 0-0/4'
        with patch.object(health, 'urlopen', side_effect=[HTTPError(self.URL, 405, 'no HEAD', {}, None), response]) as fetch:
            self.assertEqual(health.probe_download(self.URL, 4)['method'], 'GET bytes=0-0')
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(response.reads, [1])
        with patch.object(health, 'urlopen', side_effect=HTTPError(self.URL, 404, 'missing', {}, None)) as fetch:
            with self.assertRaises(HTTPError):
                health.probe_download(self.URL)
            self.assertEqual(fetch.call_count, 1)

    def test_site_non_200_is_not_accepted_as_exact_body(self):
        with patch.object(health, 'urlopen', return_value=Response(status=206)):
            with self.assertRaisesRegex(ValueError, 'HTTPS 200'):
                health.fetch_site('https://example.test/books/catalog.json', 4)


if __name__ == '__main__':
    unittest.main()
