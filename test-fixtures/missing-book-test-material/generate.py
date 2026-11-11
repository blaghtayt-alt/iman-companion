"""Stage, then bind the 30 user-requested temporary TEST TEST materials.

Only this fixture directory is writable. The recorded author review must exist
before finish; this script does not invent a reviewer or apply source intake.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PREFIX = BASE.relative_to(ROOT).as_posix()
NAME = 'automation test material'
BODY = 'TEST TEST'
BODY_SHA = hashlib.sha256(BODY.encode()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf8')


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def binding(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path.read_bytes())}


def write(path, value):
    require(path.resolve().is_relative_to(BASE), 'Output leaves the assigned fixture folder')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Symlink output is not allowed')
        if part == BASE:
            break
    raw = value if isinstance(value, bytes) else encode(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, 'Existing fixture differs; preserve it: ' + str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return binding(path)


def specification():
    spec = read(BASE / 'specification.json')
    require(spec['schema'] == 'iman-missing-book-test-specification-v1'
            and spec['canonicalSourceName'] == NAME and spec['bodyText'] == BODY,
            'Unexpected test specification')
    for relative, expected in spec['productionBaselineBindings'].items():
        require(sha((ROOT / relative).read_bytes()) == expected,
                'Production source eligibility advanced: ' + relative)
    conf = read(ROOT / 'books/config.json')
    published = read(ROOT / 'books/published-library.json')['entries']
    available = {(row['book']['language'], row['book']['collection']) for row in published}
    expected = {(row['language'], row['collection']) for row in spec['scopes']}
    actual = {(language, collection) for language in conf['languages']
              for collection in ('tadabbur-extended', 'hadith', 'seerah', 'articles')
              if (language, collection) not in available}
    require(actual == expected and len(expected) == 30, 'Missing-scope matrix changed')
    declarations = read(ROOT / 'books/reviewed-books.json')['books']
    declared = {(row['language'], row['collection']) for row in declarations}
    require(not expected.intersection(declared), 'A requested scope already has a declaration')
    return spec


def material(scope):
    return {key: scope[key] for key in ('collection', 'language')} | {'id': scope['materialId']}


def folder(scope):
    return BASE / 'generated' / scope['language'] / scope['collection']


def sources(spec):
    request = binding(BASE / 'user-request-receipt.json')
    records = []
    for scope in spec['scopes']:
        location = folder(scope)
        text = write(location / 'source.txt', BODY.encode('utf8'))
        metadata = {
            'schema': 'iman-authored-temporary-automation-source-v1',
            **material(scope), 'testOnly': True, 'temporary': True,
            'name': NAME, 'title': NAME, 'displayTitle': scope['title'],
            'order': 1, 'paragraphs': [BODY], 'citations': [],
            'bodyIsTranslation': False, 'religiousSource': False,
            'purpose': 'User-requested temporary material for the normal books automation path.',
            'userRequestReceipt': request, 'sourceText': text,
        }
        if scope['collection'] == 'seerah':
            metadata['edition'] = 'new-adult'
        source = write(location / 'source.json', metadata)
        records.append({**scope, 'sourceText': text, 'sourceMetadata': source,
                        'readerTextSHA256': BODY_SHA, 'referenceCount': 0})
    return records


def finish(spec, records):
    review_path = BASE / 'author-technical-review.json'
    review = read(review_path)
    require(review.get('schema') == 'iman-missing-book-test-author-review-v1'
            and review.get('decision') == 'approved' and review.get('wholeMaterial') is True
            and review.get('specification') == binding(BASE / 'specification.json')
            and review.get('sourceRecords') == records
            and review.get('reviewer', {}).get('identity') == '/root/bidi_patch_review'
            and review['reviewer'].get('independent') is False
            and review.get('claims') and all(value is False for value in review['claims'].values()),
            'An actual exact author technical review is required before generating handoffs')
    author = binding(review_path)
    request = binding(BASE / 'user-request-receipt.json')
    output = []
    registrations = []
    for record in records:
        location = folder(record)
        identity = material(record)
        source_bindings = [record['sourceMetadata'], record['sourceText']]
        technical = write(location / 'technical-review.json', {
            'schema': 'iman-temporary-material-technical-review-v1',
            'testOnly': True, 'decision': 'approved', 'wholeMaterial': True,
            'approvalId': record['materialId'] + '-author-technical-v1',
            'reviewer': review['reviewer'], 'reviewedAtUTC': review['reviewedAtUTC'],
            'material': identity, 'canonicalSourceName': NAME,
            'displayTitle': record['title'], 'bodyText': BODY, 'readerTextSHA256': BODY_SHA,
            'sourceBindings': source_bindings, 'recordedAuthorReview': author,
            'reviewScope': 'Exact authored dummy text, display label and one-paragraph normalization; no religious or translation assessment.',
            'claims': review['claims'],
        })
        accepted = write(location / 'source-acceptance.json', {
            'schema': 'iman-temporary-material-source-acceptance-v1',
            'testOnly': True, 'decision': 'approved', 'wholeMaterial': True,
            'material': identity, 'sourceBindings': source_bindings,
            'readerTextSHA256': BODY_SHA, 'displayTitle': record['title'],
            'userRequestReceipt': request, 'recordedAuthorReview': author,
            'reviewer': review['reviewer'], 'reviewedAtUTC': review['reviewedAtUTC'],
            'scope': 'Accept these exact user-requested authored TEST bytes for temporary source intake. Word, visual and release decisions remain separate.',
            'claims': review['claims'],
        })
        inventory = write(location / 'approved-reader-import.json', {
            'schema': 'iman-approved-reader-source-v1', 'material': identity,
            'current': True, 'testOnly': True, 'readingSource': record['sourceText'],
            'sourceBindings': source_bindings,
            'approval': {'decision': 'approved', 'wholeMaterial': True,
                         'approvalId': record['materialId'] + '-exact-source-v1',
                         'reviewer': review['reviewer'],
                         'semanticReviewSHA256': technical['sha256'],
                         'sourceAcceptanceSHA256': accepted['sha256'],
                         'readerTextSHA256': BODY_SHA},
            'qualification': 'The semantic/source receipts describe only authored temporary TEST text; no scholarly, human or translation approval is claimed.',
        })
        proof = {'schema': 'iman-source-literal-text-v1', **identity,
                 'materialId': identity['id'], 'readerTextSHA256': BODY_SHA,
                 'source': record['sourceText'], 'inventory': inventory, 'pointer': [],
                 'start': 0, 'end': len(BODY), 'textSHA256': BODY_SHA}
        proof.pop('id')
        reader = {
            'schema': 'iman-book-unit-v1', **identity, 'testOnly': True,
            'order': 1, 'ordering': {'kind': 'global-sequence', 'sequence': 1},
            'title': record['title'], 'complete': True, 'reviewGate': 'published-current',
            'sourceHashes': [item['sha256'] for item in source_bindings],
            'readerTextSHA256': BODY_SHA, 'catalogBindings': [identity],
            'inputBindings': [*source_bindings, request, author, technical, accepted, inventory],
            'sections': [{'blocks': [{'kind': 'paragraph', 'text': BODY, 'sourceLiteralProof': proof}]}],
            'provenance': {'kind': 'user-requested-temporary-automation-material',
                           'canonicalSourceName': NAME, 'bodyIsTranslation': False,
                           'religiousSource': False, 'technicalAuthorReview': technical},
        }
        if record['collection'] == 'seerah':
            reader['referenceReadiness'] = {
                'auditScope': 'Exact TEST TEST body contains no quotations, citations or chapter facts.',
                'auditedReaderTextSHA256': BODY_SHA, 'sourceReferenceCount': 0,
                'unboundQuranSegments': 0, 'unboundHadithSegments': 0,
                'unboundScholarSegments': 0, 'unresolvedSourceReferenceCount': 0,
            }
        reader_binding = write(location / 'reader.json', reader)
        entry = {**identity, 'name': NAME, 'title': NAME, 'json': record['sourceMetadata']['path'],
                 'current': True, 'testOnly': True, 'temporary': True,
                 'sourceKind': 'user-requested-temporary-automation-material',
                 'sourceHashes': reader['sourceHashes']}
        if record['collection'] == 'seerah':
            entry['edition'] = 'new-adult'
        handoff = {
            'schema': 'iman-approved-material-publication-v1',
            'expectedCatalogSHA256': spec['sourceCatalogSHA256'],
            'catalogEntry': entry, 'sourceBindings': source_bindings,
            'canonicalOrder': 1, 'readerUnit': reader_binding,
            'approval': {'decision': 'approved', 'wholeMaterial': True,
                         'approvalId': record['materialId'] + '-temporary-publication-v1',
                         'reviewer': review['reviewer'], 'material': identity,
                         'readerTextSHA256': BODY_SHA,
                         'reviewArtifacts': [request, author, technical, accepted]},
            'expectedSourceBase': [{'path': item['path'], 'sha256': None} for item in source_bindings],
            'qualification': 'Temporary authored TEST material requested by the user; no human, scholarly or translation approval is claimed.',
        }
        handoff_binding = write(location / 'handoff.json', handoff)
        intake_path = 'materials/book-publication-intake/' + record['materialId'] + '.json'
        generated = {
            'currentReader': f"books/units/current/{record['language']}/{record['collection']}/{record['materialId']}.json",
            'approval': 'materials/book-publication-approvals/' + handoff_binding['sha256'] + '.json',
            'intakeHistory': 'materials/book-publication-intake-history/' + handoff_binding['sha256'] + '.json',
        }
        output.append({**record, 'technicalReview': technical, 'sourceAcceptance': accepted,
                       'approvedReaderImport': inventory, 'reader': reader_binding,
                       'handoff': handoff_binding, 'intendedIntakePath': intake_path,
                       'expectedGeneratedRecords': generated})
        registrations.append({'material': identity, 'scope': {key: identity[key] for key in ('language', 'collection')},
                              'intakePath': intake_path, **generated})
    manifest = {
        'schema': 'iman-missing-book-test-material-matrix-v1', 'testOnly': True,
        'canonicalSourceName': NAME, 'bodyText': BODY, 'scopeCount': 30,
        'sourceCommit': spec['sourceCommit'], 'sourceCatalogSHA256': spec['sourceCatalogSHA256'],
        'productionBaselineBindings': spec['productionBaselineBindings'],
        'userRequestReceipt': request, 'authorTechnicalReview': author,
        'scopes': output, 'removalManifest': PREFIX + '/removal-manifest.json',
        'intakeAppliedByGenerator': False, 'releaseFlagsChangedByGenerator': False,
    }
    write(BASE / 'matrix-manifest.json', manifest)
    owned = sorted(path.relative_to(ROOT).as_posix() for path in BASE.rglob('*') if path.is_file())
    removal_path = PREFIX + '/removal-manifest.json'
    if removal_path not in owned:
        owned.append(removal_path)
    write(BASE / 'removal-manifest.json', {
        'schema': 'iman-temporary-material-removal-manifest-v1',
        'ownedFixturePaths': sorted(owned),
        'ownedFixtureFileHashes': {name: sha((ROOT / name).read_bytes()) for name in sorted(owned) if name != removal_path},
        'temporaryRegistrations': registrations,
        'sharedRecordsRequireTargetedRemoval': ['materials/catalog.json', 'books/reviewed-books.json',
            'books/prepared-library.json', 'books/published-library.json', 'books/published-bundles.json'],
        'qualification': 'Ownership inventory only. Preserve unrelated shared entries and recorded publication history; bind any future release artifacts separately before cleanup.',
    })
    return manifest


def validate(manifest):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / 'books'))
    from publish_approved_material import prepare
    from source_literal_text import check_bound_text
    from material_order import validate_group
    results = []
    for row in manifest['scopes']:
        path = ROOT / row['handoff']['path']
        writes, receipt = prepare(ROOT, path)
        reader = read(ROOT / row['reader']['path'])
        block = reader['sections'][0]['blocks'][0]
        require(check_bound_text(ROOT, BODY, reader, block['sourceLiteralProof'], exact=True) == BODY,
                'Exact source literal validation failed')
        validate_group([reader])
        require(receipt['sourceApprovalCreated'] is False and receipt['preparationScopeCreated'] is True,
                'Unexpected source-intake behavior for missing scope')
        results.append({'language': row['language'], 'collection': row['collection'],
                        'materialId': row['materialId'], 'validatedWithoutApplying': True,
                        'generatedReaderSHA256': sha(writes[row['expectedGeneratedRecords']['currentReader']])})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('sources', 'finish', 'validate'))
    args = parser.parse_args()
    spec = specification()
    if args.phase == 'sources':
        print(json.dumps({'sourceRecords': sources(spec)}, ensure_ascii=False, indent=2))
    elif args.phase == 'finish':
        manifest = finish(spec, sources(spec))
        print(json.dumps({'manifest': binding(BASE / 'matrix-manifest.json'), 'scopeCount': len(manifest['scopes'])}))
    else:
        result = validate(read(BASE / 'matrix-manifest.json'))
        print(json.dumps({'validatedScopes': len(result), 'results': result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
