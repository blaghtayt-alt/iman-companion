"""Report source-to-download freshness without granting source/release approval.

This runs even after a failed book job. Every selector and input hash remains
enforced by the preparation/publication code; this module only explains gaps.
The public projection binds the advertised file hashes, so a status for an old
edition cannot accidentally label a replacement as current.
"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json

from book_edition_scope import MAP, available, select
from book_content_coverage import discover_readers, COPY as COVERAGE_COPY
from locale_copy import COPY
from published_library import current, inside, read, scope_key
from publish_approved_material import atomic, bytes_json

SCHEMA = 'iman-book-source-update-status-v1'
PUBLIC_PATH = 'docs/books/update-status.json'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_bindings(value):
    """Walk explicit bindings only; original/provenance hashes are not inputs."""
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            yield value
        for item in value.values():
            yield from source_bindings(item)
    elif isinstance(value, list):
        for item in value:
            yield from source_bindings(item)


def changed_bindings(root, bindings):
    result = []
    seen = set()
    for binding in bindings:
        identity = binding['path'], binding['sha256']
        if identity in seen:
            continue
        seen.add(identity)
        try:
            actual = digest(inside(root, binding['path']).read_bytes())
            if actual == binding['sha256']:
                continue
            reason = 'source-bytes-changed'
        except (OSError, ValueError) as error:
            actual, reason = None, str(error)
        result.append({'path': binding['path'], 'expectedSHA256': binding['sha256'],
                       'actualSHA256': actual, 'reason': reason})
    return sorted(result, key=lambda row: (row['path'], row['expectedSHA256']))


def audit(root):
    root = Path(root).resolve()
    catalog = read(root / 'materials/catalog.json')
    declarations = read(root / 'books/reviewed-books.json')['books']
    published = read(root / 'books/published-library.json')['entries']
    queue = read(root / 'books/prepared-library.json')['entries']
    discovery = discover_readers(root, list(COPY), catalog)
    by_scope = {scope_key(row): row for row in declarations}
    previous = {scope_key(row['book']): row for row in published}
    pending = {scope_key(row): row for row in queue}
    if len(by_scope) != len(declarations) or len(previous) != len(published) or len(pending) != len(queue):
        raise ValueError('Duplicate scope in source, publication or preparation registry')
    found = {}
    for row in discovery['readers']:
        found.setdefault((row['language'], MAP[row['collection']]), []).append(row)
    rows = []
    error_scopes = {(r['language'], r['collection']) for r in discovery['errors']}
    for key in sorted(set(by_scope) | set(previous) | set(found) | error_scopes):
        language, collection = key
        declaration = by_scope.get(key)
        sources = [r for r in catalog['entries'] if available(r)
                   and (r.get('language'), MAP.get(r.get('collection'))) == key
                   and (not declaration or not declaration.get('edition') or r.get('edition') == declaration['edition'])]
        bindings, problems, selected = [], [], []
        for evidence in (declaration or {}).get('sourceReviewBindings', []):
            bindings.append(evidence)
            try:
                value = read(inside(root, evidence['path']))
                if 'records' in value:
                    typed = {str(r['id']) for r in sources if r.get('bookReaderUnit')}
                    from quran_scope import review_catalog_id
                    value = [record for record in value['records'] if record.get('language') == language
                             and (MAP.get(record.get('collection'), collection) == collection)
                             and str(record.get('id', record.get('catalogId')) or
                                     (review_catalog_id(record) if 'materialId' in record else '')) not in typed]
                bindings.extend(source_bindings(value))
            except (OSError, ValueError, KeyError) as error:
                problems.append({'path': evidence.get('path'), 'reason': str(error)})
        for source in sources:
            binding = source.get('bookReaderUnit')
            if binding:
                bindings.append(binding)
                try:
                    unit = read(inside(root, binding['path']))
                    bindings.extend(unit.get('inputBindings', []))
                except (OSError, ValueError, KeyError) as error:
                    problems.append({'path': binding.get('path'), 'reason': str(error)})
        drift = changed_bindings(root, bindings)
        if declaration:
            try:
                selected, _ = select(root, catalog, declaration)
            except (OSError, ValueError, KeyError, TypeError) as error:
                problems.append({'reason': str(error)})
        elif sources or found.get(key):
            problems.append({'reason': 'No reviewed preparation declaration; an approved publication handoff is required'})
        omitted = found.get(key, [])
        for error in discovery['errors']:
            if (error['language'], error['collection']) == key:
                problems.append(error)
        entry = previous.get(key)
        released_current = bool(entry and current(root, entry))
        if declaration and not released_current and not problems and not drift:
            # Legacy declarations also have adapter-specific exact projections;
            # selector membership alone does not validate those reader bytes.
            legacy={'arabic-articles-v1':'adapt_ar_articles','arabic-new-seerah-v1':'adapt_ar_seerah',
                    'arabic-essential-hadith-v1':'adapt_ar_hadith'}
            module=legacy.get(declaration.get('adapter'))
            if module:
                try:
                    from importlib import import_module
                    exclusions={(r['collection'],r['language'],str(r['id'])) for r in selected if r.get('bookReaderUnit')}
                    import_module(module).generate(root,catalog,declaration,excluded_catalog_keys=exclusions)
                except (OSError,ValueError,KeyError,TypeError) as error:
                    problems.append({'reason':str(error),'stage':'reader-normalization'})
        candidate = pending.get(key)
        prepared_current = False
        if candidate:
            try:
                from preparation_queue import signature
                prepared_current = candidate.get('state') == 'prepared-awaiting-release-qc' and candidate.get('inputFingerprint') == signature(root, key)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if drift or problems:
            state = 'source-registration-blocked'
        elif omitted:
            state = 'source-registration-required'
        elif prepared_current:
            state = 'prepared-awaiting-release-qc'
        elif released_current:
            state = 'current'
        elif selected:
            state = 'awaiting-preparation'
        else:
            state = 'source-review-required'
        source_files = {}
        for source in sources + omitted:
            for relative in [source[field] for field in ('json','markdown') if source.get(field)] + source.get('readerFiles',[]):
                if relative:
                    try:
                        source_files[relative] = digest(inside(root, relative).read_bytes())
                    except (OSError, ValueError):
                        source_files[relative] = None
        book = entry['book'] if entry else {}
        rows.append({'language': language, 'collection': collection, 'state': state,
                     'updatePending': state != 'current', 'publishedSnapshotCurrent': released_current,
                     'sourceFingerprint': digest(bytes_json(source_files)),
                     'sourceFiles': source_files, 'changedBindings': drift, 'blockers': problems,
                     'unregisteredReadings': omitted, 'selectedIds': [str(r['id']) for r in selected],
                     'publishedSourceCommit': book.get('sourceCommit'),
                     'publishedReleaseTag': entry.get('releaseTag') if entry else None,
                     'publishedHashes': {name: book.get(field) for name, field in [('docx','sha256'), ('pdf','pdfSha256')]},
                     'prepared': {field: candidate[field] for field in ('state','sourceCommit','inputFingerprint','artifact','pendingChecks') if field in candidate} if candidate else None,
                     'nextAction': ('Complete the exact approved source handoff; resolve the listed source/review discrepancy before preparation.' if drift or problems or omitted else
                                    'Complete the recorded Word and final visual checks on the exact candidate bytes.' if prepared_current else
                                    'Prepare and validate the selected current sources.' if state != 'current' else 'No source update pending.')})
    return {'schema': SCHEMA, 'scopes': rows, 'summary': dict(Counter(r['state'] for r in rows)),
            'sourceApprovalCreated': False, 'releaseApprovalCreated': False,
            'limitations': ['Discovery is not approval.', 'A current local snapshot does not prove remote bytes or Word execution.']}


def public_projection(report, catalog):
    statuses = {(r['language'], r['collection']): r for r in report['scopes']}
    languages = {}
    for language, locale in catalog['languages'].items():
        books = {}
        for book in locale['books']:
            row = statuses.get((language, book['collection']))
            exact = row and row['publishedHashes'] == {'docx':book['sha256'], 'pdf':book['pdfSha256']}
            pending = not exact or row['updatePending']
            books[book['collection']] = {'sha256': book['sha256'], 'pdfSha256': book['pdfSha256'],
                'state': row['state'] if exact else 'status-unverified', 'updatePending': pending,
                'label': COVERAGE_COPY[language][3] if pending else '',
                'publishedSourceCommit': row.get('publishedSourceCommit') if exact else None}
        languages[language] = {'books': books, 'pendingLabel': COVERAGE_COPY[language][3],
                               'bundleLinks': locale.get('bundle'),
                               'bundleUpdatePending': any(r['updatePending'] for r in report['scopes'] if r['language']==language),
                               'unpublishedScopes': [r['collection'] for r in report['scopes'] if r['language']==language and r['collection'] not in books]}
    return {'schema': SCHEMA, 'catalogSHA256': digest(bytes_json(catalog)), 'languages': languages,
            'sourceApprovalCreated': False, 'releaseApprovalCreated': False}


def write_public(root, report=None):
    report = report or audit(root)
    result = public_projection(report, read(root / 'docs/books/catalog.json'))
    atomic(root / PUBLIC_PATH, bytes_json(result))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--json', type=Path)
    parser.add_argument('--write-public', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    report = audit(root)
    if args.write_public:
        write_public(root, report)
    if args.json:
        atomic(args.json, bytes_json(report))
    print(json.dumps({'summary':report['summary'], 'scopes':len(report['scopes']), 'sourceApprovalCreated':False}))


if __name__ == '__main__':
    main()
