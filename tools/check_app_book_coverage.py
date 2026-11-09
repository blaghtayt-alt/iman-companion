"""Read-only regression guard for an explicitly audited app/book inventory.

The baseline records an earlier app archive audit, not source approval. Existing
edition selectors decide eligibility. Published/queued identities are checked
against their snapshots; no remote asset or installed app is queried here.
"""
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import re
import sys

sys.dont_write_bytecode = True
CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / 'books'))
from book_edition_scope import MAP, available
from preparation_queue import load as load_queue, signature
from published_library import (SCHEMA as LIBRARY_SCHEMA, asset_names, catalog_fingerprint, catalog_members,
                               current, declaration, limited_continuity, scope_settings)

BASELINE_KIND = 'audited-app-book-membership'
HEX = re.compile(r'^[a-f0-9]{64}$')
COLLECTIONS = {'articles', 'tadabbur-extended', 'seerah', 'hadith'}
CATALOG_IDENTITY_FIELDS = ('sourceHashes', 'sourceChapterId', 'edition', 'readingSHA256', 'json', 'markdown')


def read(path):
    return json.loads(Path(path).read_bytes())


def identity(row, *, catalog=False):
    language, collection, ident = row.get('language'), row.get('collection'), row.get('id')
    collection = MAP.get(collection) if catalog else collection
    if not isinstance(language, str) or not language or collection not in COLLECTIONS:
        raise ValueError('Invalid material language or collection')
    if not isinstance(ident, (str, int)) or isinstance(ident, bool) or not str(ident):
        raise ValueError('Invalid material identity')
    return language, collection, str(ident)


def label(key):
    return {'language': key[0], 'collection': key[1], 'id': key[2]}


def checked_path(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts):
        raise ValueError('Expected a relative, contained evidence path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Evidence path escapes its root')
    return path


def check_bindings(root, bindings):
    """Check every exact binding, returning diagnostics without writing files."""
    if not isinstance(bindings, list) or not bindings:
        return [{'reason': 'Missing exact source bindings'}]
    problems, seen = [], set()
    for binding in bindings:
        relative = binding.get('path') if isinstance(binding, dict) else None
        try:
            if relative in seen:
                raise ValueError('Duplicate evidence path')
            seen.add(relative)
            digest = binding.get('sha256', '')
            if not isinstance(digest, str) or not HEX.fullmatch(digest):
                raise ValueError('Invalid evidence SHA256')
            actual = hashlib.sha256(checked_path(root, relative).read_bytes()).hexdigest()
            if actual != digest:
                problems.append({'path': relative, 'reason': 'Evidence bytes changed',
                                 'expectedSHA256': digest, 'actualSHA256': actual})
        except (OSError, ValueError, TypeError, AttributeError) as error:
            problems.append({'path': relative, 'reason': str(error)})
    return problems


def member_ids(entry, key):
    """Require manifest and snapshot agreement, not just equal member counts."""
    book, snapshot = entry['book'], entry['snapshot']
    if (book.get('language'), book.get('collection')) != key:
        raise ValueError('Candidate book belongs to another scope')
    ids = [str(row['id']) for row in book['units']]
    snapshot_ids = snapshot['unitIds']
    if (not ids or len(ids) != len(set(ids)) or not isinstance(snapshot_ids, list)
            or len(snapshot_ids) != len(set(snapshot_ids))
            or set(ids) != set(snapshot_ids)):
        raise ValueError('Book units differ from their exact snapshot identities')
    members = snapshot.get('catalogMemberKeys')
    if members is not None:
        keys = [identity(row, catalog=True) for row in members]
        if (len(keys) != len(set(keys)) or any(value[:2] != key for value in keys)
                or {value[2] for value in keys} != set(ids)):
            raise ValueError('Book units differ from their catalogue member identities')
    # Historical snapshots without catalogMemberKeys have matching literal IDs.
    # current()/limited_continuity() must independently validate that legacy case.
    return set(ids)


