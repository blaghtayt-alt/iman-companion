"""Adapt the current, reviewed first Essential Hadith readers without rewriting.

The first translations predate the common 002--004 reader schema.  This module
uses their explicit reader fields and original note associations, rather than
silently omitting them or treating every string in a source envelope as prose.
Only the exact current catalogue rows and their pinned, existing review evidence
are eligible.  This migration creates no translation or source approval.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from bibliography import native_text
from locale_copy import locale
from source_literal_text import normalize_lines


SCHEMA = 'iman-current-hadith-first-source-bindings-v1'
ADAPTER = 'current-reviewed-first-essential-hadith-v1'
PROJECTION = 'books/source-projections/current-hadith-first.json'
UNIT_ID = 'essential-01-001'
ARABIC_CURRENT = 'materials/hadith/essential-ar/01/001.json'
ARABIC_REVIEWED = 'materials/hadith/essential-uz/sources/EXACT-SOURCE-ARABIC930.json'
SUPPORTED = ('bn', 'de', 'es', 'fa', 'hi', 'id', 'ms', 'pt-BR', 'ru', 'ur', 'uz')
SPEC = {
    'bn': ('reading', 'sections', 'notes', ('essentialFirst891',)),
    'de': ('reading', 'sections', 'main_notes', ('essentialFirst914',)),
    'es': ('reading', 'commentary', 'readerNotes', ('sourceCorrection911',)),
    'fa': ('reading', 'commentary', 'readerNotes', ('sourceCorrection911',)),
    'hi': ('reading', 'sections', 'notes', ('essentialFirst896', 'sourceCorrection911')),
    'id': ('lesson', 'commentary', 'readingNotes', ()),
    'ms': ('reading', 'commentarySections', 'requiredMeaningNotes', ('essentialFirst871',)),
    'pt-BR': ('reading', 'commentary', 'reading_notes', ('essentialFirst871',)),
    'ru': ('reading', 'sections', 'readerNotes', ('essentialFirst898', 'sourceCorrection911')),
    'ur': ('reading', 'sections', None, ('essentialFirst888', 'sourceCorrection911')),
    'uz': ('reader', 'sections', 'notes', ('essentialFirst934',)),
}
INDONESIAN_COMPANIONS = (
    'sources/ARABIC-REPORT-CONTEXT638.json',
    'sources/CATATAN-PELAJARAN-ID638.md',
    'sources/COMPLETE-READING-NOTES638.json',
    'sources/FINAL-LESSON001-ID638.json',
    'sources/GLOSSARY638.json',
    'sources/LESSON-NOTES-PROJECTION638.json',
    'sources/ORIGINAL-ARABIC-COMPANION638.json',
    'sources/SELECTED-PUBLISHER-PARENTS638.json',
    'sources/SOURCE-CONDITIONS638.json',
    'sources/TEXT-ONLY-SUCCESSOR675.md',
)
UZ_SOURCE_DIRECTORY = 'materials/hadith/essential-uz/sources/'
UZ_READABLE_COMPANIONS = (
    'SOURCE-TEXTS-QURAN930.txt',
    'SOURCE-TEXTS-HADITH930.txt',
    'SOURCE-TEXTS-ARABIC-ORIGINALS930.txt',
    'SOURCE-TEXTS-CONDITIONS930.txt',
)
# This is a finite public display allowlist, not a directory traversal. Review
# workpapers, private retrievals, historical originals and unused publications
# remain evidence inputs only and never become book text.
UZ_PUBLIC_TEXT_FILES = ('SOURCE-NOTES-UZ930.md',) + UZ_READABLE_COMPANIONS
UZ_FINAL_QUALIFICATION_FIELDS = (
    ('Quran',), ('mainQudsi',),
    *(('variants', index) for index in range(7)),
    *(('positiveSourceOffers', name) for name in
      ('QuranEncAndHEC', 'IslamHouse', 'Vorislar', 'MuslimBoard')),
    *(('openDuties', 'selectedSourceNote', name) for name in
      ('scope', 'publisher', 'version', 'sourceURL', 'printedExact',
       'correspondingArabic', 'assessment', 'publisherExplanationSupport',
       'noticeAuthorship', 'disposition', 'actualSourceDuty', 'timingLimit')),
    *(('openDuties', 'selectedSourceNote', 'completeActualParentEvidence', name, 'text')
      for name in ('UzbekMatn', 'ArabicMatn', 'UzbekExplanation',
                   'ArabicExplanation', 'UzbekBenefits')),
    *(('openDuties', name) for name in
      ('notifications', 'updates', 'advertising', 'quantities')),
    ('qualificationLimit',),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf8')


def pointer(value, path):
    for part in path:
        if isinstance(value, list) and type(part) is int:
            value = value[part]
        elif isinstance(value, dict) and isinstance(part, str):
            value = value[part]
        else:
            raise ValueError('Invalid first-Hadith reader pointer')
    return value


def _inside(root, relative):
    from book_edition_scope import inside
    return inside(Path(root).resolve(), relative)


def _binding(root, path):
    return {'path': path, 'sha256': sha(_inside(root, path).read_bytes())}


def _arabic_correspondence(root):
    """Reject superseded source translations, not just retired catalogue flags."""
    current = json.loads(_inside(root, ARABIC_CURRENT).read_bytes())
    reviewed = json.loads(_inside(root, ARABIC_REVIEWED).read_bytes())
    original = reviewed.get('originalLesson', {})
    if (current.get('id') != UNIT_ID or original.get('id') != UNIT_ID
            or len(current.get('commentary', [])) != 1
            or len(original.get('blocks', [])) != 3):
        raise ValueError('Unsupported current/reviewed Arabic first-lesson identity')
    current_texts = [current['mainNarration']['text'], current['reference']['text'],
                     current['commentary'][0]['text']]
    old_texts = [block['text'] for block in original['blocks']]
    if current.get('originalTitle') != original.get('title') or current_texts != old_texts:
        raise ValueError('First-Hadith translation belongs to a superseded Arabic reader')
    return {'titleSHA256': sha(current['originalTitle'].encode('utf8')),
            'paragraphSHA256': [sha(text.encode('utf8')) for text in current_texts],
            'comparison': 'exact title, main narration, reference and complete Arabic commentary'}


def _review_fields(root, catalog, language, payload):
    """Read source-owner review dispositions; never upgrade an author status."""
    status = json.loads(_inside(root, 'materials/translation-status.json').read_bytes())
    group_names = SPEC[language][3]
    catalog_fields = {name: deepcopy(catalog.get(name)) for name in group_names}
    status_fields = {name: deepcopy(status.get(name)) for name in group_names}
    for name in group_names:
        a, b = catalog_fields[name], status_fields[name]
        if not isinstance(a, dict) or not isinstance(b, dict):
            raise ValueError('Missing existing first-Hadith review evidence: ' + name)
        if name == 'sourceCorrection911':
            languages = a.get('correctedLocales', []) + a.get('newFirstLessons', [])
            if language not in languages or language not in b.get('languages', []):
                raise ValueError('First-Hadith correction is outside its reviewed languages')
        elif a.get('unit') != UNIT_ID or language not in a.get('languages', []):
            raise ValueError('First-Hadith reader is outside its reviewed publication group')
        review = b.get('status', '').lower()
        if 'independently model-reviewed' not in review or 'human verification' not in review:
            raise ValueError('Missing first-Hadith model-review qualification')
    if language == 'id':
        reader = payload.get('lesson', {})
        final = reader.get('provenance', {}).get('independentFinal638', {})
        if (not reader.get('reviewStatus', '').startswith('DISTINCT_INDEPENDENT_FINAL638_QUALIFIED_COMPLETE_')
                or final.get('differentFromMain635And659') is not True):
            raise ValueError('Indonesian first lesson lacks its distinct whole-reader review')
    elif not payload.get('status', '').startswith('Independent model-assisted'):
        raise ValueError('First-Hadith wrapper lacks its existing review qualification')
    return {'catalogFields': catalog_fields, 'translationStatusFields': status_fields,
            'sourceStatus': payload.get('status', payload.get('review'))}


def _source_files(root, row, payload):
    files = [_binding(root, row[name]) for name in ('json', 'markdown')]
    directory = Path(row['json']).parent
    if row['language'] == 'id':
        files.extend(_binding(root, (directory / name).as_posix())
                     for name in INDONESIAN_COMPANIONS)
    else:
        from book_edition_scope import pinned
        declared = payload.get('sourceFiles')
        if not isinstance(declared, list) or not declared:
            raise ValueError('Missing current first-Hadith source companions')
        for source in declared:
            item = {'path': (directory / source['path']).as_posix(),
                    'sha256': source['sha256']}
            pinned(Path(root), item)
            files.append(item)
    if len({item['path'] for item in files}) != len(files):
        raise ValueError('Duplicate first-Hadith source binding')
    return files


def _source_conditions(root, files):
    existing = {item['path'] for item in files}
    return [_binding(root, path) for path in (ARABIC_CURRENT, ARABIC_REVIEWED)
            if path not in existing]


def _section_fields(reader, section_key):
    sections = reader.get(section_key)
    if not isinstance(sections, list) or len(sections) != 49:
        raise ValueError('First-Hadith reader must contain all 49 current commentary sections')
    for index, section in enumerate(sections):
        actual = section.get('index', section.get('id'))
        if actual not in (index + 1, 'S' + str(index + 1), 'en508-p' + str(index + 1).zfill(2)):
            raise ValueError('First-Hadith commentary is missing, duplicated or reordered')
        if not isinstance(section.get('text'), str) or not section['text'].strip():
            raise ValueError('Empty first-Hadith commentary paragraph')
    return sections


def _note_targets(note, sections, reader, *, fixed=None):
    """Resolve only supplied identity/field/note links; never numeric guesswork."""
    if fixed is not None:
        return [fixed]
    aliases = {'main': -1}
    for index, section in enumerate(sections):
        aliases[str(section.get('id', section.get('index')))] = index
        aliases['S' + str(index + 1)] = index
    explicit = ([note['section']] if note.get('section') else note.get('sections', []))
    if explicit:
        if any(str(value) not in aliases for value in explicit):
            raise ValueError('Reader note refers to an unknown first-Hadith section')
        return sorted({aliases[str(value)] for value in explicit})
    targets = set()
    note_id = note.get('id')
    main = reader.get('mainNarration', reader.get('mainHadith', {}))
    main = main if isinstance(main, dict) else {}
    if note_id in reader.get('main_reader_note_ids', []) + main.get('reader_note_ids', []) + main.get('mandatoryNoteIds', []):
        targets.add(-1)
    quote_ids = {str(value) for value in [note.get('quoteId'), note.get('quote_identity'),
                                        note.get('linked_quote_identity')]
                 if value is not None}
    quote_ids.update(str(value) for value in note.get('relatedQuoteIds', []))
    fields = {str(value) for value in note.get('bound_field_ids', note.get('field_ids', []))}
    if note.get('field') is not None:
        fields.add(str(note['field']))
    if quote_ids & {'2'} or fields & {'2'}:
        targets.add(-1)
    for index, section in enumerate(sections):
        if note_id in section.get('reader_note_ids', []):
            targets.add(index)
        identities = {str(value) for key in ('canonicalQuoteIds', 'sourceQuoteIds', 'quote_identity_ids')
                      for value in section.get(key, [])}
        section_fields = {str(value) for value in section.get('field_ids', [])}
        for part in section.get('parts', section.get('segments', [])):
            for key in ('identity', 'quoteId'):
                if part.get(key) is not None:
                    identities.add(str(part[key]))
            for key in ('field', 'field_id'):
                if part.get(key) is not None:
                    section_fields.add(str(part[key]))
        if identities & quote_ids or section_fields & fields:
            targets.add(index)
    if note_id == 'UZ:qualified-hadith-notice':
        return [-1]
    if not targets:
        raise ValueError('First-Hadith note has no exact supplied reader association: ' + str(note_id))
    return sorted(targets)


def _uz_export_context(root, row, payload, field):
    """The exact public source context required by the current export contract.

    The ordinary reader deliberately does not show the source parents. Detached
    books must still carry them. The four existing readable companions already
    contain every complete parent, its source/version/credit metadata and the
    publisher notes. Preserve those supplied documents, and prove each parent
    and note's exact original span instead of recreating or abridging them.
    """
    reader = payload['reader']
    final_qualification = json.loads(_inside(
        root, UZ_SOURCE_DIRECTORY + 'FINAL-SOURCE-QUALIFICATIONS934.json').read_bytes())
    if reader.get('sourceQualification') != final_qualification:
        raise ValueError('Uzbek source qualifications differ from the exact current final sidecar')
    parents = reader.get('sourceParents')
    if (not isinstance(parents, list) or len(parents) != 99
            or len({parent.get('id') for parent in parents}) != 99):
        raise ValueError('Uzbek export requires all 99 distinct complete source parents')
    public_paths = [UZ_SOURCE_DIRECTORY + name for name in UZ_PUBLIC_TEXT_FILES]
    declared = {(Path(row['json']).parent / item['path']).as_posix(): item
                for item in payload.get('sourceFiles', [])}
    if any(path not in declared for path in public_paths):
        raise ValueError('Uzbek public source companion is not an explicit current input')
    raw_texts = {name: _inside(root, UZ_SOURCE_DIRECTORY + name).read_bytes().decode('utf8')
                 for name in UZ_PUBLIC_TEXT_FILES}
    projection = json.loads(_inside(root, UZ_SOURCE_DIRECTORY + 'APP-SOURCE-PROJECTION930.json').read_bytes())
    if projection.get('textCompanions') != {name: raw_texts[name] for name in UZ_READABLE_COMPANIONS}:
        raise ValueError('Uzbek public readable companions differ from the current source projection')
    contract_path = UZ_SOURCE_DIRECTORY + 'TERRA-CONSUMER-CONTRACT934.json'
    contract = json.loads(_inside(root, contract_path).read_bytes())
    requirement = ('Preserve full99parents10publishernotes, four readable source companions, '
                   'exact source/reference/meaning qualifications in Source/Saved/export/offline.')
    if requirement not in contract.get('integrity', []):
        raise ValueError('Uzbek source export contract requires a new explicit review')

    parent_mappings, note_mappings = [], []
    for index, parent in enumerate(parents):
        carrier = parent.get('sourceCarrier', {})
        filename = carrier.get('file')
        if filename not in UZ_READABLE_COMPANIONS[:2]:
            raise ValueError('Uzbek parent points outside its exact public source companions')
        raw = raw_texts[filename]
        source = _binding(root, UZ_SOURCE_DIRECTORY + filename)
        if source['sha256'] != carrier.get('sha256'):
            raise ValueError('Uzbek parent companion hash differs')
        start, end = carrier['fullParentBounds']['codePoints']
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(raw) or raw[start:end] != parent['text']):
            raise ValueError('Uzbek complete parent no longer matches its original carrier bounds')
        marker = 'ID: ' + parent['id'] + '\n'
        if raw.count(marker) != 1:
            raise ValueError('Uzbek parent source record is missing or ambiguous')
        record_start = raw.index(marker)
        next_record = raw.find('\n---\n', end)
        record_end = next_record if next_record >= 0 else len(raw)
        if not record_start < start < end <= record_end:
            raise ValueError('Uzbek full parent is outside its own source record')
        metadata = json.dumps(parent['metadata'], ensure_ascii=False, indent=2)
        if (metadata not in raw[record_start:start]
                or parent['sourceURL'] not in raw[record_start:start]):
            raise ValueError('Uzbek parent source metadata or publisher credit was lost')
        parent_mappings.append({
            'parentId': parent['id'], 'readerPointer': ['reader', 'sourceParents', index],
            'source': source, 'pointer': ['$text'],
            'rawCodePointRange': [start, end],
            'normalizedCodePointRange': [len(normalize_lines(raw[:start])),
                                         len(normalize_lines(raw[:end]))],
            'rawTextSHA256': sha(parent['text'].encode('utf8')),
            'sourceMetadataSHA256': sha(canonical(parent['metadata'])),
            'sourceURL': parent['sourceURL'], 'publisherNoteCount': len(parent['notes'])})
        for note_index, note in enumerate(parent['notes']):
            note_text = note['text']
            note_start = raw.find(note_text, end, record_end)
            if note_start < 0 or note['label'] not in raw[end:note_start]:
                raise ValueError('Uzbek full publisher note or its source role was lost')
            note_end = note_start + len(note_text)
            note_mappings.append({
                'parentId': parent['id'],
                'readerPointer': ['reader', 'sourceParents', index, 'notes', note_index, 'text'],
                'source': source, 'pointer': ['$text'],
                'rawCodePointRange': [note_start, note_end],
                'normalizedCodePointRange': [len(normalize_lines(raw[:note_start])),
                                             len(normalize_lines(raw[:note_end]))],
                'rawTextSHA256': sha(note_text.encode('utf8')), 'label': note['label']})
    if len(note_mappings) != 10:
        raise ValueError('Uzbek export requires all ten complete publisher source notes')

    output = []
    for path in UZ_FINAL_QUALIFICATION_FIELDS:
        item = field(['reader', 'sourceQualification', *path], 'export-source-qualification', role='note')
        item['sourceOnlyPlacement'] = True
        output.append(item)

    # The public source requires links on these exact words. The source JSON
    # supplies the complete formula and destinations; the current source notes
    # provide the two exact labelled links. No wording or destination is invented.
    credit_parent = next((index for index, parent in enumerate(parents)
                          if 'creditRequired' in parent['metadata']), None)
    if credit_parent is None:
        raise ValueError('Uzbek source publisher credit formula is absent')
    credit_path = ['reader', 'sourceParents', credit_parent, 'metadata']
    metadata = parents[credit_parent]['metadata']
    credit_text = metadata['creditRequired']
    credit = field(credit_path + ['creditRequired'], 'export-source-credit', role='note')
    credit['sourceOnlyPlacement'] = True
    credit['requiredLiteralProof'] = True
    links = re.findall(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)', raw_texts['SOURCE-NOTES-UZ930.md'])
    credit['hyperlinks'] = []
    for name in ('homeURL', 'articleURL'):
        url = metadata[name]
        labels = [label for label, target in links if target == url]
        if len(labels) != 1 or credit_text.count(labels[0]) != 1:
            raise ValueError('Uzbek source publisher credit links changed')
        start = credit_text.index(labels[0])
        credit['hyperlinks'].append({
            'start': start, 'end': start + len(labels[0]), 'url': url,
            'urlField': field(credit_path + [name], 'export-credit-url', role='note')})
    if credit['hyperlinks'] != sorted(credit['hyperlinks'], key=lambda item: item['start']):
        raise ValueError('Uzbek source publisher credit link order changed')
    output.append(credit)

    companion_mappings = []
    for filename in UZ_PUBLIC_TEXT_FILES:
        path = UZ_SOURCE_DIRECTORY + filename
        value = normalize_lines(raw_texts[filename])
        start = 0
        ranges = []
        for separator in re.finditer(r'\n[ \t]*\n+', value):
            end = separator.end()
            if value[start:end].strip():
                ranges.append([start, end])
            elif ranges:
                ranges[-1][1] = end
            start = end
        if start < len(value):
            if value[start:].strip():
                ranges.append([start, len(value)])
            elif ranges:
                ranges[-1][1] = len(value)
        if not ranges or ''.join(value[a:b] for a, b in ranges) != value:
            raise ValueError('Uzbek source companion paragraph partition lost text')
        for index, (start, end) in enumerate(ranges):
            output.append({
                'sourcePath': path, 'pointer': ['$text'], 'literalRange': [start, end],
                'purpose': 'export-source-companion', 'section': None, 'role': 'note',
                'kind': 'heading' if index == 0 else 'paragraph',
                'sourceOnlyPlacement': True,
                'textSHA256': sha(value[start:end].encode('utf8'))})
        companion_mappings.append({'source': _binding(root, path), 'pointer': ['$text'],
            'normalizedCharacters': len(value), 'normalizedTextSHA256': sha(value.encode('utf8')),
            'paragraphCount': len(ranges), 'complete': True,
            'role': 'readable-source-companion' if filename in UZ_READABLE_COMPANIONS else 'source-reference-qualifications'})

    return output, {
        'contract': _binding(root, contract_path),
        'publicTextFiles': public_paths, 'readableCompanionCount': 4,
        'sourceParentCount': 99, 'publisherNoteCount': 10,
        'sourceParents': parent_mappings, 'publisherNotes': note_mappings,
        'companions': companion_mappings,
        'qualificationPointers': [['reader', 'sourceQualification', *path]
                                  for path in UZ_FINAL_QUALIFICATION_FIELDS],
        'coordinateConvention': 'Original raw Unicode code points retained in mappings; output normalizes line endings only.',
        'privateMaterialIncluded': False}


def reader_plan(root, row, payload):
    """An ordered, inspectable list of exact display-string pointers."""
    language = row['language']
    reader_key, section_key, note_key, _ = SPEC[language]
    reader = payload.get(reader_key)
    if not isinstance(reader, dict):
        raise ValueError('Unsupported first-Hadith reader wrapper')
    sections = _section_fields(reader, section_key)
    base = [reader_key]
    source_path = row['json']
    before, main, end, source_only = [], [], [], []
    notes_after = {-1: []}
    notes_after.update({index: [] for index in range(49)})

    def field(path, purpose, section=None, role='body', source=None):
        source = source or source_path
        document = payload if source == source_path else json.loads(_inside(root, source).read_bytes())
        value = pointer(document, path)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing exact first-Hadith display field: ' + str(path))
        return {'sourcePath': source, 'pointer': path, 'purpose': purpose,
                'section': section, 'role': role,
                'textSHA256': sha(normalize_lines(value).encode('utf8'))}

    title = field(base + ['title'], 'title')
    if reader.get('meaningNotice'):
        before.append(field(base + ['meaningNotice'], 'reader-notice', role='note'))
    if language == 'id':
        main.append(field(base + ['mainHadith', 'text'], 'main', -1, 'hadith'))
        main.append(field(base + ['mainHadith', 'referenceText'], 'reference', -1, 'note'))
    elif language == 'ms':
        main.append(field(base + ['mainIntroduction'], 'main-frame', -1))
        main.append(field(base + ['mainNarration'], 'main', -1, 'hadith'))
        main.append(field(base + ['reference'], 'reference', -1, 'note'))
    elif language == 'pt-BR':
        main.append(field(base + ['mainNarration', 'text'], 'main', -1, 'hadith'))
        main.append(field(base + ['reference', 'reader_label'], 'reference', -1, 'note'))
    elif language in {'bn', 'hi'}:
        main.append(field(base + ['main_frame'], 'main-frame', -1))
        main.append(field(base + ['main_text'], 'main', -1, 'hadith'))
        main.append(field(base + ['reference'], 'reference', -1, 'note'))
    elif language in {'es', 'fa', 'ru'}:
        main.append(field(base + ['mainNarration', 'frame'], 'main-frame', -1))
        main.append(field(base + ['mainNarration', 'text'], 'main', -1, 'hadith'))
        ref = ['reference', 'reading'] if language in {'es', 'fa'} else ['reference']
        main.append(field(base + ref, 'reference', -1, 'note'))
    else:
        main.append(field(base + ['main'], 'main', -1, 'hadith'))
        if language == 'de':
            candidate = (Path(source_path).parent / 'sources/LESSON001-DE-CANDIDATE914.json').as_posix()
            main.append(field(['mainNarration', 'reference'], 'reference', -1, 'note', candidate))
            # This attribution is present in the current public Markdown reader,
            # but was not duplicated in its older JSON projection.
            text = _inside(root, row['markdown']).read_text(encoding='utf8')
            literal = 'Muslim · Rowwad'
            if text.count(literal) != 1:
                raise ValueError('German first-Hadith source attribution changed')
            start = text.index(literal)
            main.append({'sourcePath': row['markdown'], 'textRange': [start, start + len(literal)],
                         'purpose': 'credit', 'section': -1, 'role': 'note',
                         'textSHA256': sha(literal.encode('utf8'))})
        else:
            main.append(field(base + ['reference'], 'reference', -1, 'note'))
            if reader.get('quranCredit'):
                main.append(field(base + ['quranCredit'], 'credit', -1, 'note'))

    all_notes = []
    if note_key:
        notes = reader.get(note_key, [])
        if not isinstance(notes, list):
            raise ValueError('Unsupported first-Hadith note list')
        all_notes.extend((base + [note_key, index, 'text'], note,
                          -1 if note_key == 'main_notes' else None)
                         for index, note in enumerate(notes))
    for index, section in enumerate(sections):
        all_notes.extend((base + [section_key, index, 'notes', n, 'text'], note, index)
                         for n, note in enumerate(section.get('notes', [])))
    for path, note, fixed in all_notes:
        if not isinstance(note, dict) or not isinstance(note.get('text'), str):
            raise ValueError('Malformed first-Hadith reader note')
        item = field(path, 'reader-note', role='note')
        item['noteId'] = note.get('id')
        item['sourceNoteMetadata'] = {k: deepcopy(v) for k, v in note.items() if k != 'text'}
        if note.get('placement') == 'source-only parent context':
            item['purpose'] = 'export-source-note'
            item['sourceOnlyPlacement'] = True
            source_only.append(item)
            continue
        if language == 'id' and note.get('id') in {'CONTEXT-QUALIFICATIONS', 'MEANING-EXCERPT-NOTICE'}:
            # These two whole-lesson notes are explicitly placed after the
            # final commentary in the current public reader, not at a quote.
            compact = lambda value: re.sub(r'\s+', '', value)
            markdown = compact(_inside(root, row['markdown']).read_text(encoding='utf8'))
            last = compact(sections[-1]['text'])
            supplied_note = compact(note['text'])
            if last not in markdown or supplied_note not in markdown[markdown.index(last) + len(last):]:
                raise ValueError('Current whole-lesson note placement changed')
            targets = [48]
            item['placementEvidence'] = 'After final commentary in the exact current Markdown reader'
        else:
            targets = _note_targets(note, sections, reader, fixed=fixed)
        item['anchorSections'] = targets
        # Explicit multiple section bindings are retained; a shared source note
        # without an explicit repeated placement is shown at its first anchor.
        repeat = bool(note.get('sections'))
        for target in targets if repeat else targets[:1]:
            placed = deepcopy(item)
            placed['section'] = target
            notes_after[target].append(placed)

    commentary = [field(base + [section_key, index, 'text'], 'commentary', index)
                  for index in range(49)]
    for name in ('readerCredits', 'readingCredits', 'short_credits', 'credits'):
        values = reader.get(name)
        if values is None:
            continue
        if isinstance(values, str):
            end.append(field(base + [name], 'credit', role='note'))
        elif isinstance(values, list):
            end.extend(field(base + [name, index], 'credit', role='note') for index in range(len(values)))
        else:
            raise ValueError('Unsupported original first-Hadith reader credits')
    export_context = None
    if language == 'uz':
        source_only.insert(0, field(base + ['originalQuranNotice'], 'export-source-notice', role='note'))
        public_fields, export_context = _uz_export_context(root, row, payload, field)
        source_only.extend(public_fields)
    ordered = before + main + notes_after[-1]
    for index, item in enumerate(commentary):
        ordered += [item] + notes_after[index]
    ordered += end
    return {'title': title, 'ordinary': ordered, 'sourceOnlyExport': source_only,
            'noteCount': len(all_notes),
            'ordinaryNoteCount': sum(note.get('placement') != 'source-only parent context'
                                     for _, note, _ in all_notes),
            'sourceOnlyExportContext': export_context}


def snapshot(root, catalog, source_commit):
    """Create an exact migration snapshot for review; publishers never call it."""
    from book_edition_scope import available
    root = Path(root).resolve()
    records_out, excluded = [], []
    correspondence = _arabic_correspondence(root)
    seen = set()
    for row in catalog.get('entries', []):
        if (row.get('collection') != 'essential-hadith' or row.get('id') != UNIT_ID
                or row.get('language') == 'ar' or not available(row)):
            continue
        language = row['language']
        if language in seen:
            raise ValueError('Duplicate current first-Hadith catalogue identity')
        seen.add(language)
        payload = json.loads(_inside(root, row['json']).read_bytes())
        if language == 'fr':
            excluded.append({'language': 'fr', 'id': UNIT_ID,
                'reason': 'Current inner reader records a pending distinct final review; existing outer status and historical reviews must be reconciled for these exact bytes.',
                'sourceFiles': [_binding(root, row[name]) for name in ('json', 'markdown')],
                'reviewStatus': payload.get('reading', {}).get('reviewStatus'),
                'sourceApprovalCreated': False})
            continue
        if language not in SPEC:
            raise ValueError('Unsupported current first-Hadith reader schema: ' + language)
        if row.get('chapter') != 1 or row.get('lesson') != 1:
            raise ValueError('First-Hadith catalogue has the wrong source position')
        if row.get('translationStatus') != 'ai-translated-independent-model-reviewed-human-verification-needed':
            raise ValueError('First-Hadith current catalogue review status changed')
        if _binding(root, ARABIC_REVIEWED)['sha256'] not in row.get('sourceHashes', []):
            raise ValueError('First-Hadith translation has no matching reviewed Arabic source')
        files = _source_files(root, row, payload)
        plan = reader_plan(root, row, payload)
        records_out.append({
            'collection': 'essential-hadith', 'language': language, 'id': UNIT_ID,
            'chapter': 1, 'lesson': 1, 'readerPointer': [SPEC[language][0]],
            'catalogEntry': {k: deepcopy(v) for k, v in row.items() if k != 'bookReaderUnit'},
            'sourceFiles': files,
            'sourceConditions': _source_conditions(root, files),
            'arabicCorrespondence': correspondence,
            'existingPublication': {'sourceCommit': source_commit,
                                    **_review_fields(root, catalog, language, payload)},
            'displayPlan': plan,
            'qualification': 'Exact existing independently model-reviewed current first lesson; human verification remains needed. This adapter creates no new source, translation, Word or visual approval.'})
    return {'schema': SCHEMA, 'sourceCommit': source_commit,
            'records': sorted(records_out, key=lambda item: item['language']),
            'excludedCurrentRows': excluded, 'sourceApprovalCreated': False,
            'humanCertification': False,
            'scope': 'Only exact current first-lesson readers and original notes. Superseded sources, unrelated legacy Hadith, absent translations and unreconciled review claims are not imported.'}


def records(root, declaration):
    from book_edition_scope import pinned
    result = []
    for binding in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(Path(root), binding))
        if data.get('schema') != SCHEMA:
            continue
        for item in data.get('records', []):
            if item.get('language') == declaration.get('language'):
                result.append((item, binding))
    if len({item['id'] for item, _ in result}) != len(result):
        raise ValueError('Duplicate current first-Hadith source-review identity')
    return result


def validate_record(root, record, row, catalog):
    from book_edition_scope import available, pinned
    root = Path(root).resolve()
    language = record.get('language')
    if (language not in SUPPORTED or record.get('collection') != 'essential-hadith'
            or record.get('id') != UNIT_ID or record.get('chapter') != 1 or record.get('lesson') != 1
            or record.get('readerPointer') != [SPEC[language][0]]):
        raise ValueError('Unsupported current first-Hadith review identity')
    if not available(row) or {k: v for k, v in row.items() if k != 'bookReaderUnit'} != record.get('catalogEntry'):
        raise ValueError('First-Hadith source is no longer the exact current reviewed catalogue row')
    bindings = record.get('sourceFiles', []) + record.get('sourceConditions', [])
    if len({item['path'] for item in bindings}) != len(bindings):
        raise ValueError('Duplicate first-Hadith input binding')
    for binding in bindings:
        pinned(root, binding)
    payload = json.loads(_inside(root, row['json']).read_bytes())
    if (payload.get('id') != UNIT_ID
            or (payload.get('language') or payload.get('reader', {}).get('locale')) != language):
        raise ValueError('First-Hadith reader language or identity differs')
    if record.get('sourceFiles') != _source_files(root, row, payload):
        raise ValueError('Current first-Hadith source companions changed')
    if record.get('sourceConditions') != _source_conditions(root, record['sourceFiles']):
        raise ValueError('Missing current/reviewed Arabic first-Hadith source inputs')
    if record.get('arabicCorrespondence') != _arabic_correspondence(root):
        raise ValueError('Arabic first-Hadith source correspondence changed')
    publication = record.get('existingPublication', {})
    if not re.fullmatch(r'[a-f0-9]{40}', str(publication.get('sourceCommit', ''))):
        raise ValueError('Missing exact existing first-Hadith source commit')
    if {k: v for k, v in publication.items() if k != 'sourceCommit'} != _review_fields(root, catalog, language, payload):
        raise ValueError('Current first-Hadith source review qualification changed')
    if record.get('displayPlan') != reader_plan(root, row, payload):
        raise ValueError('First-Hadith display fields, order or note associations changed')
    return bindings


def literal_sources(record):
    by_path = {item['path']: item for item in record.get('sourceFiles', [])}
    plan = record.get('displayPlan', {})
    found = []
    fields = [plan.get('title', {}), *plan.get('ordinary', []), *plan.get('sourceOnlyExport', [])]
    fields.extend(link['urlField'] for field in list(fields) for link in field.get('hyperlinks', []))
    for field in fields:
        if 'pointer' not in field or field.get('sourcePath') not in by_path:
            continue
        item = {'source': deepcopy(by_path[field['sourcePath']]), 'pointer': list(field['pointer'])}
        if item not in found:
            found.append(item)
    return found


def literal_links(record):
    """Bind each public credit's exact label positions to its exact destinations."""
    by_path = {item['path']: item for item in record.get('sourceFiles', [])}
    associations = []
    for field in record.get('displayPlan', {}).get('sourceOnlyExport', []):
        if not field.get('hyperlinks'):
            continue
        links = []
        for link in field['hyperlinks']:
            target = link['urlField']
            links.append({
                **{name: deepcopy(link[name]) for name in ('start', 'end', 'url')},
                'source': deepcopy(by_path[target['sourcePath']]),
                'pointer': list(target['pointer']), 'textSHA256': target['textSHA256']})
        associations.append({
            'paragraph': {'source': deepcopy(by_path[field['sourcePath']]),
                          'pointer': list(field['pointer']), 'textSHA256': field['textSHA256']},
            'links': links})
    return associations


