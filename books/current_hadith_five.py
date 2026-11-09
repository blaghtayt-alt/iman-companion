"""Import the exact already-published Filipino fifth Essential Iman lesson.

The source publisher supplied a complete ordinary reader, including its notes
and attribution, but omitted its central catalogue registration. This adapter
does not translate, rewrite, renumber or create a new review approval.
"""
from copy import deepcopy
import hashlib
import json
import re

from book_edition_scope import available, canonical, key, pinned, select
from bibliography import expand_verse_key, native_text
from build_books import check_unit
from source_literal_text import normalize_lines, proof_for

SCHEMA = 'iman-current-filipino-hadith-five-source-bindings-v1'
PROJECTION = 'books/source-projections/current-filipino-hadith-five.json'
ADAPTER = 'current-reviewed-filipino-hadith-five-v1'
IDENTITY = ('essential-hadith', 'fil', 'essential-01-005')
PUBLICATION = '27ca53b72b0183faa91fb5620df8b02950c01f02'
JSON_PATH = 'materials/hadith/essential-fil/005.json'
TEXT_PATH = 'materials/hadith/essential-fil/005.txt'
INDEX_PATH = 'materials/hadith/essential-01-005/README.md'
ARABIC_PATH = 'materials/hadith/essential-ar/01/005.json'
ARABIC_MD = 'materials/hadith/essential-ar/01/005.md'
# Observed Git blobs in the original reviewed source publication. The current
# Arabic JSON was also compared in full with the file at that commit.
PUBLISHED_BLOBS = {
    JSON_PATH: 'ee370f395e11b38a70ec27a900959dde80b6b479',
    TEXT_PATH: '9f9d0469170d5e96afef8d549e130c8cf3037f88',
    INDEX_PATH: '4df52748d7cecc72cfef0e3d668cd0108d67fe01',
}
ARABIC_CANONICAL_SHA256 = '49de5e705e8268207b692c781db16bc9be0d83d9f69683947dc8a92a5b4a62be'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def binding(root, path):
    return {'path': path, 'sha256': sha((root / path).read_bytes())}


def catalogue_entry():
    return {'collection': IDENTITY[0], 'language': IDENTITY[1], 'id': IDENTITY[2],
            'json': JSON_PATH, 'markdown': TEXT_PATH, 'chapter': 1, 'lesson': 5,
            'translationStatus': 'ai-translated-needs-verification',
            'status': 'current-app-edition'}


def _source(root):
    for path, expected in PUBLISHED_BLOBS.items():
        raw = (root / path).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if blob != expected:
            raise ValueError('Filipino fifth lesson differs from its existing reviewed publication: ' + path)
    arabic = json.loads((root / ARABIC_PATH).read_bytes())
    if sha(canonical(arabic)) != ARABIC_CANONICAL_SHA256:
        raise ValueError('Filipino fifth lesson Arabic source has changed since review')
    payload = json.loads((root / JSON_PATH).read_bytes())
    if (payload.get('schema'), payload.get('id'), payload.get('language')) != (
            'iman-essential-fil005-reviewed-v1', IDENTITY[2], 'fil'):
        raise ValueError('Unexpected reviewed Filipino fifth lesson identity')
    text = payload.get('reader')
    if not isinstance(text, str) or sha(text.encode('utf8')) != payload.get('readerSHA256'):
        raise ValueError('Filipino fifth lesson complete reader hash differs')
    if (root / TEXT_PATH).read_text(encoding='utf8') != text:
        raise ValueError('Filipino fifth lesson ordinary and structured readers differ')
    if not text.startswith(payload.get('title', '') + '\n\n') or not payload.get('title'):
        raise ValueError('Filipino fifth lesson title is not its exact opening')
    if 'available as reviewed ordinary text' not in (root / INDEX_PATH).read_text(encoding='utf8'):
        raise ValueError('Filipino fifth lesson has no original publication qualification')
    previous = 0
    for span in payload.get('quranSpans', []):
        start, end = span.get('start'), span.get('end')
        if (type(start) is not int or type(end) is not int
                or not previous <= start < end <= len(text)):
            raise ValueError('Invalid or overlapping original Quran span')
        expand_verse_key(span['ref'])
        previous = end
    return payload