def validate_snapshot_sources(root, catalog, key, rows, snapshot):
    """Require consumed sources using the existing narrow Ikhlas contract.

    The legacy translated Ikhlas adapter consumes its JSON reader and pinned
    verse/source files, not the Markdown mirror. That mirror remains bound by
    the preparation signature and the separate audited baseline. Derive the
    exception from the real adapter; never ignore Markdown for another reader.
    """
    required = {row[name] for row in rows for name in ('json', 'markdown') if row.get(name)}
    bindings = {binding['path']: binding['sha256'] for binding in snapshot.get('bindings', [])}
    declared = declaration(root, key, for_release=False)
    if (key[0] != 'ar' and key[1] == 'tadabbur-extended'
            and declared.get('adapter') in {'reviewed-ikhlas-v1', 'reviewed-structured-quran-v1'}):
        from quran_scope import canonical_surah
        targets = [row for row in rows if canonical_surah(row) == 112 and not row.get('bookReaderUnit')]
        if targets:
            if len(targets) != 1:
                raise ValueError('Ambiguous translated Ikhlas source identity')
            from adapt_ikhlas import generate
            units = generate(root, catalog, {**declared, 'adapter': 'reviewed-ikhlas-v1'})
            if len(units) != 1 or str(units[0]['id']) != str(targets[0]['id']):
                raise ValueError('Ikhlas adapter returned another source identity')
            consumed = {item['path']: item['sha256'] for item in units[0]['inputBindings']}
            if not consumed or any(bindings.get(path) != digest for path, digest in consumed.items()):
                raise ValueError('Current preparation omits or changes an actual Ikhlas adapter input')
            mirror = targets[0].get('markdown')
            if mirror and mirror not in consumed:
                required.discard(mirror)
    if not required.issubset(bindings):
        raise ValueError('Current preparation omits selected source bindings')


def validate_baseline(baseline):
    if baseline.get('schemaVersion') != 1 or baseline.get('kind') != BASELINE_KIND:
        raise ValueError('Unsupported app/book audit baseline')
    date.fromisoformat(baseline['auditedDate'])
    if not re.fullmatch(r'[a-f0-9]{40}', baseline.get('repositoryBase', '')):
        raise ValueError('Baseline needs the exact audited repository commit')
    evidence = baseline.get('appEvidence', {})
    if not HEX.fullmatch(evidence.get('archiveSHA256', '')) or not evidence.get('files'):
        raise ValueError('Baseline needs pinned app archive and runtime file identities')
    if not evidence.get('method') or not evidence.get('limitations'):
        raise ValueError('Baseline must explain its app evidence and limitations')
    runtime_paths = set()
    for binding in evidence['files']:
        relative = binding['path']
        checked_path(Path('/'), relative)
        if relative in runtime_paths or not HEX.fullmatch(binding.get('sha256', '')):
            raise ValueError('Invalid or duplicate runtime file pin')
        runtime_paths.add(relative)
    units = baseline.get('units')
    if not isinstance(units, list) or not units:
        raise ValueError('Baseline has no audited unit identities')
    keys = [identity(unit) for unit in units]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate baseline material identity')
    for unit in units:
        if not isinstance(unit.get('evidenceLevel'), str) or not unit['evidenceLevel']:
            raise ValueError('Baseline unit is missing its evidence level')
        if not isinstance(unit.get('sourceBindings'), list) or not unit['sourceBindings']:
            raise ValueError('Baseline unit is missing its exact source bindings')
        metadata = unit.get('catalogIdentity')
        if (not isinstance(metadata, dict) or not any(metadata.get(name) for name in ('json', 'markdown'))
                or set(metadata) - set(CATALOG_IDENTITY_FIELDS)):
            raise ValueError('Baseline unit needs its bounded catalogue identity metadata')
    return keys