def literal_value(root, record, proof):
    """Resolve only exact display fields or the explicitly public text files."""
    source = proof.get('source')
    if source not in record.get('sourceFiles', []):
        raise ValueError('First-Hadith literal is outside its exact source inputs')
    from book_edition_scope import pinned
    raw = pinned(Path(root), source)
    if proof.get('pointer') == ['$text']:
        if (record.get('language') != 'uz'
                or source['path'] not in {UZ_SOURCE_DIRECTORY + name for name in UZ_PUBLIC_TEXT_FILES}):
            raise ValueError('First-Hadith text source is outside the explicit public export allowlist')
        return raw.decode('utf8')
    return pointer(json.loads(raw), proof['pointer'])


def _text(root, field):
    raw = _inside(root, field['sourcePath']).read_bytes()
    if field.get('pointer') == ['$text']:
        if field['sourcePath'] not in {UZ_SOURCE_DIRECTORY + name for name in UZ_PUBLIC_TEXT_FILES}:
            raise ValueError('First-Hadith text source is outside the public export allowlist')
        text = raw.decode('utf8')
    elif 'pointer' in field:
        text = pointer(json.loads(raw), field['pointer'])
    else:
        text = raw.decode('utf8')[slice(*field['textRange'])]
    if not isinstance(text, str):
        raise ValueError('First-Hadith display pointer is not text')
    text = normalize_lines(text)
    if 'literalRange' in field:
        start, end = field['literalRange']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError('Invalid first-Hadith source export range')
        text = text[start:end]
    if sha(text.encode('utf8')) != field['textSHA256']:
        raise ValueError('First-Hadith literal display text changed')
    return text