def snapshot(root, catalog, source_commit):
    rows = [row for row in catalog['entries'] if key(row) == IDENTITY and available(row)]
    if len(rows) != 1 or {k: v for k, v in rows[0].items() if k != 'bookReaderUnit'} != catalogue_entry():
        raise ValueError('Register the exact current Filipino fifth lesson once before snapshotting')
    payload = _source(root)
    return {'schema': SCHEMA, 'sourceCommit': source_commit, 'sourceApprovalCreated': False,
            'records': [{
                'collection': IDENTITY[0], 'language': 'fil', 'id': IDENTITY[2],
                'chapter': 1, 'lesson': 5,
                'catalogEntry': {k: deepcopy(v) for k, v in rows[0].items() if k != 'bookReaderUnit'},
                'sourceFiles': [binding(root, path) for path in (JSON_PATH, TEXT_PATH)],
                'sourceConditions': [binding(root, path) for path in (INDEX_PATH, ARABIC_PATH, ARABIC_MD)],
                'readingPointer': ['reader'],
                'existingPublication': {'commit': PUBLICATION, 'gitBlobs': dict(PUBLISHED_BLOBS),
                    'arabicSourceCanonicalSHA256': ARABIC_CANONICAL_SHA256},
                'readerSHA256': payload['readerSHA256'],
                'qualification': 'Existing published reviewed ordinary text, with its original embedded source notes and attribution. Human verification remains needed. No new translation or finished-book approval is created.'
            }]}


def records(root, declaration):
    found = []
    for evidence in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(root, evidence))
        if data.get('schema') == SCHEMA:
            found.extend((record, evidence) for record in data.get('records', [])
                         if record.get('language') == declaration.get('language'))
    if len(found) > 1:
        raise ValueError('Duplicate Filipino fifth-lesson source inventory')
    return found


def validate_record(root, record, row, catalog):
    if key(row) != IDENTITY or key(record) != IDENTITY or not available(row):
        raise ValueError('Filipino fifth-lesson source is not a current available reader')
    if {k: v for k, v in row.items() if k != 'bookReaderUnit'} != record.get('catalogEntry'):
        raise ValueError('Filipino fifth-lesson catalogue changed after its source binding')
    expected_publication = {'commit': PUBLICATION, 'gitBlobs': PUBLISHED_BLOBS,
                            'arabicSourceCanonicalSHA256': ARABIC_CANONICAL_SHA256}
    if record.get('existingPublication') != expected_publication:
        raise ValueError('Filipino fifth-lesson publication evidence differs')
    expected_paths = {JSON_PATH, TEXT_PATH, INDEX_PATH, ARABIC_PATH, ARABIC_MD}
    files = record.get('sourceFiles', []) + record.get('sourceConditions', [])
    if {item.get('path') for item in files} != expected_paths or len(files) != len(expected_paths):
        raise ValueError('Filipino fifth-lesson source inventory omits or duplicates inputs')
    for item in files:
        pinned(root, item)
    payload = _source(root)
    if record.get('readerSHA256') != payload['readerSHA256'] or record.get('readingPointer') != ['reader']:
        raise ValueError('Filipino fifth-lesson reader binding differs')
    return files


def literal_sources(record):
    return [{'source': item, 'pointer': ['reader']}
            for item in record['sourceFiles'] if item['path'] == JSON_PATH]


