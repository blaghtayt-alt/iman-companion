"""Read-only reconciliation of published book tables and optional live downloads.

This checks recorded release identities, not book approval or rendering. The
existing publisher remains the only writer. Remote checks are opt-in and their
scope is explicit in the report; HTTP availability does not rehash book bodies.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen
import argparse
import copy
import hashlib
import io
import json
import re
import subprocess
import sys

sys.dont_write_bytecode = True
CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / 'books'))
from book_content_coverage import download_coverage
from download_page import (REPO, SCHEMA as BUNDLE_SCHEMA, fingerprint, inventory,
                           verified_bundle)
from download_tables import COPY, download_labels, merge_readme, release_url, render_ready
from locale_copy import NATIVE_DIGITS, locale
from preparation_copy import LIMITED
from published_library import (HEX, SCHEMA as LIBRARY_SCHEMA, asset_names,
                               catalog_members, current, inside,
                               limited_continuity, previous_edition_available, read, scope_key, verify_pair)
from source_update_status import audit as source_update_audit, public_projection
from check_app_book_coverage import member_ids
from temporary_test_labels import decorate_catalog_row

SCHEMA = 'iman-book-download-health-v1'
STATIC_FILES = ('index.html', 'books.mjs', 'books.css', 'copy.mjs', 'update-status.json')
TIMEOUT = 25


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized(value):
    # Coverage numbers use tuples in memory and arrays in the committed JSON.
    return json.loads(json.dumps(value, ensure_ascii=False))


def difference(expected, actual, path='catalog'):
    """Return the first useful mismatch, including identity/order substitutions."""
    if type(expected) is not type(actual):
        return path + ' (type)'
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return path + ' (keys)'
        for key in expected:
            if expected[key] != actual[key]:
                return difference(expected[key], actual[key], path + '.' + key)
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return path + ' (length)'
        for i, (left, right) in enumerate(zip(expected, actual)):
            if left != right:
                return difference(left, right, f'{path}[{i}]')
    return path


def recorded_inventory(root):
    library = read(root / 'books/published-library.json')
    if library.get('schema') != LIBRARY_SCHEMA or not library.get('entries'):
        raise ValueError('Missing or invalid published book registry')
    ready, entries = {}, {}
    for entry in library['entries']:
        book = entry['book']
        key = scope_key(book)
        if key in ready:
            raise ValueError(f'Duplicate published scope: {key}')
        ids = member_ids(entry, key)
        if book.get('exportVerified') is not True or book.get('previewOnly') is not False:
            raise ValueError(f'Unverified production record: {key}')
        tag = entry['releaseTag']
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', tag):
            raise ValueError(f'Invalid release tag: {key}')
        names = asset_names(book)
        for _, hash_key in names:
            if not HEX.fullmatch(book.get(hash_key, '')):
                raise ValueError(f'Missing exact published hash: {key}/{hash_key}')
        retained = None
        if current(root, entry):
            rows, _ = catalog_members(root, key)
            if ids != {str(row['id']) for row in rows}:
                raise ValueError(f'Current edition omits selected identities: {key}')
        elif limited_continuity(root, entry):
            retained = {'state': 'verified-limited-edition', 'updatePending': True,
                        'includedUnitIds': entry['snapshot']['unitIds'], 'newMaterialsIncluded': False}
        elif previous_edition_available(root, entry):
            retained = {'state': 'previous-published-edition', 'updatePending': True,
                        'includedUnitIds': entry['snapshot']['unitIds'], 'newMaterialsIncluded': False,
                        'currentSourceVerified': False}
        else:
            raise ValueError(f'Published snapshot is stale or withdrawn: {key}')
        if entry.get('availability') != retained:
            raise ValueError(f'Recorded availability needs publisher reconciliation: {key}')
        item = copy.deepcopy(book)
        item.pop('availability', None)
        for field, (name, _) in zip(('download', 'pdfDownload'), names):
            expected = release_url(REPO, tag, name)
            if field in book and book[field] != expected:
                raise ValueError(f'Recorded URL differs from its immutable release: {key}/{field}')
            item[field] = expected
        if retained:
            item['availability'] = retained
        ready[key], entries[key] = item, entry
    return ready, entries


def recorded_bundles(root, ready):
    manifest = read(root / 'books/published-bundles.json')
    if manifest.get('schema') != BUNDLE_SCHEMA:
        raise ValueError('Invalid published bundle registry')
    entries, links = manifest['languages'], {}
    expected_languages = {language for language in COPY if inventory(ready, language)}
    if set(entries) != expected_languages:
        raise ValueError('Bundle languages differ from the complete published language inventory')
    for language, entry in entries.items():
        books = inventory(ready, language)
        parts = [{k: b[k] for k in ('language', 'collection', 'sha256', 'pdfSha256')} for b in books]
        if entry.get('parts') != parts or entry.get('fingerprint') != fingerprint(root, books):
            raise ValueError(f'Bundle membership or merger fingerprint changed: {language}')
        tag = entry['releaseTag']
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', tag):
            raise ValueError(f'Invalid bundle release tag: {language}')
        base = f'Iman_Companion_{language}_all-books.'
        wanted = {base + 'zip'} | ({base + 'pdf', base + 'docx'} if len(books) > 1 else set())
        assets = entry['assets']
        if len(assets) != len(wanted) or {a['name'] for a in assets} != wanted:
            raise ValueError(f'Unexpected or duplicate bundle assets: {language}')
        for asset in assets:
            if (not HEX.fullmatch(asset.get('sha256', '')) or type(asset.get('bytes')) is not int
                    or asset['bytes'] <= 0):
                raise ValueError(f'Invalid bundle asset hash or size: {language}')
        zip_files = {name: b[hash_key] for b in books for name, hash_key in asset_names(b)}
        if entry.get('verification', {}).get('zipFiles') != zip_files:
            raise ValueError(f'ZIP contents differ from published Word/PDF pairs: {language}')
        links[language] = {
            'zip': release_url(REPO, tag, base + 'zip'),
            'docx': release_url(REPO, tag, base + 'docx') if len(books) > 1 else books[0]['download'],
            'pdf': release_url(REPO, tag, base + 'pdf') if len(books) > 1 else books[0]['pdfDownload'],
            'parts': len(books)}
    return links, entries


def expected_catalog(root, ready, bundles, coverage):
    conf, languages = read(root / 'books/config.json'), {}
    for language, labels in COPY.items():
        settings = conf['languages'][language]
        font = conf['fonts'][settings['font']]
        row = {'language': language, 'name': locale(language)['nativeName'], 'brand': settings['brand'],
               'title': labels[0], 'included': labels[4], 'downloads': download_labels(language),
               'digits': NATIVE_DIGITS.get(language, '0123456789'),
               'font': {key: 'assets/fonts/' + font['sha256'][weight] + '.ttf'
                        for weight, key in [('Regular', 'regular'), ('Bold', 'bold')]},
               'books': [], 'bundle': bundles.get(language)}
        for book in inventory(ready, language):
            scope = coverage[(language, book['collection'])]
            unit_labels = scope['presentation']['unitLabels']
            item = {'language': language, 'collection': book['collection'],
                    'title': book['collectionLabel'] if book.get('editionScope') else settings['titles'][book['collection']],
                    'cover': 'assets/covers/' + book['pdfSha256'] + '.webp',
                    'docx': book['download'], 'pdf': book['pdfDownload'],
                    'sha256': book['sha256'], 'pdfSha256': book['pdfSha256'],
                    'units': len(book['units']), 'pages': book.get('pages'), 'audio': len(book.get('audioPanels', [])),
                    'coverage': scope,
                    'contents': [{'id': unit['id'], 'title': unit['title'],
                                  **({'numberLabel': unit_labels[str(unit['id'])]}
                                     if str(unit['id']) in unit_labels else {})} for unit in book['units']]}
            if book.get('availability'):
                item.update(availability=book['availability'], statusLabel=LIMITED[language])
            row['books'].append(item)
        decorate_catalog_row(row, inventory(ready, language))
        languages[language] = row
    return normalized({'schema': 'iman-book-downloads-v1', 'languages': languages})


def check_bootstrap(files):
    """Bind the actual browser entry point to the static files we check."""
    class EntryPoint(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts, self.styles, self.resources = [], [], []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'script':
                self.scripts.append((attrs.get('type'), attrs.get('src')))
            if tag == 'link' and attrs.get('rel') == 'stylesheet':
                self.styles.append(attrs.get('href'))
            self.resources.extend(attrs[key] for key in ('src', 'href') if attrs.get(key))

    html = EntryPoint()
    html.feed(files['index.html'].decode('utf8'))
    if html.scripts != [('module', 'books.mjs')] or html.styles != ['books.css']:
        raise ValueError('Browser bootstrap does not load the checked books module and stylesheet')
    if any(path.removeprefix('./') not in files for path in html.resources):
        raise ValueError('Browser entry point references an unchecked or missing resource')
    dependencies = []
    for name in ('books.mjs', 'copy.mjs'):
        source = files[name].decode('utf8')
        dependencies += re.findall(r'\bfrom\s*[\'"]([^\'"]+)[\'"]', source)
        dependencies += re.findall(r'\bimport\s*(?:\(\s*)?[\'"]([^\'"]+)[\'"]', source)
        dependencies += re.findall(r'\bfetch\(\s*[\'"]([^\'"]+)[\'"]', source)
    if './copy.mjs' not in dependencies or 'catalog.json' not in dependencies:
        raise ValueError('Browser module no longer loads the checked labels and catalog')
    css = files['books.css'].decode('utf8')
    dependencies += [value.strip(' \"\'') for value in re.findall(r'url\(([^)]+)\)', css)]
    if any(path.removeprefix('./') not in files for path in dependencies):
        raise ValueError('Browser module or stylesheet references an unchecked resource')


def checked_local_files(root, ready, bundles):
    conf = read(root / 'books/config.json')
    coverage = download_coverage(root, ready, conf=conf)
    expected = expected_catalog(root, ready, bundles, coverage)
    actual = read(root / 'docs/books/catalog.json')
    if datetime.fromisoformat(actual['updated']).utcoffset() is None:
        raise ValueError('Catalog update timestamp has no timezone')
    if expected != {k: v for k, v in actual.items() if k != 'updated'}:
        raise ValueError('Catalog differs from published inventory at ' +
                         difference(expected, {k: v for k, v in actual.items() if k != 'updated'}))
    table, pages = render_ready(conf, ready, REPO, bundles=bundles, coverage=coverage)
    original = (root / 'README.md').read_text(encoding='utf8')
    if merge_readme(original, table) != original:
        raise ValueError('Root README download table differs from the published inventory')
    if {p.parent.name for p in (root / 'books/downloads').glob('*/README.md')} != set(pages):
        raise ValueError('Native download pages do not match the configured languages')
    for language, body in pages.items():
        heading, rest = body.split('\n', 1)
        link = f'[{COPY[language][0]}](https://blaghtayt-alt.github.io/iman-companion/books/?lang={language})'
        expected_page = heading + '\n\n<!-- IMAN-DOWNLOAD-INTERFACE -->\n' + link + '\n' + rest
        if (root / 'books/downloads' / language / 'README.md').read_text(encoding='utf8') != expected_page:
            raise ValueError(f'Native download table or interface link differs: {language}')
    assets = {path for row in expected['languages'].values() for path in row['font'].values()}
    assets.update(book['cover'] for row in expected['languages'].values() for book in row['books'])
    files = {}
    for relative in sorted(assets | set(STATIC_FILES) | {'catalog.json'}):
        path = inside(root / 'docs/books', relative)
        raw = path.read_bytes()
        if not raw:
            raise ValueError(f'Empty site file: {relative}')
        if relative.startswith('assets/fonts/') and digest(raw) != path.stem:
            raise ValueError(f'Public font bytes differ from the pinned font hash: {relative}')
        if relative.startswith('assets/covers/'):
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as cover:
                if cover.format != 'WEBP' or not (0 < cover.width <= 4096 and 0 < cover.height <= 4096):
                    raise ValueError(f'Invalid cover image format or dimensions: {relative}')
                cover.load()
        files[relative] = raw
    check_bootstrap(files)
    return files, len(assets), len(pages)


def fetch_release(tag):
    process = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/tags/{tag}'],
                             capture_output=True, text=True, timeout=TIMEOUT)
    if process.returncode:
        raise ValueError(f'GitHub release metadata unavailable: {tag} (exit {process.returncode})')
    return json.loads(process.stdout)


def fetch_site(url, expected_size):
    request = Request(url, headers={'User-Agent': 'iman-book-download-health', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200 or urlparse(response.url).scheme != 'https':
            raise ValueError('Site response is not HTTPS 200')
        raw = response.read(expected_size + 1)
    return raw


def probe_download(url, expected_size=None):
    """Check public transport without credentials or downloading full books."""
    headers = {'User-Agent': 'iman-book-download-health'}
    method = 'HEAD'
    try:
        response = urlopen(Request(url, headers=headers, method=method), timeout=TIMEOUT)
    except HTTPError as error:
        if error.code != 405:
            raise
        error.close()
        method = 'GET bytes=0-0'
        response = urlopen(Request(url, headers={**headers, 'Range': 'bytes=0-0'}), timeout=TIMEOUT)
    with response:
        if response.status not in ({200} if method == 'HEAD' else {200, 206}):
            raise ValueError(f'Unexpected download HTTP status: {response.status}')
        final = urlparse(response.url)
        if final.scheme != 'https' or (final.hostname != 'github.com' and
                                      not (final.hostname or '').endswith('.githubusercontent.com')):
            raise ValueError('Download redirects outside the expected HTTPS GitHub asset hosts')
        if 'text/html' in response.headers.get('Content-Type', '').lower():
            raise ValueError('Download returned an HTML page')
        disposition = Message()
        disposition['Content-Disposition'] = response.headers.get('Content-Disposition', '')
        filename = disposition.get_filename()
        if filename != Path(urlparse(url).path).name:
            raise ValueError('Download attachment filename differs from the requested release asset')
        length = response.headers.get('Content-Length')
        size = int(length) if length and length.isdigit() else None
        if response.status == 206:
            match = re.fullmatch(r'bytes 0-0/(\d+)', response.headers.get('Content-Range', ''))
            if not match:
                raise ValueError('Range response does not identify the complete asset size')
            size = int(match[1])
        if size == 0 or (expected_size is not None and size is not None and size != expected_size):
            raise ValueError('Download Content-Length differs from the recorded release size')
        if method != 'HEAD' and not response.read(1):
            raise ValueError('Range download returned no bytes')
        return {'method': method, 'status': response.status, 'bytes': size,
                'filename': filename, 'finalHost': final.hostname}


def parallel_check(items, operation, check, errors):
    passed = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(operation, key, value): key for key, value in items.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                passed.append({'path': key, **(future.result() or {})})
            except Exception as error:
                errors.append({'check': check, 'path': key, 'message': str(error)})
    return sorted(passed, key=lambda row: row['path'])


def audit(root, *, site_url=None, verify_releases=False, verify_downloads=False,
          release_fetch=None, site_fetch=None, download_probe=None):
    root = Path(root).resolve()
    flags = {'local': True, 'releaseMetadata': verify_releases,
             'publicDownloadHTTP': verify_downloads, 'deployedSite': bool(site_url)}
    report = {'schema': SCHEMA, 'auditedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'repositoryCommit': None, 'passed': False, 'scope': flags, 'counts': {},
              'checks': {key: {'status': 'pending' if enabled else 'not-requested'} for key, enabled in flags.items()},
              'errors': [], 'limitations': [
                  'Local checks reconcile recorded approval and source snapshots; they do not create approval.',
                  'Release metadata checks compare GitHub asset digests; HTTP checks do not rehash binary book or bundle bodies.',
                  'Site checks compare deployed bytes and bootstrap references; they do not simulate browser layout or interaction.',
                  'The caller must detect a concurrent main-branch update during the audit.']}
    process = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if process.returncode == 0:
        report['repositoryCommit'] = process.stdout.strip()
    errors = report['errors']
    try:
        ready, entries = recorded_inventory(root)
        bundles, bundle_entries = recorded_bundles(root, ready)
        files, assets, pages = checked_local_files(root, ready, bundles)
        urls = {b[field]: None for b in ready.values() for field in ('download', 'pdfDownload')}
        for entry in bundle_entries.values():
            urls.update({release_url(REPO, entry['releaseTag'], a['name']): a['bytes'] for a in entry['assets']})
        report['counts'] = {'languages': len(COPY), 'bookPairs': len(ready), 'bundles': len(bundles),
                            'downloadURLs': len(urls), 'nativePages': pages, 'siteAssets': assets}
        report['checks']['local'] = {'status': 'pass', **report['counts']}
    except Exception as error:
        errors.append({'check': 'local', 'path': str(root), 'message': str(error)})
        for key, enabled in flags.items():
            if enabled:
                report['checks'][key]['status'] = 'fail' if key == 'local' else 'blocked-by-local-failure'
        return report
    # Source currency is still a failing gate. It must not prevent independent
    # verification of the explicitly old, hash-bound public edition or site.
    report['scope']['sourceCurrency'] = True
    try:
        source = source_update_audit(root)
        expected_status = public_projection(source, read(root / 'docs/books/catalog.json'))
        actual_status = read(root / 'docs/books/update-status.json')
        if actual_status != expected_status:
            raise ValueError('Public pending status differs from the current sources and exact published hashes')
        pending = [{key: row.get(key) for key in ('language', 'collection', 'state', 'nextAction')}
                   for row in source['scopes'] if row['updatePending']]
        report['checks']['sourceCurrency'] = {'status': 'pending' if pending else 'pass',
            'pendingScopes': pending, 'sourceApprovalCreated': False}
        report['counts']['pendingSourceScopes'] = len(pending)
        if pending:
            errors.append({'check': 'sourceCurrency', 'path': 'docs/books/update-status.json',
                           'message': f'{len(pending)} source updates remain pending; see each scope nextAction.'})
    except Exception as error:
        report['checks']['sourceCurrency'] = {'status': 'fail'}
        errors.append({'check': 'sourceCurrency', 'path': 'docs/books/update-status.json', 'message': str(error)})
    site_results = []
    if site_url:
        parsed = urlparse(site_url)
        site_transport = site_fetch or fetch_site
        def match_file(relative, raw):
            actual = site_transport(urljoin(site_url.rstrip('/') + '/', quote(relative, safe='/')), len(raw))
            if actual != raw:
                raise ValueError('Deployed bytes differ from this checkout (possibly awaiting Pages propagation)')
            return {'sha256': digest(raw), 'bytes': len(raw)}
        try:
            if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError('Expected an HTTPS site directory without credentials, query or fragment')
            # A newly committed catalog may not have reached Pages yet. Check
            # it first so an outer propagation retry does not repeat 144 HEADs.
            site_results.append({'path': 'catalog.json', **match_file('catalog.json', files['catalog.json'])})
        except Exception as error:
            errors.append({'check': 'deployedSite', 'path': 'catalog.json', 'message': str(error)})
            report['checks']['deployedSite'] = {'status': 'fail', 'checkedFiles': 0, 'expectedFiles': len(files)}
            for key in ('releaseMetadata', 'publicDownloadHTTP'):
                if flags[key]:
                    report['checks'][key]['status'] = 'blocked-by-site-catalog'
            return report
    if verify_releases:
        cache = {}
        fetch = release_fetch or fetch_release
        def release(tag):
            if tag not in cache:
                try:
                    cache[tag] = fetch(tag)
                except Exception as error:
                    cache[tag] = error
            if isinstance(cache[tag], Exception):
                raise cache[tag]
            return cache[tag]
        checked = 0
        for key, entry in entries.items():
            try:
                remote = release(entry['releaseTag'])
                verify_pair(entry, REPO, remote)
                for asset in remote['assets']:
                    if asset.get('browser_download_url') in urls:
                        urls[asset['browser_download_url']] = asset['size']
                checked += 1
            except Exception as error:
                errors.append({'check': 'releaseMetadata', 'path': '/'.join(key), 'message': str(error)})
        for language, entry in bundle_entries.items():
            try:
                verified_bundle(entry, inventory(ready, language), REPO, release)
                checked += 1
            except Exception as error:
                errors.append({'check': 'releaseMetadata', 'path': language + '/bundle', 'message': str(error)})
        report['checks']['releaseMetadata'] = {'status': 'fail' if any(e['check'] == 'releaseMetadata' for e in errors) else 'pass',
                                                'checkedRecords': checked, 'expectedRecords': len(entries) + len(bundle_entries),
                                                'releaseTags': len(cache)}
    if verify_downloads:
        results = parallel_check(urls, download_probe or probe_download, 'publicDownloadHTTP', errors)
        report['checks']['publicDownloadHTTP'] = {'status': 'pass' if len(results) == len(urls) else 'fail',
                                                  'checkedURLs': len(results), 'expectedURLs': len(urls), 'results': results}
    if site_url:
        results = site_results + parallel_check({p: raw for p, raw in files.items() if p != 'catalog.json'},
                                                match_file, 'deployedSite', errors)
        report['checks']['deployedSite'] = {'status': 'pass' if len(results) == len(files) else 'fail',
                                           'checkedFiles': len(results), 'expectedFiles': len(files), 'results': results}
    report['passed'] = not errors
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=CODE_ROOT)
    parser.add_argument('--json', type=Path, help='Report path outside the repository')
    parser.add_argument('--site-url', help='Exact HTTPS deployed books directory')
    parser.add_argument('--verify-releases', action='store_true', help='Verify live GitHub release metadata using gh')
    parser.add_argument('--verify-downloads', action='store_true', help='Check every public download via HEAD; Range GET only on HTTP 405')
    args = parser.parse_args()
    if args.json and args.json.resolve().is_relative_to(args.root.resolve()):
        parser.error('--json must be outside the repository; the health check never changes managed files')
    result = audit(args.root, site_url=args.site_url, verify_releases=args.verify_releases,
                   verify_downloads=args.verify_downloads)
    raw = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(raw, encoding='utf8')
        print(json.dumps({'passed': result['passed'], 'counts': result['counts'],
                          'checks': {k: v['status'] for k, v in result['checks'].items()},
                          'errors': len(result['errors']), 'report': str(args.json)}, ensure_ascii=False))
    else:
        print(raw, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