def _spans(payload, field, text):
    """Retain explicit semantic spans only when they reproduce the whole field."""
    path = field.get('pointer', [])
    if field['purpose'] == 'commentary':
        owner = pointer(payload, path[:-1])
        parts = owner.get('parts', owner.get('segments'))
    elif field['purpose'] == 'main':
        owner = pointer(payload, path[:-1])
        parts = owner.get('parts', owner.get('segments', owner.get('mainParts')))
        if parts and owner.get('mainParts') is parts:
            # Uzbek's mainParts includes a separate, ID-bound reader notice.
            # The main string excludes it; reader_plan presents the exact same
            # note once, at the main narration's note anchor.
            filtered = []
            for part in parts:
                if part.get('kind') == 'note':
                    matches = [note for note in owner.get('notes', [])
                               if note.get('id') == part.get('noteId') and note.get('text') == part.get('text')]
                    if len(matches) != 1:
                        raise ValueError('First-Hadith semantic note lacks its exact reader note')
                else:
                    filtered.append(part)
            parts = filtered
    else:
        return None
    if not parts:
        return None
    spans = []
    for part in parts:
        value = part.get('displayText', part.get('text'))
        if not isinstance(value, str):
            raise ValueError('Non-text first-Hadith semantic span')
        kind = str(part.get('kind', part.get('type', ''))).lower()
        if 'quran' in kind:
            role = 'quran'
        elif 'scholar' in kind:
            role = 'scholar'
        elif 'hadith' in kind or kind in {'published_nonq', 'own_nonq_meaning', 'own_direct_arabic_nonq_meaning'}:
            role = 'hadith'
        else:
            role = 'body'
        spans.append({'text': normalize_lines(value), 'role': role})
    if ''.join(span['text'] for span in spans) != text:
        raise ValueError('First-Hadith semantic spans change the exact reader paragraph')
    return spans