def normalize(root, catalog, row, record, evidence):
    files = validate_record(root, record, row, catalog)
    payload = _source(root)
    reading = normalize_lines(payload['reader'])
    if reading != payload['reader']:
        raise ValueError('Original Quran span offsets require unchanged source line endings')
    title = payload['title']
    native_text(title, 'fil')
    source = next(item for item in files if item['path'] == JSON_PATH)
    blocks = []
    positions = []
    cursor = len(title)
    for piece in re.split(r'(\n[ \t]*\n+)', reading[cursor:]):
        text = piece.strip()
        start = cursor + len(piece) - len(piece.lstrip())
        cursor += len(piece)
        if not text:
            continue
        end = start + len(text)
        spans = []
        offset = start
        for supplied in payload['quranSpans']:
            a, b = supplied['start'], supplied['end']
            if b <= start or a >= end:
                continue
            if not start <= a < b <= end:
                raise ValueError('A source Quran span crosses an unrepresented paragraph boundary')
            if a > offset:
                spans.append({'text': reading[offset:a], 'role': 'body'})
            spans.append({'text': reading[a:b], 'role': 'quran',
                          'verseKeys': [supplied['ref']], 'explicitSourceReferencePlaced': True})
            offset = b
        if offset < end:
            spans.append({'text': reading[offset:end], 'role': 'hadith' if not blocks else 'body'})
        block = {'kind': 'paragraph', 'text': text, 'spans': spans}
        try:
            native_text(text, 'fil')
        except ValueError:
            block['sourceLiteralProof'] = proof_for(record, evidence, source, start, end, text)
        blocks.append(block)
        positions.append({'start': start, 'end': end, 'sha256': sha(text.encode('utf8'))})
    body = ''.join(block['text'] for block in blocks)
    if re.sub(r'\s+', '', title + body) != re.sub(r'\s+', '', reading):
        raise ValueError('Filipino fifth-lesson reading was shortened or reordered')
    bindings = {item['path']: item['sha256'] for item in files + [evidence]}
    unit = {'schema': 'iman-book-unit-v1', 'id': row['id'], 'language': 'fil',
            'collection': 'hadith', 'hadithEdition': 'new-extended',
            'chapter': 1, 'lesson': 5, 'sourceLessonNumber': 5, 'order': 1005,
            'ordering': {'kind': 'chapter-lesson', 'chapter': 1, 'lesson': 5},
            'title': title, 'complete': True, 'reviewGate': 'published-current',
            'sourceHashes': [source['sha256']],
            'inputBindings': [{'path': path, 'sha256': value} for path, value in sorted(bindings.items())],
            'catalogBindings': [{'collection': row['collection'], 'language': 'fil', 'id': row['id']}],
            'sections': [{'blocks': blocks}], 'readerTextSHA256': sha(body.encode('utf8')),
            'sourceReferencePreservation': {
                'schema': 'iman-source-reference-preservation-v1',
                'auditMode': 'literal-source-and-qualification-fidelity',
                'sourceReferences': len(payload['quranSpans']), 'preservedReferences': len(payload['quranSpans']),
                'sourceQualifications': 0, 'preservedQualifications': 0,
                'sourceParagraphs': len(blocks), 'preservedParagraphs': len(blocks),
                'lostReferences': 0, 'lostQualifications': 0, 'lostParagraphs': 0},
            'provenance': {'adapter': ADAPTER, 'existingPublication': deepcopy(record['existingPublication']),
                'sourceReadingSHA256': payload['readerSHA256'], 'sourceReadingPositions': positions,
                'originalSourceArabicDigest': payload['sourceArabicDigest'],
                'originalSourceArabicDigestRetainedWithoutReinterpretingItsAlgorithm': True,
                'sourceQuranSpans': deepcopy(payload['quranSpans']),
                'embeddedNotesAndReferencesPreservedInCompleteReading': True,
                'reviewQualification': record['qualification'],
                'sourceApprovalCreated': False, 'humanCertification': False}}
    check_unit(unit, unit, root=root)
    return unit


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    if declaration.get('language') != 'fil' or declaration.get('collection') != 'hadith':
        return []
    selected, _ = select(root, catalog, declaration)
    selected = {key(row): row for row in selected}
    excluded = set(excluded_catalog_keys)
    return [normalize(root, catalog, selected[IDENTITY], record, evidence)
            for record, evidence in records(root, declaration)
            if IDENTITY in selected and IDENTITY not in excluded]
