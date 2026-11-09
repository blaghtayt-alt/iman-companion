"""Faithfully prepare the existing reviewed translated Essential Hadith readers.

The complete source reading is the backbone, including its notes, glossary,
credits, literal references and qualifications. Structured spans supply colours
without rewriting words. Separately supplied translator notes absent from the
continuous reading become actual Word footnotes. No legacy short Hadith or new
translation is inferred.
"""
from copy import deepcopy
import hashlib
import json
import re

from bibliography import native_text
from book_edition_scope import select, pinned, key
from build_books import check_unit
from reviewed_hadith_sources import ADAPTER, records, validate_record, source_pointer, canonical
from source_literal_text import normalize_lines, proof_for

ROLES = {'plain': 'body', 'body': 'body', 'quran': 'quran', 'hadith': 'hadith',
         'scholar': 'scholar', 'meaning': 'meaning', 'note': 'note', 'source-note': 'note'}
NOTE_FIELDS = {'notes', 'readerNotes', 'readingNotes', 'publisherNotes',
               'mainNotes', 'mainPublisherNotes', 'referenceNotes',
               'requiredMeaningNotes', 'main_notes'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def note_fields(reader):
    """Enumerate actual display notes, excluding source audit/internal metadata."""
    found = []
    for field in reader:
        if field not in NOTE_FIELDS:
            continue
        values = reader.get(field, [])
        if not isinstance(values, list):
            raise ValueError('Unsupported translated reader-note list: ' + field)
        found.extend((None, field, number, note) for number, note in enumerate(values))
    for index, block in enumerate(reader.get('sections', reader.get('blocks', []))):
        for field in block:
            if field not in NOTE_FIELDS:
                continue
            values = block.get(field, [])
            if not isinstance(values, list):
                raise ValueError('Unsupported translated section-note list: ' + field)
            found.extend((index, field, number, note) for number, note in enumerate(values))
    for index, field, number, note in found:
        if not isinstance(note, dict) or not isinstance(note.get('text'), str):
            raise ValueError('Unsupported complete translated reader note')
        yield index, field, number, note


def structured_blocks(reader, lesson):
    if lesson == 2:
        blocks = [{'kind': 'main', 'text': reader.get('main'),
                   'parts': deepcopy(reader.get('mainParts', [])), 'sourceSection': 'main'}]
        blocks += [{**deepcopy(block), 'sourceSection': index}
                   for index, block in enumerate(reader.get('sections', []))]
    else:
        blocks = [{**deepcopy(block), 'sourceSection': index}
                  for index, block in enumerate(reader.get('blocks', []))]
    if not blocks or any(not isinstance(block.get('text'), str) or not block['text'] for block in blocks):
        raise ValueError('Translated Hadith is missing a complete main/section text')
    return blocks


def normalize(root, catalog, row, record, evidence):
    bindings = validate_record(root, record, row, catalog)
    binding_by_path = {item['path']: item for item in bindings}
    source_binding = binding_by_path[row['json']]
    payload = json.loads(pinned(root, source_binding))
    reader = source_pointer(payload, record['readerPointer'])
    if payload.get('id') != row['id'] or payload.get('language') != row['language']:
        raise ValueError('Translated reader identity differs from catalogue')
    language = row['language']
    title = reader['title']
    native_text(title, language)
    reading = normalize_lines(reader['reading'])
    start = len(reading) - len(reading.lstrip())
    if not reading.startswith(title, start):
        raise ValueError('Complete translated reading does not begin with its exact title')
    start += len(title)
    if start < len(reading) and not reading[start].isspace():
        raise ValueError('Translated title does not end on a source-text boundary')
    blocks = []
    body_records = []
    source_blocks = structured_blocks(reader, record['lesson'])
    positions = {}

    def add(text, begin, *, parts=None, kind='paragraph', source_section=None):
        if not text.strip():
            return
        if reading[begin:begin + len(text)] != text:
            raise ValueError('Translated paragraph lost its exact reading position')
        result = {'kind': kind, 'text': text}
        if parts:
            spans = []
            for part in parts:
                role = part.get('kind', 'plain')
                if role not in ROLES or not isinstance(part.get('text'), str):
                    raise ValueError('Unknown translated Hadith semantic source span')
                spans.append({'text': normalize_lines(part['text']), 'role': ROLES[role]})
            if ''.join(span['text'] for span in spans) != text:
                raise ValueError('Translated source spans differ from the exact paragraph')
            result['spans'] = spans
        try:
            native_text(text, language)
        except ValueError:
            # Exact immutable source text only. Generic native validation is not
            # changed, and render checks re-open these inputs independently.
            result['sourceLiteralProof'] = proof_for(record, evidence, source_binding,
                                                    begin, begin + len(text), text)
        if source_section is not None:
            positions[source_section] = len(blocks)
        blocks.append(result)
        body_records.append({'start': begin, 'end': begin + len(text),
                             'sha256': sha(text.encode('utf8'))})

    def gap(begin, end):
        cursor = begin
        for piece in re.split(r'(\n[ \t]*\n+)', reading[begin:end]):
            literal = piece.strip()
            if literal:
                first = len(piece) - len(piece.lstrip())
                add(literal, cursor + first)
            cursor += len(piece)

    cursor = start
    for original in source_blocks:
        text = normalize_lines(original['text'])
        begin = reading.find(text, cursor)
        if begin < 0:
            raise ValueError('Complete reading omits or reorders a translated source paragraph: ' + row['id'])
        gap(cursor, begin)
        add(text, begin, parts=original.get('parts'), source_section=original['sourceSection'])
        cursor = begin + len(text)
    gap(cursor, len(reading))

    # Except for the title already printed as a heading and paragraph-boundary
    # whitespace, every character of the original continuous reading survives.
    canonical_body = ''.join(reading[item['start']:item['end']] for item in body_records)
    if re.sub(r'\s+', '', canonical_body) != re.sub(r'\s+', '', reading[start:]):
        raise ValueError('Translated continuous-reading fidelity audit failed')
    missing_notes = []
    seen_notes = set()
    all_notes = []
    for section, field, number, note in note_fields(reader):
        text = normalize_lines(note['text'])
        if not text.strip():
            continue
        all_notes.append(text)
        if text in reading or text in seen_notes:
            continue
        native_text(text, language)
        target = positions.get('main') if section is None and field.startswith('main') else positions.get(section)
        if target is None:
            target = len(blocks) - 1
        block = blocks[target]
        block.setdefault('spans', [{'text': block['text'], 'role': 'body'}])[-1].setdefault('noteTexts', []).append(text)
        seen_notes.add(text)
        missing_notes.append({'id': note.get('id'), 'field': field,
                              'section': section, 'index': number, 'textSHA256': sha(text.encode('utf8')),
                              'placement': 'Word footnote at the source paragraph'})

    references = [reader.get('reference', '')]
    references += [block.get('credit', '') for block in source_blocks]
    references = [normalize_lines(text) for text in references if isinstance(text, str) and text.strip()]
    if any(text not in reading for text in references):
        raise ValueError('Complete translated reading omits an original reference')
    rendered_text = ''.join(block['text'] for block in blocks)
    presented_notes = [note for block in blocks for span in block.get('spans', [])
                       for note in span.get('noteTexts', [])]
    if any(text not in reading and text not in presented_notes for text in all_notes):
        raise ValueError('A supplied translated meaning/qualification note was lost')
    input_bindings = {item['path']: item['sha256'] for item in bindings + [evidence]}
    unit = {
        'schema': 'iman-book-unit-v1', 'id': row['id'], 'language': language,
        'collection': 'hadith', 'hadithEdition': 'new-extended',
        'chapter': record['chapter'], 'lesson': record['lesson'],
        'sourceLessonNumber': record['lesson'],
        'order': record['chapter'] * 1000 + record['lesson'],
        'ordering': {'kind': 'chapter-lesson', 'chapter': record['chapter'], 'lesson': record['lesson']},
        'title': title, 'complete': True, 'reviewGate': 'published-current',
        'sourceHashes': list(row.get('sourceHashes') or [source_binding['sha256']]),
        'inputBindings': [{'path': path, 'sha256': digest} for path, digest in sorted(input_bindings.items())],
        'catalogBindings': [{'collection': 'essential-hadith', 'language': language, 'id': row['id']}],
        'sections': [{'blocks': blocks}],
        'readerTextSHA256': sha(rendered_text.encode('utf8')),
        'sourceReferencePreservation': {
            'schema': 'iman-source-reference-preservation-v1',
            'auditMode': 'literal-source-and-qualification-fidelity',
            'sourceReferences': len(references), 'preservedReferences': len(references),
            'sourceQualifications': len(all_notes), 'preservedQualifications': len(all_notes),
            'sourceParagraphs': len(body_records), 'preservedParagraphs': len(body_records),
            'lostReferences': 0, 'lostQualifications': 0, 'lostParagraphs': 0,
        },
        'provenance': {
            'adapter': ADAPTER, 'sourceRecordSHA256': sha(canonical(record)),
            'sourceReadingSHA256': sha(reading.encode('utf8')), 'sourceReadingPositions': body_records,
            'sourceStatus': payload.get('status', row.get('translationStatus')),
            'sourceProvenance': deepcopy(reader.get('sourceProvenance')),
            'sourceDetails': deepcopy(payload.get('sourceDetails')),
            'sourceParagraphMetadata': [{k: deepcopy(v) for k, v in block.items() if k not in {'text', 'parts'}} for block in source_blocks],
            'additionalPublishedNotes': missing_notes,
            'reviewQualification': record['qualification'],
            'sourceApprovalCreated': False, 'humanCertification': False,
        },
    }
    check_unit(unit, {'language': language, 'collection': 'hadith', 'id': unit['id']}, root=root)
    return unit


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    if declaration.get('adapter') != ADAPTER or declaration.get('collection') != 'hadith' or declaration.get('language') == 'ar':
        raise ValueError('Unsupported translated Essential Hadith adapter scope')
    selected, _ = select(root, catalog, declaration)
    excluded = set(excluded_catalog_keys)
    by_id = {record['id']: (record, evidence) for record, evidence in records(root, declaration)}
    from current_source_registry import supplemental_records
    other_formats = {identity for identity, _, _, _ in supplemental_records(root, declaration)}
    result = []
    for row in sorted(selected, key=lambda item: (item.get('chapter', 0), item.get('lesson', 0))):
        if key(row) in excluded:
            continue
        if row['id'] not in by_id:
            if key(row) in other_formats:
                continue  # The indexer runs the exact registered format adapter.
            raise ValueError('Selected translated material needs its approved normalized reader transaction')
        record, evidence = by_id[row['id']]
        result.append(normalize(root, catalog, row, record, evidence))
    return result