def normalize(root, catalog, row, record, evidence):
    from build_books import check_unit
    from source_literal_text import SCHEMA as LITERAL_SCHEMA
    bindings = validate_record(root, record, row, catalog)
    by_path = {item['path']: item for item in bindings}
    payload = json.loads(_inside(root, row['json']).read_bytes())
    language = record['language']
    plan = record['displayPlan']
    title = _text(root, plan['title'])
    native_text(title, language)
    blocks, export_blocks, ledger = [], [], []

    def exact_proof(field, text):
        if 'pointer' not in field:
            raise ValueError('Non-native first-Hadith text lacks an exact source-field proof')
        start, end = field.get('literalRange', (0, len(text)))
        return {
            'schema': LITERAL_SCHEMA, 'language': language, 'materialId': UNIT_ID,
            'source': deepcopy(by_path[field['sourcePath']]), 'inventory': deepcopy(evidence),
            'pointer': list(field['pointer']), 'start': start, 'end': end,
            'textSHA256': sha(text.encode('utf8'))}

    for fields, output in ((plan['ordinary'], blocks), (plan['sourceOnlyExport'], export_blocks)):
        for field in fields:
            text = _text(root, field)
            block = {'kind': field.get('kind', 'paragraph'), 'text': text, 'role': field['role']}
            if output is export_blocks:
                block['sourceOnlyContext'] = True
            spans = _spans(payload, field, text) if field['sourcePath'] == row['json'] else None
            if spans:
                block['spans'] = spans
            try:
                native_text(text, language)
            except ValueError:
                block['sourceLiteralProof'] = exact_proof(field, text)
            if field.get('requiredLiteralProof'):
                block['sourceLiteralProof'] = exact_proof(field, text)
            if field.get('hyperlinks'):
                block['hyperlinks'] = [
                    {name: deepcopy(link[name]) for name in ('start', 'end', 'url')}
                    | {'sourceLiteralProof': exact_proof(link['urlField'], _text(root, link['urlField']))}
                    for link in field['hyperlinks']]
            output.append(block)
            ledger.append({**deepcopy(field), 'blockIndex': len(output) - 1,
                           'outputSection': 'source-notes' if output is export_blocks else 'lesson'})
    sections = [{'blocks': blocks}]
    if export_blocks:
        sections.append({'heading': locale(language)['creditsTitle'], 'blocks': export_blocks,
                         'sourceOnlyContext': True})
    all_text = ''.join(block['text'] for section in sections for block in section['blocks'])
    references = sum(field['purpose'] in {'reference', 'credit'} for field in plan['ordinary'])
    paragraphs = sum(field['purpose'] in {'main-frame', 'main', 'commentary'} for field in plan['ordinary'])
    inputs = {item['path']: item['sha256'] for item in bindings + [evidence]}
    unit = {
        'schema': 'iman-book-unit-v1', 'id': UNIT_ID, 'language': language,
        'collection': 'hadith', 'hadithEdition': 'new-extended',
        'chapter': 1, 'lesson': 1, 'sourceLessonNumber': 1, 'order': 1001,
        'ordering': {'kind': 'chapter-lesson', 'chapter': 1, 'lesson': 1},
        'title': title, 'complete': True, 'reviewGate': 'published-current',
        'sourceHashes': list(row['sourceHashes']),
        'inputBindings': [{'path': path, 'sha256': digest} for path, digest in sorted(inputs.items())],
        'catalogBindings': [{'collection': 'essential-hadith', 'language': language, 'id': UNIT_ID}],
        'sections': sections, 'readerTextSHA256': sha(all_text.encode('utf8')),
        'sourceReferencePreservation': {
            'schema': 'iman-source-reference-preservation-v1',
            'auditMode': 'literal-source-and-qualification-fidelity',
            'sourceReferences': references, 'preservedReferences': references,
            'sourceQualifications': plan['noteCount'], 'preservedQualifications': plan['noteCount'],
            'sourceParagraphs': paragraphs, 'preservedParagraphs': paragraphs,
            'lostReferences': 0, 'lostQualifications': 0, 'lostParagraphs': 0},
        'provenance': {
            'adapter': ADAPTER, 'sourceRecordSHA256': sha(canonical(record)),
            'sourceDisplayFields': ledger, 'sourceStatus': record['existingPublication']['sourceStatus'],
            'sourceCompanionBindings': [item for item in bindings if item['path'] not in {row['json'], row['markdown']}],
            'sourceOnlyNoteCount': plan['noteCount'] - plan['ordinaryNoteCount'],
            'sourceOnlyExportDisposition': 'Exact required publisher source-context notes remain separate from the authored lesson, under localized source furniture.',
            'sourceOnlyExportContext': deepcopy(plan['sourceOnlyExportContext']),
            'arabicCorrespondence': deepcopy(record['arabicCorrespondence']),
            'reviewQualification': record['qualification'], 'sourceApprovalCreated': False,
            'humanCertification': False}}
    if plan['sourceOnlyExportContext'] is not None:
        context = plan['sourceOnlyExportContext']
        unit['sourceContextPreservation'] = {
            'sourceParents': context['sourceParentCount'], 'preservedParents': context['sourceParentCount'],
            'publisherNotes': context['publisherNoteCount'], 'preservedPublisherNotes': context['publisherNoteCount'],
            'readableCompanions': context['readableCompanionCount'],
            'preservedReadableCompanions': context['readableCompanionCount'],
            'sourceQualificationFields': len(context['qualificationPointers']),
            'preservedSourceQualificationFields': len(context['qualificationPointers']),
            'publisherCreditHyperlinks': 2, 'preservedPublisherCreditHyperlinks': 2,
            'lostParents': 0, 'lostPublisherNotes': 0, 'lostCompanions': 0,
            'privateMaterialIncluded': False}
    check_unit(unit, {'language': language, 'collection': 'hadith', 'id': UNIT_ID}, root=Path(root))
    return unit


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    """Additional current first lessons for a declaration already bound to us."""
    if declaration.get('collection') != 'hadith' or declaration.get('language') == 'ar':
        raise ValueError('First-Hadith adapter belongs to a translated Hadith edition')
    excluded = set(excluded_catalog_keys)
    result = []
    for record, evidence in records(root, declaration):
        identity = ('essential-hadith', record['language'], record['id'])
        if identity in excluded:
            continue
        rows = [row for row in catalog.get('entries', [])
                if (row.get('collection'), row.get('language'), str(row.get('id'))) == identity]
        if len(rows) != 1:
            raise ValueError('Current first-Hadith source disappeared or became ambiguous')
        result.append(normalize(root, catalog, rows[0], record, evidence))
    return result
