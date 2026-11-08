"""Exact, existing translated Essential Hadith publication evidence.

This inventory is a bounded snapshot of material already published and reviewed
by the source producer. It does not approve a new translation or upgrade a
human-verification qualification. Later sources enter through the ordinary
approved reader transaction, rather than being inferred from a filename.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SCHEMA = 'iman-existing-translated-hadith-source-bindings-v1'
ADAPTER = 'reviewed-translated-essential-hadith-v1'
PROJECTION = 'books/source-projections/translated-essential-hadith.json'
GROUPS = {2: 'essentialSecond1003', 3: 'essentialThird1016', 4: 'essentialFourth1039'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')


def source_pointer(value, pointer):
    for part in pointer:
        if isinstance(value, list) and type(part) is int:
            value = value[part]
        elif isinstance(value, dict) and isinstance(part, str):
            value = value[part]
        else:
            raise ValueError('Invalid exact source-reader pointer')
    return value


def snapshot(root, catalog, source_commit):
    """Create a reviewable migration snapshot; never called by the publisher."""
    root = Path(root).resolve()
    from book_edition_scope import inside, available
    records = []
    for row in catalog['entries']:
        if row.get('collection') != 'essential-hadith' or row.get('language') == 'ar':
            continue
        lesson = row.get('lesson')
        if lesson not in GROUPS or not available(row):
            continue
        group_name = GROUPS[lesson]
        group = catalog.get(group_name, {})
        expected = f'essential-01-{lesson:03d}'
        if row.get('chapter') != 1 or row.get('id') != expected or group.get('unit') != expected or row['language'] not in group.get('languages', []):
            raise ValueError('Translated Hadith is not in its existing publication group')
        review_text = group.get('scope', group.get('status', ''))
        if 'independently model-reviewed' not in review_text:
            raise ValueError('Existing translated publication lacks its explicit model-review qualification')
        files = []
        for name in ('json', 'markdown'):
            path = row.get(name)
            if not path:
                raise ValueError('Reviewed translated Hadith lacks both reader formats')
            files.append({'path': path, 'sha256': sha(inside(root, path).read_bytes())})
        payload = json.loads(inside(root, row['json']).read_bytes())
        reader_pointer = ['reader'] if lesson == 2 else []
        reader = source_pointer(payload, reader_pointer)
        if not isinstance(reader, dict) or not isinstance(reader.get('reading'), str) or not reader.get('title'):
            raise ValueError('Unsupported installed translated lesson reader')
        conditions = []
        if payload.get('sourceDetails'):
            detail = (Path(row['json']).parent / payload['sourceDetails']).as_posix()
            conditions.append({'path': detail, 'sha256': sha(inside(root, detail).read_bytes())})
        evidence_path = group.get('index')
        if not evidence_path:
            raise ValueError('Published review group has no source-owner index')
        evidence = {'path': evidence_path, 'sha256': sha(inside(root, evidence_path).read_bytes())}
        records.append({
            'collection': 'essential-hadith', 'language': row['language'], 'id': row['id'],
            'chapter': 1, 'lesson': lesson,
            'catalogEntry': deepcopy(row), 'sourceFiles': files,
            'sourceConditions': conditions, 'readerPointer': reader_pointer,
            'readingPointer': [*reader_pointer, 'reading'],
            'existingPublication': {'sourceCommit': source_commit, 'catalogField': group_name,
                                    'group': deepcopy(group), 'evidence': evidence},
            'qualification': 'Existing independently model-reviewed translation; human verification remains needed. No new source, translation, Word or visual approval is created.'
        })
    records.sort(key=lambda item: (item['language'], item['chapter'], item['lesson']))
    return {'schema': SCHEMA, 'sourceCommit': source_commit, 'records': records,
            'sourceApprovalCreated': False, 'humanCertification': False,
            'scope': 'The exact currently published translated Essential Hadith lessons 01-002 through 01-004, in their explicitly listed languages only. Earlier heterogeneous 01-001 wrappers are not reinterpreted by this adapter.'}


def records(root, declaration):
    from book_edition_scope import pinned
    result = []
    for binding in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(root, binding))
        if data.get('schema') != SCHEMA:
            continue
        for item in data.get('records', []):
            if item.get('language') == declaration.get('language'):
                result.append((item, binding))
    if len({item['id'] for item, _ in result}) != len(result):
        raise ValueError('Duplicate translated Hadith source-review identity')
    return result


def validate_record(root, record, row, catalog):
    from book_edition_scope import pinned
    if record.get('collection') != 'essential-hadith' or record.get('chapter') != 1 or record.get('lesson') not in GROUPS:
        raise ValueError('Unsupported translated Hadith source-review identity')
    if (row.get('collection'), row.get('language'), str(row.get('id'))) != (record['collection'], record['language'], str(record['id'])):
        raise ValueError('Translated Hadith source-review identity differs')
    # bookReaderUnit is owned by a later typed publication. Such a row is
    # selected by typed_basis before this historical snapshot is considered.
    if {k: v for k, v in row.items() if k != 'bookReaderUnit'} != record.get('catalogEntry'):
        raise ValueError('Current translated Hadith catalogue changed after its bound review: ' + record['id'])
    publication = record.get('existingPublication', {})
    group = publication.get('group', {})
    if publication.get('catalogField') != GROUPS[record['lesson']] or not publication.get('sourceCommit'):
        raise ValueError('Missing existing translated Hadith publication provenance')
    if group != catalog.get(publication['catalogField']):
        raise ValueError('Translated Hadith publication qualification changed')
    if group.get('unit') != record['id'] or record['language'] not in group.get('languages', []):
        raise ValueError('Translated Hadith is outside its published language scope')
    text = group.get('scope', group.get('status', ''))
    if 'independently model-reviewed' not in text or 'human verification' not in text.lower():
        raise ValueError('Missing original translated review qualification')
    pinned(root, publication['evidence'])
    bindings = record.get('sourceFiles', []) + record.get('sourceConditions', [])
    by_path = {}
    for binding in bindings:
        if binding['path'] in by_path:
            raise ValueError('Duplicate translated source binding')
        by_path[binding['path']] = binding['sha256']
        pinned(root, binding)
    if not all(row.get(name) in by_path for name in ('json', 'markdown')):
        raise ValueError('Translated review omits an actual catalogue source')
    return bindings + [publication['evidence']]
