"""Prepare the exact current Arabic Essential Iman course for the book renderer.

The projection is a compact inventory of source bytes, not a new scholarly
approval. Supplied quotation colors do not distinguish Hadith from scholars, so
blue commentary remains a generic quotation. Only explicitly written Quran
identities are formatted as typed labels. Original report/book references and
their qualifications remain literal notes; website record IDs are never used.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import unicodedata

from adapt_ar_articles import current_record, approved_exclusions
from bibliography import native_text
from book_references import reference
from build_books import check_unit, inside

ADAPTER = 'arabic-essential-hadith-v1'
SCHEMA = 'iman-arabic-essential-hadith-projection-v1'
MATERIAL_INDEX = 'materials/hadith/essential-ar/catalog.json'
QURAN_COLORS = {'176744', '21724A'}
QUOTE_COLORS = {'204D80', '165A93'}
REFERENCE_COLORS = {'5B626B', '666666'}
COLORS = QURAN_COLORS | QUOTE_COLORS | REFERENCE_COLORS | {'000000', None}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf8')


def _positive(value):
    return type(value) is int and 0 < value < 1000


def _paragraph(paragraph):
    if (not isinstance(paragraph, dict) or not isinstance(paragraph.get('text'), str)
            or type(paragraph.get('sourceParagraph')) is not int or paragraph['sourceParagraph'] < 0
            or not isinstance(paragraph.get('runs'), list)
            or not isinstance(paragraph.get('hyperlinks'), list)):
        raise ValueError('Invalid Essential Hadith source paragraph')
    runs = paragraph['runs']
    if any(not isinstance(r, dict) or not isinstance(r.get('text'), str)
           or r.get('color') not in COLORS for r in runs):
        raise ValueError('Unknown Essential Hadith source run or color')
    if ''.join(r['text'] for r in runs) != paragraph['text']:
        raise ValueError('Essential Hadith source runs differ from paragraph text')


def _path(root, base, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('Invalid Essential Hadith source path')
    path = inside(root, (base / value).as_posix())
    if not path.is_relative_to((root / base).resolve()):
        raise ValueError('Essential Hadith source path leaves its course')
    return path.relative_to(root.resolve()).as_posix()


def _snapshot(root, catalog, material_index, *, excluded_ids=()):
    """Validate published identities and return bindings plus exact source data."""
    root = Path(root).resolve()
    index_path = inside(root, material_index)
    index_raw = index_path.read_bytes()
    course = json.loads(index_raw)
    if (course.get('schema'), course.get('id'), course.get('language')) != (
            'essential-arabic-source-course-v1', 'essential-iman-hadiths', 'ar'):
        raise ValueError('Unexpected Essential Hadith course index')
    base = Path(material_index).parent
    rows = [e for e in catalog['entries'] if e.get('collection') == 'essential-hadith'
            and e.get('language') == 'ar' and current_record(e) and str(e['id']) not in excluded_ids]
    entries = {e['id']: e for e in rows}
    all_indexed_rows = [e for e in course['lessons'] if current_record(e)]
    indexed_rows = [e for e in all_indexed_rows if str(e['id']) not in excluded_ids]
    indexed = {e['id']: e for e in indexed_rows}
    if (not entries or len(entries) != len(rows) or len(indexed) != len(indexed_rows)
            or set(entries) != set(indexed)):
        raise ValueError('Current Essential Hadith coverage changed or is ambiguous')
    positions = [(e.get('chapter'), e.get('lesson')) for e in rows]
    if (any(not _positive(c) or not _positive(l) for c, l in positions)
            or len(set(positions)) != len(positions)):
        raise ValueError('Essential Hadith order is missing or ambiguous')
    chapters = [c for c in course['chapters'] if current_record(c)]
    if excluded_ids:
        # Fully replaced chapters no longer supply legacy units. A partial
        # replacement still binds the exact entire shared chapter source below.
        replaced_chapters = {c['number'] for c in chapters
                             if (members := [e for e in all_indexed_rows if e['chapter'] == c['number']])
                             and all(str(e['id']) in excluded_ids for e in members)}
        chapters = [c for c in chapters if c['number'] not in replaced_chapters]
    bychapter = {c.get('number'): c for c in chapters}
    if (len(bychapter) != len(chapters) or any(not _positive(n) for n in bychapter)
            or set(bychapter) != {c for c, _ in positions}):
        raise ValueError('Essential Hadith chapter coverage changed or is ambiguous')
    projection = {'schema': SCHEMA, 'language': 'ar', 'collection': 'hadith',
                  'edition': 'new-extended', 'materialIndex': material_index,
                  'materialIndexSHA256': sha(index_raw), 'chapters': [], 'lessons': []}
    chapter_sources = {}
    for number, item in sorted(bychapter.items()):
        paths = {k: _path(root, base, item[k]) for k in ('json', 'markdown')}
        raws = {k: inside(root, path).read_bytes() for k, path in paths.items()}
        source = json.loads(raws['json'])
        count = sum(e['chapter'] == number for e in all_indexed_rows)
        if (source.get('id') != item.get('id') or item.get('id') != f'essential-{number:02d}'
                or source.get('number') != number or source.get('lessonCount') != count
                or item.get('lessons') != count
                or source.get('originalTitle') != item.get('originalTitle')
                or source.get('displayTitle') != item.get('displayTitle')
                or not re.fullmatch('[a-f0-9]{64}', source.get('sourceDocumentSHA256', ''))):
            raise ValueError('Essential Hadith chapter identity changed')
        title = source.get('displayTitle') or source['originalTitle']
        if not raws['markdown'].decode('utf8').replace('\r\n', '\n').startswith('# ' + title + '\n'):
            raise ValueError('Essential Hadith chapter display title differs')
        for key in ('introduction', 'bibliography'):
            if not isinstance(source.get(key), list):
                raise ValueError('Missing Essential Hadith chapter matter')
            for p in source[key]:
                _paragraph(p)
        binding = {'id': item['id'], 'number': number, 'title': title,
                   'originalTitle': source['originalTitle'], 'lessonCount': count,
                   'sourceSHA256': source['sourceDocumentSHA256'],
                   **paths, **{k + 'SHA256': sha(v) for k, v in raws.items()}}
        projection['chapters'].append(binding)
        chapter_sources[number] = (binding, source)
    lesson_sources = {}
    for ident in sorted(entries, key=lambda i: (entries[i]['chapter'], entries[i]['lesson'])):
        row, item = entries[ident], indexed[ident]
        chapter, lesson = row['chapter'], row['lesson']
        paths = {k: _path(root, base, item[k]) for k in ('json', 'markdown')}
        if (ident != f'essential-{chapter:02d}-{lesson:03d}'
                or (item.get('chapter'), item.get('lesson')) != (chapter, lesson)
                or any(row.get(k) != paths[k] for k in paths)
                or row.get('translationStatus') != 'supplied-arabic-structurally-screened'):
            raise ValueError('Essential Hadith lesson identity or path changed: ' + ident)
        raws = {k: inside(root, path).read_bytes() for k, path in paths.items()}
        source = json.loads(raws['json'])
        chapter_binding, chapter_source = chapter_sources[chapter]
        if (source.get('schema') != 'essential-arabic-source-lesson-v1'
                or (source.get('id'), source.get('chapter'), source.get('lesson')) != (ident, chapter, lesson)
                or source.get('originalTitle') != row.get('originalTitle')
                or source.get('originalTitle') != item.get('originalTitle')
                or source.get('chapterOriginalTitle') != chapter_source['originalTitle']
                or row.get('sourceHashes') != [chapter_binding['sourceSHA256']]
                or _path(root, Path(paths['json']).parent, source.get('sourceChapter')) != chapter_binding['json']):
            raise ValueError('Essential Hadith source identity changed: ' + ident)
        paragraphs = [source[k] for k in ('sourceHeading', 'mainNarration', 'reference')] + source['commentary']
        for p in paragraphs:
            _paragraph(p)
        source_numbers = [p['sourceParagraph'] for p in paragraphs]
        heading = re.fullmatch(r'\s*(\d+)\s+(.+?)\s*', source['sourceHeading']['text'])
        if (not source['mainNarration']['text'].strip() or not source['reference']['text'].strip()
                or not source['commentary'] or source['reference']['text'] != row.get('sourceReference')
                or source['reference']['text'] != item.get('sourceReference')
                or source_numbers != sorted(set(source_numbers))
                or not heading or int(heading[1]) != lesson
                or heading[2] != source['originalTitle'].strip()):
            raise ValueError('Essential Hadith main narration/reference differs: ' + ident)
        expected = '# ' + paragraphs[0]['text'] + '\n\n' + '\n\n'.join(p['text'] for p in paragraphs[1:])
        if not raws['markdown'].decode('utf8').replace('\r\n', '\n').startswith(expected + '\n\n'):
            raise ValueError('Essential Hadith Markdown differs from JSON reading: ' + ident)
        if (not isinstance(source.get('referenceQualifications'), list)
                or not all(isinstance(q, str) and q.strip() for q in source['referenceQualifications'])
                or not isinstance(source.get('externalSourceLinks'), list)):
            raise ValueError('Invalid Essential Hadith source qualifications/links')
        binding = {'id': ident, 'chapter': chapter, 'lesson': lesson,
                   'title': source['originalTitle'], 'sourceSHA256': chapter_binding['sourceSHA256'],
                   'catalogEntrySHA256': sha(canonical(row)), **paths,
                   **{k + 'SHA256': sha(v) for k, v in raws.items()}}
        projection['lessons'].append(binding)
        lesson_sources[ident] = source
    return projection, chapter_sources, lesson_sources


def export_projection(root, catalog, material_index=MATERIAL_INDEX):
    """Inventory exact eligible source bytes; does not approve or write anything."""
    return _snapshot(root, catalog, material_index)[0]


def _role(run, main=False):
    if run.get('color') in QURAN_COLORS:
        return 'quran'
    if run.get('color') in QUOTE_COLORS:
        return 'hadith' if main else 'related'
    return 'body'


def _source_reference(text, names, quran):
    # Source Word exports split some labels around bidi/word-joiner runs. These
    # format controls are not letters or locators; ignore them for recognition
    # only, retaining every original character in the reversible source map.
    plain = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
    return reference(plain.strip().strip(' []()（）'), 'ar', names, quran)


def _format_paragraph(paragraph, names, quran, *, main=False, references=True):
    """Move only source-marked reference furniture, keeping a reversible map."""
    spans, offsets, moves, reference_positions = [], [], [], []
    offset = 0
    for number, run in enumerate(paragraph['runs']):
        text = run['text']
        spans.append({'text': text, 'role': _role(run, main), 'bold': bool(run.get('bold')),
                      'sourceRunIndex': number})
        offsets.append(offset)
        offset += len(text)
    number = 0
    while references and number < len(spans):
        run = paragraph['runs'][number]
        if run.get('color') not in REFERENCE_COLORS or not run['text'].strip():
            number += 1
            continue
        end = number + 1
        literal = run['text']
        # Retain run boundaries, but recognize one bracketed source label when
        # Word stored its name, number range and closing bracket separately.
        if literal.strip().startswith('['):
            while (not literal.strip().endswith(']') and end < len(spans)
                   and paragraph['runs'][end].get('color') in REFERENCE_COLORS):
                literal += paragraph['runs'][end]['text']
                end += 1
        binding = _source_reference(literal, names, quran)
        if binding or (literal.strip().startswith('[') and literal.strip().endswith(']')):
            metadata = ({'verseKeys': binding['verseKeys']} if binding and binding.get('verseKeys')
                        else {'noteTexts': [native_text(literal, 'ar')]})
            parts = [{'sourceRunIndex': i, 'literal': paragraph['runs'][i]['text']} for i in range(number, end)]
            for i in range(number, end):
                spans[i].update({'text': '', 'role': 'body'})
            spans[end - 1].update(metadata)
            start = offsets[number]
            moves.append({'sourceRunIndex': number, 'sourceRunParts': parts,
                          'sourceCP': [start, start + len(literal)], 'literal': literal,
                          'binding': deepcopy(binding), 'presentation': deepcopy(metadata)})
            reference_positions.append((start, start + len(literal), binding))
        number = end
    # Validate reversibility without normalizing punctuation, whitespace or quotes.
    moved_runs = {p['sourceRunIndex']: p['literal'] for m in moves for p in m['sourceRunParts']}
    restored = ''.join(moved_runs.get(i, span['text']) for i, span in enumerate(spans))
    if restored != paragraph['text']:
        raise ValueError('Hadith source prose changed during reference presentation')
    groups, offset = [], 0
    for run in paragraph['runs']:
        role = _role(run, main)
        end = offset + len(run['text'])
        if role in {'quran', 'related', 'hadith'} and run['text'].strip():
            if groups and groups[-1][2] == role and not paragraph['text'][groups[-1][1]:offset].strip():
                groups[-1] = (groups[-1][0], end, role)
            else:
                groups.append((offset, end, role))
        offset = end
    missing_quran = missing_quotes = 0
    for start, end, role in groups if references else []:
        adjacent = [(a, b, value) for a, b, value in reference_positions if a >= end
                    and not paragraph['text'][end:a].strip(' \t\r\n،؛,:.!?؟”“«»﴿﴾()（）[]')]
        bound = any(value and value.get('verseKeys') for _, _, value in adjacent) if role == 'quran' else bool(adjacent) or main
        if not bound:
            if role == 'quran':
                missing_quran += 1
            else:
                missing_quotes += 1
    return ({'kind': 'heading' if str(paragraph.get('style', '')).startswith('Heading') else 'paragraph',
             'text': ''.join(s['text'] for s in spans), 'spans': spans,
             'sourceParagraph': paragraph['sourceParagraph']}, moves,
            {'unboundQuranSegments': missing_quran, 'unboundQuotationSegments': missing_quotes,
             'untypedLiteralSourceReferences': sum(m['binding'] is None for m in moves)})


def _verify_source_preservation(source, blocks, transformations, introduction=(), bibliography=()):
    """Check actual preservation, without treating parser limits as source flaws."""
    originals = [('chapter-introduction', p) for p in introduction]
    originals += [('main-narration', source['mainNarration']), ('main-reference', source['reference'])]
    originals += [('commentary', p) for p in source['commentary']]
    originals += [('chapter-bibliography', p) for p in bibliography]
    source_blocks = [b for b in blocks if 'sourceParagraph' in b]
    actual = {(b.get('sourceOrigin'), b.get('sourceParagraph')): b for b in source_blocks}
    if len(actual) != len(originals) or len(source_blocks) != len(originals):
        raise ValueError('Hadith source paragraph was lost or duplicated')
    for origin, original in originals:
        block = actual.get((origin, original['sourceParagraph']))
        if block is None:
            raise ValueError('Hadith source paragraph was lost')
        moves = [m for m in transformations if m['sourceOrigin'] == origin
                 and m['sourceParagraph'] == original['sourceParagraph']]
        if origin == 'main-reference':
            restored = block['text']
        else:
            moved = {p['sourceRunIndex']: p['literal'] for m in moves for p in m['sourceRunParts']}
            if len(block['spans']) != len(original['runs']):
                raise ValueError('Hadith source run was lost')
            restored = ''.join(moved.get(i, span['text']) for i, span in enumerate(block['spans']))
        if restored != original['text']:
            raise ValueError('Hadith source paragraph/reference text changed')
        for move in moves:
            span = block['spans'][move['sourceRunParts'][-1]['sourceRunIndex']]
            if any(span.get(key) != value for key, value in move['presentation'].items()):
                raise ValueError('Hadith original source reference placement was lost')
    presented = [b['text'] for b in blocks]
    presented += [n for b in blocks for s in b.get('spans', []) for n in s.get('noteTexts', [])]
    for qualification in source['referenceQualifications']:
        if not any(qualification in text for text in presented):
            raise ValueError('Hadith original source qualification was lost')
    references = len(transformations) + 1  # Explicit inline placements plus the original main reference.
    return {'schema': 'iman-source-reference-preservation-v1',
            'auditMode': 'literal-source-and-qualification-fidelity',
            'sourceReferences': references, 'preservedReferences': references,
            'sourceQualifications': len(source['referenceQualifications']),
            'preservedQualifications': len(source['referenceQualifications']),
            'sourceParagraphs': len(originals), 'preservedParagraphs': len(originals),
            'lostReferences': 0, 'lostQualifications': 0, 'lostParagraphs': 0}


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    root = Path(root).resolve()
    if ((declaration.get('language'), declaration.get('collection'), declaration.get('adapter'))
            != ('ar', 'hadith', ADAPTER) or declaration.get('hadithEdition', 'new-extended') != 'new-extended'):
        raise ValueError('Unsupported Essential Hadith source adapter')
    raw = inside(root, declaration['projection']).read_bytes()
    if sha(raw) != declaration.get('projectionSHA256'):
        raise ValueError('Essential Hadith projection changed')
    excluded = approved_exclusions(root, catalog, declaration, excluded_catalog_keys)
    reviewed = json.loads(raw)
    if excluded and (reviewed.get('materialIndex') != declaration['materialIndex']
                     or sha(inside(root, declaration['materialIndex']).read_bytes()) != reviewed.get('materialIndexSHA256')):
        raise ValueError('Mixed Hadith shared material index changed; per-lesson approval cannot replace it')
    projection, chapters, lessons = _snapshot(root, catalog, declaration['materialIndex'], excluded_ids=excluded)
    if excluded:
        if any(reviewed.get(k) != projection[k] for k in ('schema', 'language', 'collection', 'edition', 'materialIndex', 'materialIndexSHA256')):
            raise ValueError('Essential Hadith shared projection identity changed')
        for kind in ('chapters', 'lessons'):
            frozen = {r['id']: r for r in reviewed[kind]}
            if len(frozen) != len(reviewed[kind]) or any(frozen.get(r['id']) != r for r in projection[kind]):
                raise ValueError('Uncovered Essential Hadith source or shared chapter binding changed')
    elif reviewed != projection:
        raise ValueError('Essential Hadith source bindings or current coverage changed')
    conf = json.loads((root / 'books/config.json').read_bytes())
    assets = [conf['quranText'], conf['surahNames']]
    values = []
    for asset in assets:
        asset_raw = inside(root, asset['path']).read_bytes()
        if sha(asset_raw) != asset['sha256']:
            raise ValueError('Canonical Quran or native names changed')
        values.append(json.loads(asset_raw))
    quran, names = values
    output = []
    for item in projection['lessons']:
        source = lessons[item['id']]
        chapter_binding, chapter = chapters[item['chapter']]
        chapter_lessons = [x for x in projection['lessons'] if x['chapter'] == item['chapter']]
        first, last = item['id'] == chapter_lessons[0]['id'], item['id'] == chapter_lessons[-1]['id']
        blocks, transformations = [], []
        parser_counts = {'unboundQuranSegments': 0, 'unboundQuotationSegments': 0,
                         'untypedLiteralSourceReferences': 0}
        main_reference = _source_reference(source['reference']['text'], names, quran)
        if not main_reference:
            parser_counts['untypedLiteralSourceReferences'] += 1

        def add(paragraph, origin, **options):
            block, moves, missing = _format_paragraph(paragraph, names, quran, **options)
            block['sourceOrigin'] = origin
            blocks.append(block)
            transformations.extend({'sourceOrigin': origin, 'sourceParagraph': paragraph['sourceParagraph'], **m}
                                   for m in moves)
            for key, value in missing.items():
                parser_counts[key] += value

        if first:
            for p in chapter['introduction']:
                add(p, 'chapter-introduction', references=False)
        add(source['mainNarration'], 'main-narration', main=True)
        blocks.append({'kind': 'note', 'text': native_text(source['reference']['text'], 'ar'),
                       'sourceOrigin': 'main-reference', 'sourceParagraph': source['reference']['sourceParagraph']})
        for p in source['commentary']:
            add(p, 'commentary')
        # Usually qualifications duplicate the original main reference. Preserve
        # every supplied qualification in provenance and render any extra once.
        for qualification in source['referenceQualifications']:
            if not any(qualification in p['text'] for p in [source['reference'], *source['commentary']]):
                blocks.append({'kind': 'note', 'text': native_text(qualification, 'ar'),
                               'sourceOrigin': 'reference-qualification'})
        if last:
            for p in chapter['bibliography']:
                add(p, 'chapter-bibliography', references=False)
        preservation = _verify_source_preservation(source, blocks, transformations,
                                                   chapter['introduction'] if first else (),
                                                   chapter['bibliography'] if last else ())
        diagnostics = {'auditMode': 'parser-placement-only-not-source-validity',
                       'quranGroupsWithoutImmediateTypedReference': parser_counts['unboundQuranSegments'],
                       'quotationGroupsWithoutImmediateReference': parser_counts['unboundQuotationSegments'],
                       'literalReferencesWithoutTypedClassification': parser_counts['untypedLiteralSourceReferences'],
                       'scope': 'Adjacency/parser diagnostics only; shared references, repeated quotations, source-book notes and context remain literal. No new scholarly review or typed identity is asserted.'}
        bindings = [{'path': obj[k], 'sha256': obj[k + 'SHA256']}
                    for obj in (item, chapter_binding) for k in ('json', 'markdown')]
        bindings += [{'path': declaration['materialIndex'], 'sha256': projection['materialIndexSHA256']},
                     {'path': declaration['projection'], 'sha256': sha(raw)}, *deepcopy(assets)]
        unit = {'schema': 'iman-book-unit-v1', 'id': item['id'], 'language': 'ar',
                'collection': 'hadith', 'hadithEdition': 'new-extended',
                'chapter': item['chapter'], 'chapterTitle': chapter_binding['title'],
                'lesson': item['lesson'], 'order': item['chapter'] * 1000 + item['lesson'],
                'title': item['title'], 'complete': True, 'reviewGate': 'published-current',
                'sourceHashes': [item['sourceSHA256']], 'inputBindings': bindings,
                'catalogBindings': [{'collection': 'essential-hadith', 'language': 'ar', 'id': item['id']}],
                'sections': [{'blocks': blocks}], 'readerTextSHA256': sha(''.join(b['text'] for b in blocks).encode('utf8')),
                'sourceReferencePreservation': preservation,
                'sourceReferenceDiagnostics': diagnostics,
                'provenance': {'adapter': ADAPTER, 'projectionSHA256': sha(raw),
                               'sourceStatus': source['status'], 'sourceLesson': deepcopy(source),
                               'mainReferenceClassification': deepcopy(main_reference),
                               'sourceChapter': {k: deepcopy(v) for k, v in chapter.items()
                                                 if k not in {'introduction', 'bibliography'}},
                               'chapterIntroduction': deepcopy(chapter['introduction']) if first else [],
                               'chapterBibliography': deepcopy(chapter['bibliography']) if last else [],
                               'referenceFurnitureTransformations': transformations,
                               'reviewScope': 'Exact currently published Arabic source intake; no new scholarly or reference certification.'}}
        check_unit(unit, {'language': 'ar', 'collection': 'hadith', 'id': item['id']}, quran)
        output.append(unit)
    return output