def audit(root, baseline, app_root=None):
    root = Path(root).resolve()
    baseline_keys = validate_baseline(baseline)
    errors, warnings, statuses = [], [], []
    catalog = read(root / 'materials/catalog.json')
    catalog_index = {}
    for row in catalog.get('entries', []):
        if row.get('collection') not in MAP:
            continue
        key = identity(row, catalog=True)
        if key in catalog_index:
            errors.append({'code': 'duplicate-catalog-identity', **label(key)})
        catalog_index[key] = row
    public = read(root / 'books/published-library.json')
    if public.get('schema') != LIBRARY_SCHEMA:
        raise ValueError('Invalid published book registry')
    queue = load_queue(root)
    published_by_scope, queued_by_scope = {}, {}
    for entry in public.get('entries', []):
        key = entry['book']['language'], entry['book']['collection']
        if key in published_by_scope:
            errors.append({'code': 'duplicate-published-scope', 'scope': '/'.join(key)})
        published_by_scope[key] = entry
    for row in queue['entries']:
        queued_by_scope[(row['language'], row['collection'])] = row

    scopes = {}
    for key in sorted({value[:2] for value in baseline_keys}):
        info = {'selected': set(), 'published': set(), 'recordedPublished': set(),
                'prepared': set(), 'recordedPrepared': set(), 'preparationState': 'not-queued',
                'selectedRows': [], 'catalogFingerprint': None}
        try:
            selected, selection_report = catalog_members(root, key, for_release=False)
            ids = [str(row['id']) for row in selected]
            if len(ids) != len(set(ids)):
                raise ValueError('Duplicate selected material identity')
            info['selected'] = set(ids)
            info['selectedRows'] = selected
            info['catalogFingerprint'] = catalog_fingerprint(selected, selection_report)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append({'code': 'source-selection-failed', 'scope': '/'.join(key),
                           'reason': str(error)})
        entry = published_by_scope.get(key)
        if entry:
            try:
                book = entry['book']
                if book.get('exportVerified') is not True or book.get('previewOnly') is not False:
                    raise ValueError('Published record is not an export-verified production book')
                if any(not HEX.fullmatch(book.get(field, '')) for _, field in asset_names(book)):
                    raise ValueError('Published record lacks exact Word/PDF asset hashes')
                ids = member_ids(entry, key)
                info['recordedPublished'] = ids
                is_current = current(root, entry)
                if is_current and ids != info['selected']:
                    raise ValueError('Current published snapshot omits selected identities')
                if is_current or limited_continuity(root, entry):
                    if not ids.issubset(info['selected']):
                        raise ValueError('Published snapshot includes a non-selected identity')
                    info['published'] = ids
                else:
                    warnings.append({'code': 'published-snapshot-not-current', 'scope': '/'.join(key),
                                     'reason': 'Recorded download membership is not current source evidence.'})
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                errors.append({'code': 'invalid-published-membership', 'scope': '/'.join(key),
                               'reason': str(error)})
        queued = queued_by_scope.get(key)
        if queued:
            try:
                book = queued['candidate']['book']
                if book.get('preparationVerified') is not True or book.get('previewOnly') is not False:
                    raise ValueError('Queue does not contain a verified production preparation')
                ids = member_ids(queued['candidate'], key)
                info['recordedPrepared'] = ids
                snapshot = queued['candidate']['snapshot']
                if queued.get('releaseVerified') is not False:
                    raise ValueError('A preparation cannot claim release verification')
                same_inputs = queued.get('inputFingerprint') == signature(root, key)
                if same_inputs and (ids != info['selected']
                                    or snapshot.get('catalogSHA256') != info['catalogFingerprint']):
                    raise ValueError('Current preparation omits selected units or has a changed catalogue snapshot')
                if same_inputs:
                    validate_snapshot_sources(root, catalog, key, info['selectedRows'], snapshot)
                if (queued.get('state') != 'prepared-awaiting-release-qc' or not same_inputs
                        or snapshot.get('scopeSettingsSHA256') != scope_settings(root, key, snapshot['unitIds'])
                        or check_bindings(root, snapshot.get('bindings'))):
                    info['preparationState'] = 'stale-inputs'
                else:
                    info['prepared'] = ids
                    info['preparationState'] = 'current-recorded-preparation'
                if not info['prepared']:
                    warnings.append({'code': 'preparation-needs-refresh', 'scope': '/'.join(key),
                                     'state': info['preparationState']})
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                errors.append({'code': 'invalid-prepared-membership', 'scope': '/'.join(key),
                               'reason': str(error)})
                info['preparationState'] = 'invalid-record'
        scopes[key] = info

    for unit, key in zip(baseline['units'], baseline_keys):
        info = scopes[key[:2]]
        binding_errors = check_bindings(root, unit['sourceBindings'])
        row = catalog_index.get(key)
        if row is not None:
            metadata = {name: row[name] for name in CATALOG_IDENTITY_FIELDS if name in row}
            if metadata != unit['catalogIdentity']:
                binding_errors.append({'reason': 'Current catalogue identity metadata differs from audited fields',
                                       'expected': unit['catalogIdentity'], 'actual': metadata})
        bound_paths = {binding['path'] for binding in unit['sourceBindings']}
        for field in ('json', 'markdown'):
            if row and row.get(field) and row[field] not in bound_paths:
                binding_errors.append({'path': row[field], 'reason': 'Current catalogue source path is absent from audited bindings'})
        if binding_errors:
            errors.append({'code': 'baseline-source-drift', **label(key), 'bindings': binding_errors})
        if row is None:
            state = 'missing-from-catalog'
        elif not available(row):
            state = 'held-or-retired'
        elif key[2] not in info['selected']:
            state = 'not-selected'
        elif binding_errors:
            state = 'source-drift'
        elif key[2] in info['published']:
            state = 'published-record-current'
        elif key[2] in info['prepared']:
            state = 'selected-and-prepared'
        else:
            state = 'selected-awaiting-preparation'
        if state in {'missing-from-catalog', 'held-or-retired', 'not-selected'}:
            errors.append({'code': 'baseline-unit-not-selected', **label(key), 'state': state})
        statuses.append({**label(key), 'state': state, 'evidenceLevel': unit['evidenceLevel'],
                         'recordedPublished': key[2] in info['recordedPublished'],
                         'recordedPrepared': key[2] in info['recordedPrepared']})

    expected = set(baseline_keys)
    additional = [label((*scope, ident)) for scope, info in scopes.items()
                  for ident in sorted(info['selected']) if (*scope, ident) not in expected]
    if additional:
        warnings.append({'code': 'selected-identities-outside-audited-baseline', 'units': additional})
    runtime = {'state': 'not-checked', 'reason': 'No --app-root supplied; historical archive evidence only.',
               'archiveBytesChecked': False}
    if app_root is not None:
        mismatches = check_bindings(Path(app_root).resolve(), baseline['appEvidence']['files'])
        runtime = {'state': 'pins-match' if not mismatches else 'pins-stale',
                   'filesChecked': len(baseline['appEvidence']['files']),
                   'archiveBytesChecked': False, 'mismatches': mismatches}
        if mismatches:
            errors.append({'code': 'app-runtime-pins-stale', 'bindings': mismatches})
    return {'schemaVersion': 1, 'kind': 'app-book-coverage-audit',
            'baselineDate': baseline['auditedDate'], 'repositoryBase': baseline['repositoryBase'],
            'result': 'FAIL' if errors else 'PASS', 'summary': dict(Counter(item['state'] for item in statuses)),
            'auditedUnits': len(statuses), 'units': statuses, 'runtimeEvidence': runtime,
            'preparationScopes': [{'language': key[0], 'collection': key[1],
                                   'state': value['preparationState']} for key, value in scopes.items()],
            'errors': errors, 'warnings': warnings,
            'knownAppGaps': baseline.get('knownAppGaps', []),
            'exclusions': baseline.get('exclusions', []),
            'sourceApprovalCreated': False, 'releaseApprovalCreated': False,
            'limitations': ['Identity and exact pinned-source audit; paragraph/body completeness is not revalidated.',
                           'Published membership is verified against local registry snapshots; remote assets are not fetched.',
                           'Preparation artifact availability and Word/visual acceptance are not revalidated.',
                           'App file pins describe the audited archive; no installed app or live UI is inspected.',
                           'Known app gaps and exclusions are reported, never admitted or approved.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path,
                        default=CODE_ROOT / 'docs/automation/current-app-book-baseline.json')
    parser.add_argument('--app-root', type=Path)
    parser.add_argument('--json', dest='output', type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if root != CODE_ROOT:
            raise ValueError('Run the guard from the same checkout supplied as --root')
        if args.output:
            output = args.output.resolve()
            if (output.is_relative_to(root) or output == args.baseline.resolve()
                    or (args.app_root and output.is_relative_to(args.app_root.resolve()))):
                raise ValueError('Audit output must be outside the read-only repository, app and baseline inputs')
        result = audit(root, read(args.baseline), args.app_root)
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(encoded, encoding='utf8')
            print(json.dumps({'result': result['result'], 'auditedUnits': result['auditedUnits'],
                              'summary': result['summary'], 'runtimeEvidence': result['runtimeEvidence']['state'],
                              'errors': len(result['errors']), 'warnings': len(result['warnings'])}, ensure_ascii=False))
        else:
            print(encoded, end='')
        return 1 if result['errors'] else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({'result': 'FAIL', 'error': str(error), 'sourceApprovalCreated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
