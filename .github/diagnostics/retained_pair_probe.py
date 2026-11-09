#!/usr/bin/env python3
"""Read-only production transport smoke test; this cannot publish a book."""
from pathlib import Path
from unittest import mock
import argparse
import hashlib
import json
import os
import sys
import time


PINNED = {
    'language': 'en',
    'collection': 'hadith',
    'file': 'Iman_Companion_en_hadith.docx',
    'sha256': '1b603de7fb024fee6dfdf2d01e6d70db412024ed4d06e3d2ec9b50d38b1e099f',
    'pdfSha256': '22b3c7bf755b8784412b847bec3f669bfa0e3beebb2fa568fd34fee4b536af16',
    'download': 'https://github.com/blaghtayt-alt/iman-companion/releases/download/books-42532552652-1/Iman_Companion_en_hadith.docx',
    'pdfDownload': 'https://github.com/blaghtayt-alt/iman-companion/releases/download/books-42532552652-1/Iman_Companion_en_hadith.pdf',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(event, **details):
    print(json.dumps({'diagnostic': event, **details}, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if root == out or root in out.parents:
        raise ValueError('Diagnostic output must be outside the repository')
    if not os.environ.get('GH_TOKEN'):
        raise ValueError('A normal read-only GitHub token is required for the live probe')
    sys.path.insert(0, str(root / 'books'))
    import download_page
    import install_assets

    registry = json.loads((root / 'books/published-library.json').read_text())
    matches = [entry['book'] for entry in registry['entries']
               if (entry['book']['language'], entry['book']['collection']) == ('en', 'hadith')]
    if len(matches) != 1:
        raise ValueError('Selected retained pair must have exactly one registry record')
    book = matches[0]
    if any(book.get(key) != value for key, value in PINNED.items()):
        raise ValueError('Selected retained pair no longer matches the reviewed URLs and hashes')
    if book.get('exportVerified') is not True or book.get('previewOnly') is not False:
        raise ValueError('Selected pair is not the existing verified public edition')

    report = {
        'schema': 'iman-retained-pair-diagnostic-v1',
        'purpose': 'Read-only authenticated transport proof; no publication eligibility',
        'headCommit': os.environ.get('GITHUB_SHA'),
        'runId': os.environ.get('GITHUB_RUN_ID'),
        'selectedRetainedPair': PINNED,
        'originalFailureAssetIdentified': False,
        'productionModules': {name: digest(root / 'books' / name)
                              for name in ['download_page.py', 'install_assets.py']},
        'apiCalls': [], 'files': [], 'checks': [], 'complete': False,
    }
    report_path = out / 'transport-report.json'

    def checkpoint():
        report_path.write_text(json.dumps(report, indent=2) + '\n')

    def check(name, condition, **details):
        if not condition:
            raise AssertionError(name)
        report['checks'].append({'check': name, 'passed': True, **details})
        emit('check-passed', check=name, **details)
        checkpoint()

    real_api = install_assets._gh_api

    def traced_api(endpoint, accept, *, timeout, output=None):
        call = {'endpoint': endpoint, 'accept': accept, 'timeoutSeconds': timeout}
        report['apiCalls'].append(call)
        emit('authenticated-api-start', **call)
        started = time.monotonic()
        try:
            value = real_api(endpoint, accept, timeout=timeout, output=output)
        except BaseException as error:
            call.update(seconds=round(time.monotonic()-started, 3), errorType=type(error).__name__)
            checkpoint()
            raise
        call.update(seconds=round(time.monotonic()-started, 3), success=True)
        emit('authenticated-api-end', **call)
        checkpoint()
        return value

    def forbidden_download(*args, **kwargs):
        raise AssertionError('Unexpected download on a local/cache-only check')

    work = out / 'isolated-root'
    local_out = work / 'out'
    try:
        # The public route is forbidden during the real calls, proving that the
        # normal GH_TOKEN selected the production authenticated API transport.
        with mock.patch.object(install_assets, '_gh_api', side_effect=traced_api), \
             mock.patch.object(install_assets.urllib.request, 'urlopen',
                               side_effect=AssertionError('Unexpected public URL transport')):
            for extension, hashkey in [('pdf', 'pdfSha256'), ('docx', 'sha256')]:
                started = time.monotonic()
                path = download_page.source_file(work, local_out, book, extension)
                expected = work / 'books/.cache/download-pairs' / book[hashkey] / Path(book['file']).with_suffix('.'+extension).name
                check('exact-released-bytes-'+extension,
                      path == expected and digest(path) == book[hashkey],
                      bytes=path.stat().st_size, sha256=book[hashkey])
                report['files'].append({'extension': extension, 'path': str(path.relative_to(out)),
                                        'sha256': digest(path), 'bytes': path.stat().st_size,
                                        'seconds': round(time.monotonic()-started, 3)})

        check('authenticated-api-used-for-both-files',
              len(report['apiCalls']) == 4 and
              sum(call['accept'] == 'application/octet-stream' for call in report['apiCalls']) == 2)

        for extension, hashkey in [('pdf', 'pdfSha256'), ('docx', 'sha256')]:
            name = Path(book['file']).with_suffix('.'+extension).name
            cache = work / 'books/.cache/download-pairs' / book[hashkey] / name
            original = cache.read_bytes()
            before = cache.stat().st_mtime_ns
            with mock.patch.object(download_page, 'download_archive', side_effect=forbidden_download):
                cached = download_page.source_file(work, local_out, book, extension)
            check('cache-hit-without-download-'+extension,
                  cached == cache and digest(cache) == book[hashkey] and cache.stat().st_mtime_ns == before)

            # A checked local file with unexpected bytes must never be accepted,
            # even though an authentic release copy already exists in the cache.
            local = local_out / 'en-hadith' / name
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(b'diagnostic intentional local tamper')
            rejected = False
            with mock.patch.object(download_page, 'download_archive', side_effect=forbidden_download):
                try:
                    download_page.source_file(work, local_out, book, extension)
                except ValueError as error:
                    rejected = str(error) == 'Local checked book changed'
            check('changed-local-file-rejected-'+extension,
                  rejected and local.read_bytes() == b'diagnostic intentional local tamper' and cache.read_bytes() == original)
            local.unlink()

            # Negative transfer probe is isolated from the verified cache. It
            # supplies wrong bytes through only the transport seam, while the
            # production source_file size/digest/cache checks remain untouched.
            badroot = out / ('negative-'+extension)
            badcache = badroot / 'books/.cache/download-pairs' / book[hashkey] / name
            badcache.parent.mkdir(parents=True, exist_ok=True)
            badcache.write_bytes(b'diagnostic old damaged cache')
            def bad_download(url, destination):
                expected_url = book['pdfDownload' if extension == 'pdf' else 'download']
                if url != expected_url:
                    raise AssertionError('Negative transfer lost the pinned URL')
                destination.write_bytes(original + b'diagnostic tamper')
            rejected = False
            with mock.patch.object(download_page, 'download_archive', side_effect=bad_download):
                try:
                    download_page.source_file(badroot, badroot / 'out', book, extension)
                except ValueError as error:
                    rejected = str(error) == 'Downloaded book differs from its published hash'
            check('tampered-download-rejected-without-cache-promotion-'+extension,
                  rejected and badcache.read_bytes() == b'diagnostic old damaged cache')
            check('staged-tampered-download-cleaned-'+extension,
                  [p.name for p in badcache.parent.iterdir()] == [name])

            # A damaged cache must trigger a fresh verified transfer; this copy
            # uses the previously authenticated exact bytes, without another GET.
            refresh_calls = []
            def verified_copy(url, destination):
                refresh_calls.append(url)
                destination.write_bytes(original)
            with mock.patch.object(download_page, 'download_archive', side_effect=verified_copy):
                repaired = download_page.source_file(badroot, badroot / 'out', book, extension)
            check('damaged-cache-replaced-only-by-verified-bytes-'+extension,
                  repaired == badcache and digest(repaired) == book[hashkey] and len(refresh_calls) == 1)

        report['complete'] = True
        checkpoint()
        emit('diagnostic-success', checks=len(report['checks']), report=str(report_path))
    except BaseException as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        checkpoint()
        raise


if __name__ == '__main__':
    main()
