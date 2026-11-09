"""Import current, already-reviewed Quran readers whose older schemas were missed.

This is a migration of the installed app's exact source publications, not a new
translation approval.  Each record pins the reader, its existing review evidence,
the current Arabic revision, and every accompanying source/qualification file.
The adapter never discovers eligibility from an arbitrary file or an old archive.

The three supported layouts are the reviewed entries map, the published Fatiha
packet, and the Japanese Qiyamah per-verse index.  Words and quotation order are
unchanged.  Original source references and notes become literal, source-bound
footnotes; no website identifier is guessed to be a Hadith collection number.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re

from bibliography import native_text, digits, expand_verse_key
from book_edition_scope import available, canonical, key, pinned
from book_scope_copy import AVAILABLE_AYAHS
from locale_copy import locale
from quran_scope import canonical_surah
from source_literal_text import SCHEMA as LITERAL_SCHEMA, normalize_lines


SCHEMA = 'iman-current-reviewed-quran-source-bindings-v1'
ADAPTER = 'current-reviewed-quran-v1'
PROJECTION = 'books/source-projections/current-reviewed-quran.json'
ENTRY_LANGUAGES = {'en', 'ur', 'id', 'ms', 'bn', 'tr', 'fr', 'pt-BR'}
ENTRY_SURAHS = {1, 15, 17, 40, 55, 61, 62, 63, 68, 93, 98, 99, 101, 103}
FATIHA_LANGUAGES = {'de', 'ja', 'fil', 'hi', 'zh-CN', 'fa', 'th', 'ru', 'vi', 'es', 'uz'}
FATIHA_INDEX = 'materials/tadabbur/fatiha-extended/README.md'
QIYAMAH_PREFIX = 'materials/tadabbur/ja/extended/075-sources'
QIYAMAH_FRONT = QIYAMAH_PREFIX + '/FRONTMATTER-AND-BIBLIOGRAPHY658.json'
ROLES = {'plain': 'body', 'meaning': 'meaning', 'body': 'body', 'core': 'body',
         'example': 'example', 'note': 'note', 'related': 'related',
         'related-ayah': 'quran', 'current-ayah': 'current-ayah',
         'current': 'current-ayah', 'quran': 'quran', 'hadith': 'hadith',
         'scholar': 'scholar', 'heading': 'heading'}
NOTE_FIELDS = {'readerNotes', 'publisherNotes', 'contextNotes', 'notes',
               'readingNotes', 'referenceNotes', 'requiredMeaningNotes',
               'requiredPublisherNotes', 'quranNoteQualification',
               'quranQualification', 'greatnessFirstQualification'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(root, path):
    return json.loads((Path(root) / path).read_bytes())


def binding(root, path):
    root = Path(root).resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or file == root:
        raise ValueError('Current Quran source escapes repository')
    if '/source-archive/' in file.as_posix():
        raise ValueError('Archived Quran source cannot enter the current book')
    return {'path': file.relative_to(root).as_posix(), 'sha256': sha(file.read_bytes())}


def _atom(path, pointer, text, role='body'):
    if not isinstance(text, str):
        raise ValueError('Reviewed reader field is not literal text')
    return {'path': path, 'pointer': list(pointer), 'text': normalize_lines(text), 'role': role}


def _string_notes(path, value, pointer):
    """Known reader-note payloads only, never arbitrary audit metadata."""
    if isinstance(value, str):
        if value.strip():
            yield _atom(path, pointer, value, 'note')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _string_notes(path, item, [*pointer, index])
    elif isinstance(value, dict):
        # Keep the source's note title and complete text together as two exact
        # fields. IDs and audit hashes are provenance, not reader prose.
        fields = [name for name in ('title', 'heading', 'text', 'note', 'meaning')
                  if isinstance(value.get(name), str) and value[name].strip()]
        if fields:
            for name in fields:
                yield _atom(path, [*pointer, name], value[name], 'note')
        else:
            # Some publisher footnotes are dictionaries keyed by note number.
            for name, item in value.items():
                if isinstance(item, (str, list, dict)):
                    yield from _string_notes(path, item, [*pointer, name])
    elif value is not None:
        raise ValueError('Unsupported existing reader-note value')


def _notes(path, value, pointer):
    result = []
    for name, item in value.items():
        if name in NOTE_FIELDS:
            result.extend(_string_notes(path, item, [*pointer, name]))
    return result


def _citation(path, citation, pointer, source_text):
    """Original labels/locators, including their original qualifications."""
    if not isinstance(citation, dict):
        raise ValueError('Unsupported original Quran citation object')
    fields = ['publisher', 'reference', 'canonicalReference', 'sourceReference',
              'label', 'translator', 'work', 'edition', 'sourceReport',
              'excerptNotice', 'quotationType']
    kind = citation.get('kind')
    if isinstance(kind, str) and kind not in {'quran', 'hadith', 'scholar', 'source', 'reference'}:
        fields.append('kind')
    if isinstance(citation.get('quote'), str) and citation['quote'] not in source_text:
        fields.append('quote')
    fields.append('url')
    result = []
    seen = set()
    for name in fields:
        text = citation.get(name)
        if isinstance(text, str) and text.strip() and text not in seen:
            result.append(_atom(path, [*pointer, name], text, 'note'))
            seen.add(text)
    result.extend(_notes(path, citation, pointer))
    if not result:
        raise ValueError('Original citation has no preserved literal reference')
    return result


def _source_block(path, pointer, block):
    if not isinstance(block, dict) or not isinstance(block.get('text'), str) or not block['text'].strip():
        raise ValueError('Empty or unsupported reviewed Quran source paragraph')
    if block.get('kind') not in {'paragraph', 'translation', 'ayah', 'heading', 'note', 'quotation', 'list-item'}:
        raise ValueError('Unsupported current Quran block kind: ' + str(block.get('kind')))
    role = block.get('role', 'current-ayah' if block['kind'] in {'ayah', 'translation'} else 'body')
    if role not in ROLES:
        raise ValueError('Unsupported current Quran semantic role')
    spans = deepcopy(block.get('spans', []))
    if spans:
        if ''.join(normalize_lines(span['text']) for span in spans) != normalize_lines(block['text']):
            raise ValueError('Original Quran paragraph spans change its literal text')
        for span in spans:
            if span.get('role', role) not in ROLES:
                raise ValueError('Unsupported current Quran span role')
    return {**_atom(path, [*pointer, 'text'], block['text'], ROLES[role]),
            'kind': block['kind'], 'spans': spans,
            'notes': _notes(path, block, pointer)}


def _current_arabic(root, catalog, row):
    surah = canonical_surah(row)
    matches = [item for item in catalog['entries']
               if item.get('collection') == 'tadabbur' and item.get('language') == 'ar'
               and available(item) and canonical_surah(item) == surah]
    if len(matches) != 1:
        raise ValueError('Current Arabic Quran revision is missing or ambiguous')
    arabic = matches[0]
    if row.get('sourceHashes') and row['sourceHashes'] != arabic.get('sourceHashes'):
        raise ValueError('Translated Quran source was superseded by the current Arabic revision')
    files = [binding(root, arabic[name]) for name in ('json', 'markdown') if arabic.get(name)]
    if not files or not arabic.get('sourceHashes'):
        raise ValueError('Current Arabic source lacks its exact revision identity')
    return deepcopy(arabic), files


def _entry_map(root, row, payload):
    path = row['json']; language = row['language']; surah = canonical_surah(row)
    if (payload.get('language'), payload.get('surah'), payload.get('mode')) != (language, surah, 'extended'):
        raise ValueError('Reviewed Quran entries map identity changed')
    if not isinstance(payload.get('entries'), dict) or not payload['entries']:
        raise ValueError('Reviewed Quran entries map is empty')
    sections = []; review = []
    for section_key, entry in payload['entries'].items():
        pointer = ['entries', section_key]
        if (entry.get('internalReviewStatus') != 'reviewed' or not entry.get('reviewedAt')
                or entry.get('sourceSha256') not in row.get('sourceHashes', [])
                or entry.get('sourceLanguage') != 'ar'
                or entry.get('semanticAnnotation', {}).get('independentReviewPending') is True):
            raise ValueError('Quran entry is unfinished, unreviewed, or from another Arabic revision')
        blocks = [_source_block(path, [*pointer, 'blocks', index], block)
                  for index, block in enumerate(entry.get('blocks', []))]
        if not blocks:
            raise ValueError('Reviewed Quran entry has no complete body')
        refs = [_citation(path, citation, [*pointer, 'citations', number], ''.join(b['text'] for b in blocks))
                for number, citation in enumerate(entry.get('citations', []))]
        credit = []
        source = entry.get('quranTranslationSource')
        notes = _notes(path, entry, pointer)
        if source:
            if not isinstance(source, dict) or not source.get('edition') or not source.get('publisher'):
                raise ValueError('Current Quran translation attribution is incomplete')
            credit = [_atom(path, [*pointer, 'quranTranslationSource', name], source[name], 'note')
                      for name in ('publisher', 'edition')]
            if source.get('footnotes'):
                notes += list(_string_notes(path, source['footnotes'], [*pointer, 'quranTranslationSource', 'footnotes']))
        heading = _atom(path, [*pointer, 'heading'], entry['heading'], 'heading')
        sections.append({'key': section_key, 'heading': heading, 'blocks': blocks,
                         'references': refs, 'notes': notes, 'credit': credit})
        review.append({'section': section_key, 'status': entry['internalReviewStatus'],
                       'reviewedAt': entry['reviewedAt'], 'sourceSHA256': entry['sourceSha256'],
                       'scope': entry.get('reviewScope') or entry.get('semanticAnnotation', {}).get('reviewScope')})
    return {'sections': sections, 'notes': [], 'frontmatter': [], 'endmatter': [],
            'reviewEvidence': review, 'additionalFiles': [], 'conditions': [],
            'sourceKind': 'reviewed-entries-map', 'title': None}


def _fatiha(root, catalog, row, payload):
    language = row['language']; path = row['json']
    group = catalog.get('fatihaExtended1004', {})
    if language not in FATIHA_LANGUAGES or language not in group.get('languages', []) or group.get('index') != FATIHA_INDEX:
        raise ValueError('Fatiha reader is outside its existing reviewed publication group')
    index_text = (Path(root) / FATIHA_INDEX).read_text(encoding='utf8')
    if 'complete reviewed introduction and reflections on verses 1–7' not in index_text or 'independently model-reviewed' not in index_text:
        raise ValueError('Existing Fatiha whole-reading review qualification changed')
    if payload.get('language') != language or not payload.get('title') or not payload.get('shortCredit'):
        raise ValueError('Reviewed Fatiha packet identity or source credit is missing')
    units = payload.get('units')
    if not isinstance(units, list) or [unit.get('id') for unit in units] != ['intro:1', *[f'1:{n}' for n in range(1, 8)]]:
        raise ValueError('Current Fatiha packet omits or reorders an introduction/verse')
    source_path = (Path(path).parent / 'sources.json').as_posix()
    sources = read(root, source_path)
    if sources.get('language') != language or not isinstance(sources.get('sourceCredit'), str):
        raise ValueError('Fatiha original translation/source attribution is missing')
    credit = [_atom(source_path, ['sourceCredit'], sources['sourceCredit'], 'note')]
    sections = []
    for number, entry in enumerate(units):
        pointer = ['units', number]
        blocks = [_source_block(path, [*pointer, 'blocks', index], block)
                  for index, block in enumerate(entry.get('blocks', []))]
        if not blocks:
            raise ValueError('Reviewed Fatiha packet has an empty section')
        sections.append({'key': entry['id'], 'heading': _atom(path, [*pointer, 'heading'], entry['heading'], 'heading'),
                         'blocks': blocks, 'references': [], 'notes': _notes(path, entry, pointer), 'credit': credit})
    # reading.json is the reviewed ordinary-reading boundary. The companion
    # sources.json also contains unselected parents, audit commentary and source
    # transcripts: retain its exact binding, but do not promote those fields
    # into the reading. Only the original source credit supplies attribution.
    notes = _notes(path, payload, [])
    # Glossary labels are supplied content, not new explanatory prose.
    for number, term in enumerate(payload.get('glossary', [])):
        if not isinstance(term, dict) or not term.get('term') or not term.get('meaning'):
            raise ValueError('Unsupported current Fatiha glossary entry')
        notes.append([_atom(path, ['glossary', number, 'term'], term['term'], 'note'),
                      _atom(path, ['glossary', number, 'meaning'], term['meaning'], 'note')])
    return {'sections': sections, 'notes': notes,
            'frontmatter': [_atom(path, ['shortCredit'], payload['shortCredit'], 'note')], 'endmatter': [],
            'reviewEvidence': {'catalogField': 'fatihaExtended1004', 'group': deepcopy(group),
                               'index': FATIHA_INDEX,
                               'qualification': 'Existing independently model-reviewed complete published reading; human verification remains needed.'},
            'additionalFiles': [], 'conditions': [source_path, FATIHA_INDEX],
            'sourceKind': 'reviewed-fatiha-packet', 'title': payload['title']}


def _qiyamah(root, row, payload):
    path = row['json']
    if (payload.get('schema'), payload.get('language'), payload.get('surah')) != ('iman-qiyamah-ja-index-v1', 'ja', 75):
        raise ValueError('Unsupported current Japanese Qiyamah index')
    if payload.get('sourceArabicSHA256') not in row.get('sourceHashes', []) or not payload.get('sourceCandidateSHA256'):
        raise ValueError('Qiyamah reader no longer matches its current Arabic source')
    index_entries = payload.get('entries', [])
    if [entry.get('key') for entry in index_entries] != [f'75:{n}' for n in range(1, 41)]:
        raise ValueError('Reviewed Qiyamah index loses or reorders a verse')
    front = read(root, QIYAMAH_FRONT)
    if not isinstance(front, list) or front[9].get('id') != 'word/document.xml:p0010':
        raise ValueError('Qiyamah original publisher credit changed')
    credit = [_atom(QIYAMAH_FRONT, [9, 'text'], front[9]['text'], 'note')]
    publication_note = read(root, QIYAMAH_PREFIX + '/SOURCE-NOTE658.json')
    shared_publication_notes = {normalize_lines(publication_note['text'])}
    shared_publication_notes.update(normalize_lines(link['label'] + ' · ' + link['url'])
                                    for link in publication_note['sourceLinks'])
    sections = []; additional = []; review = []
    for item in index_entries:
        source = (Path(path).parent / item['json']).as_posix()
        data = read(root, source); entry = data.get('unit', {})
        if (data.get('key'), data.get('language'), data.get('surah')) != (item['key'], 'ja', 75):
            raise ValueError('Qiyamah verse identity differs from its index')
        if (entry.get('sourceSha256') not in row['sourceHashes']
                or entry.get('status') != 'CONTENT_AND_SOURCES_QUALIFIED'
                or entry.get('translationStatus') != 'independently-reviewed-final'
                or entry.get('releaseQualified') is not True
                or entry.get('sourceAndEditorialQualified') is not True
                or entry.get('qualificationId') != 'Qiyamah-Astra649-final658'):
            raise ValueError('Qiyamah verse lacks its existing content/source qualification')
        blocks = [_source_block(source, ['unit', 'blocks', number], block)
                  for number, block in enumerate(entry.get('blocks', []))]
        if not blocks or blocks[0]['kind'] != 'ayah':
            raise ValueError('Qiyamah verse has no complete translated main text')
        contexts = data.get('completeReadingAndBoundedContext')
        if not isinstance(contexts, list) or [part['text'] for part in contexts if part.get('role') in {'current', 'core'}] != [block['text'] for block in blocks]:
            raise ValueError('Qiyamah complete reading differs from its reviewed verse paragraphs')
        notes = [{**_atom(source, ['completeReadingAndBoundedContext', number, 'text'], part['text'], 'note'),
                  'sharedPublicationNote': normalize_lines(part['text']) in shared_publication_notes}
                 for number, part in enumerate(contexts) if part.get('role') == 'note' and part.get('text')]
        if not shared_publication_notes.issubset({note['text'] for note in notes}):
            raise ValueError('Qiyamah verse omits the shared original publication qualification')
        if any(part.get('role') not in {'heading', 'current', 'core', 'note'} for part in contexts):
            raise ValueError('Unknown Qiyamah bounded-context display role')
        sections.append({'key': item['key'], 'heading': _atom(source, ['unit', 'heading'], entry['heading'], 'heading'),
                         'blocks': blocks, 'references': [], 'notes': notes, 'credit': credit})
        additional += [source, (Path(path).parent / item['markdown']).as_posix()]
        review.append({'key': item['key'], 'reviewRecord': entry.get('reviewRecord'),
                       'qualificationId': entry['qualificationId'],
                       'scope': entry.get('releaseQualificationScope'), 'reviewStatus': data.get('reviewStatus')})
    frontmatter = []; endmatter = []
    for number, paragraph in enumerate(front):
        if not paragraph.get('text') or number == 0:
            continue
        atom = _atom(QIYAMAH_FRONT, [number, 'text'], paragraph['text'],
                     'heading' if paragraph.get('style', '').startswith('Heading') else 'note')
        (frontmatter if paragraph['index'] < 12 else endmatter).append(atom)
        for link_number, link in enumerate(paragraph.get('links', [])):
            if link.get('url'):
                (frontmatter if paragraph['index'] < 12 else endmatter).append(
                    _atom(QIYAMAH_FRONT, [number, 'links', link_number, 'url'], link['url'], 'note'))
    conditions = [file.relative_to(root).as_posix() for file in sorted((root / QIYAMAH_PREFIX).glob('*.json'))]
    return {'sections': sections, 'notes': [], 'frontmatter': frontmatter, 'endmatter': endmatter,
            'reviewEvidence': review, 'additionalFiles': additional, 'conditions': conditions,
            'sourceKind': 'reviewed-japanese-qiyamah-index', 'title': front[0]['text']}


def _all_atoms(plan):
    def flatten(value):
        if isinstance(value, dict) and {'path', 'pointer', 'text'}.issubset(value):
            yield {name: value[name] for name in ('path', 'pointer', 'text', 'role')}
            for note in value.get('notes', []):
                yield from flatten(note)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from flatten(item)
    for section in plan['sections']:
        yield from flatten(section['heading'])
        for field in ('blocks', 'references', 'notes', 'credit'):
            yield from flatten(section[field])
    for field in ('notes', 'frontmatter', 'endmatter'):
        yield from flatten(plan[field])


def _inspect(root, catalog, row):
    root = Path(root).resolve()
    if not available(row) or row.get('collection') != 'tadabbur' or row.get('language') == 'ar':
        raise ValueError('Only available current translated Quran material can be imported')
    path = row.get('json'); language = row['language']; surah = canonical_surah(row)
    if not path or not row.get('markdown') or not surah:
        raise ValueError('Current Quran reader identity or paired sources are missing')
    arabic, arabic_files = _current_arabic(root, catalog, row)
    payload = read(root, path)
    if (language in ENTRY_LANGUAGES and surah in ENTRY_SURAHS
            and path == f'materials/tadabbur/{language}/extended/{surah:03d}.json'):
        plan = _entry_map(root, row, payload)
    elif str(row['id']) == 'fatiha-extended' and language in FATIHA_LANGUAGES:
        plan = _fatiha(root, catalog, row, payload)
    elif language == 'ja' and surah == 75 and path == 'materials/tadabbur/ja/extended/075.json':
        plan = _qiyamah(root, row, payload)
    else:
        raise ValueError('Unsupported current reviewed Quran source identity: ' + path)
    keys = [section['key'] for section in plan['sections']]
    verse_keys = [value for value in keys if re.fullmatch(r'\d+:\d+', value)]
    intro_keys = [value for value in keys if value == 'intro' or value.startswith('intro:')]
    if len(keys) != len(set(keys)) or len(verse_keys) + len(intro_keys) != len(keys) or not verse_keys:
        raise ValueError('Current Quran source has duplicate or unknown section identities')
    if verse_keys != sorted(verse_keys, key=lambda value: int(value.split(':')[1])):
        raise ValueError('Current Quran source verses are out of canonical order')
    if keys != [*intro_keys, *verse_keys] or any(not value.startswith(str(surah) + ':') for value in verse_keys):
        raise ValueError('Current Quran source introduction/verse order changed')
    literals = {}
    for atom in _all_atoms(plan):
        pointers = literals.setdefault(atom['path'], [])
        if atom['pointer'] not in pointers:
            pointers.append(atom['pointer'])
    sources = [binding(root, row[name]) for name in ('json', 'markdown')]
    sources += [binding(root, path) for path in plan['additionalFiles']]
    conditions = [binding(root, path) for path in plan['conditions']]
    conditions += arabic_files
    dedupe = lambda items: list({item['path']: item for item in items}.values())
    record = {'collection': 'tadabbur', 'language': language, 'id': str(row['id']), 'surah': surah,
              'catalogEntry': deepcopy(row), 'sourceKind': plan['sourceKind'],
              'sourceFiles': dedupe(sources), 'sourceConditions': dedupe(conditions),
              'currentArabicCatalogEntry': arabic,
              'currentRevisionBasis': 'Matching exact sourceHashes and per-entry Arabic revision.' if row.get('sourceHashes')
                  else 'Existing current-app Fatiha publication group; no unavailable original hash is invented.',
              'bookCoverage': {'ayahKeys': verse_keys, 'introductionSectionIds': intro_keys},
              'existingReview': plan['reviewEvidence'], 'literalFields': literals,
              'sourceApprovalCreated': False, 'humanCertification': False}
    return record, plan


def snapshot(root, catalog, source_commit):
    """Create a reviewable migration inventory; never run by the publisher."""
    if not re.fullmatch('[a-f0-9]{40}', source_commit):
        raise ValueError('Current source migration needs an exact original commit')
    result = []
    for row in catalog['entries']:
        if row.get('collection') != 'tadabbur' or row.get('language') == 'ar' or not available(row):
            continue
        surah = canonical_surah(row)
        if ((row.get('language') in ENTRY_LANGUAGES and surah in ENTRY_SURAHS)
                or (row.get('language') in FATIHA_LANGUAGES and str(row['id']) == 'fatiha-extended')
                or (row.get('language') == 'ja' and surah == 75)):
            record, _ = _inspect(root, catalog, row)
            result.append(record)
    result.sort(key=lambda record: (record['language'], record['surah'], record['id']))
    return {'schema': SCHEMA, 'sourceCommit': source_commit, 'records': result,
            'scope': 'Existing current app Quran publications with their original review qualifications; exact supplied coverage only.',
            'sourceApprovalCreated': False, 'humanCertification': False}


def validate_record(root, record, row, catalog):
    if key(row) != ('tadabbur', record.get('language'), str(record.get('id'))):
        raise ValueError('Current reviewed Quran source identity differs from catalogue')
    clean_row = {name: value for name, value in row.items() if name != 'bookReaderUnit'}
    if clean_row != record.get('catalogEntry'):
        raise ValueError('Current Quran catalogue changed after its bound source inventory')
    bindings = record.get('sourceFiles', []) + record.get('sourceConditions', [])
    if not bindings or len({item['path'] for item in bindings}) != len(bindings):
        raise ValueError('Missing or duplicated current Quran source bindings')
    for item in bindings:
        pinned(root, item)
    actual, _ = _inspect(root, catalog, clean_row)
    if actual != record:
        raise ValueError('Current Quran review, coverage, literal fields, or Arabic revision changed')
    return bindings


def records(root, declaration):
    result = []
    for evidence in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(root, evidence))
        if data.get('schema') == SCHEMA:
            result += [(record, evidence) for record in data.get('records', [])
                       if record.get('language') == declaration.get('language')]
    if len({record['id'] for record, _ in result}) != len(result):
        raise ValueError('Duplicate current reviewed Quran inventory identity')
    return result


def literal_sources(record):
    sources = {item['path']: item for item in record['sourceFiles'] + record['sourceConditions']}
    return [{'source': sources[path], 'pointer': list(pointer)}
            for path, pointers in record.get('literalFields', {}).items() for pointer in pointers]


def _proof(record, evidence, sources, atom):
    return {'schema': LITERAL_SCHEMA, 'collection': 'tadabbur-extended',
            'language': record['language'], 'materialId': record['id'],
            'source': deepcopy(sources[atom['path']]), 'inventory': deepcopy(evidence),
            'pointer': list(atom['pointer']), 'start': 0, 'end': len(atom['text']),
            'textSHA256': sha(atom['text'].encode('utf8'))}


def _ranges(keys, language):
    ranges = []
    for number in [int(key.split(':')[1]) for key in keys]:
        if ranges and ranges[-1][-1] + 1 == number:
            ranges[-1].append(number)
        else:
            ranges.append([number])
    return locale(language)['ayahLabel'] + ' ' + ', '.join(
        digits(values[0], language) + ('–' + digits(values[-1], language) if len(values) > 1 else '')
        for values in ranges)


def normalize(root, catalog, row, record, evidence):
    root = Path(root).resolve()
    bindings = validate_record(root, record, row, catalog)
    _, plan = _inspect(root, catalog, row)
    config = read(root, 'books/config.json')
    quran = json.loads(pinned(root, config['quranText']))
    names = json.loads(pinned(root, config['surahNames']))
    sources = {item['path']: item for item in bindings}
    language = row['language']; surah = record['surah']
    name = names[language][surah - 1]
    try:
        native_text(name, language)
    except ValueError:
        # The installed Bengali name table contains Latin transliterations for
        # some surahs. Existing localized furniture plus the canonical number
        # gives an accurate title without inventing a translated surah name.
        name = digits(surah, language)
    title = plan['title'] or (locale(language)['surahLabel'] + ' ' + name)
    native_text(title, language)
    sections = []; source_paragraphs = []; rendered_paragraphs = []; references = []; qualifications = []
    output_notes = []; seen_shared_notes = {}; preservation = []
    qualification_occurrences = 0; shared_qualification_duplicates = 0

    def proof(atom):
        return _proof(record, evidence, sources, atom)

    def block(atom, kind='paragraph'):
        result = {'kind': kind, 'text': atom['text'], 'role': ROLES.get(atom['role'], atom['role'])}
        spans = deepcopy(atom.get('spans') or [])
        if spans:
            for span in spans:
                span['text'] = normalize_lines(span['text'])
                span['role'] = ROLES[span.get('role', atom['role'])]
                # Source tokens remain provenance; only explicit canonical
                # references enter typed renderer annotations.
                for verse in span.get('verseKeys', []):
                    if any(key not in quran for key in expand_verse_key(verse)):
                        raise ValueError('Original Quran source reference is outside canonical text')
            result['spans'] = spans
        try:
            native_text(atom['text'], language)
        except ValueError:
            result['sourceLiteralProof'] = proof(atom)
        source_paragraphs.append(atom['text']); rendered_paragraphs.append(result['text'])
        preservation.append({'source': sources[atom['path']], 'pointer': atom['pointer'],
                             'sha256': sha(atom['text'].encode()), 'placement': 'reader paragraph'})
        return result

    def attach(target, value, category='qualification', shared=False, section_key=None):
        nonlocal qualification_occurrences, shared_qualification_duplicates
        atoms = value if isinstance(value, list) else [value]
        atoms = [atom for atom in atoms if atom['text'].strip()]
        if not atoms:
            return
        text = ' · '.join(atom['text'] for atom in atoms)
        if category != 'reference':
            qualification_occurrences += 1
        source_fields = [{'source': sources[atom['path']], 'pointer': atom['pointer'],
                          'sha256': sha(atom['text'].encode())} for atom in atoms]
        if shared and text in seen_shared_notes:
            shared_qualification_duplicates += 1
            preservation.append({'sources': source_fields, 'section': section_key,
                                 'placement': 'shared publication qualification already printed',
                                 'printedAt': deepcopy(seen_shared_notes[text])})
            return
        if shared:
            seen_shared_notes[text] = {'section': section_key, 'sources': source_fields}
        (references if category == 'reference' else qualifications).append(text)
        span = target.setdefault('spans', [{'text': target['text'], 'role': target.get('role', 'body')}])[-1]
        span.setdefault('noteTexts', []).append(text)
        span.setdefault('noteLiteralProofs', []).append([proof(atom) for atom in atoms])
        output_notes.append(text)
        preservation.append({'sources': source_fields, 'section': section_key,
                             'placement': 'original source/meaning footnote'})

    if plan['frontmatter']:
        sections.append({'blocks': [block(atom, 'heading' if atom['role'] == 'heading' else 'paragraph')
                                    for atom in plan['frontmatter']]})
    for original in plan['sections']:
        source_blocks = original['blocks']
        section_key = original['key']; is_verse = section_key in quran
        if not is_verse and not (section_key == 'intro' or section_key.startswith('intro:')):
            raise ValueError('Current Quran verse is not in the pinned canonical Quran')
        converted = []
        if is_verse:
            if source_blocks[0]['kind'] not in {'ayah', 'translation'} or not original['credit']:
                raise ValueError('Current Quran reading lacks its complete first translation or attribution')
            converted.append({'kind': 'ayah', 'verseKey': section_key, 'text': quran[section_key], 'role': 'current-ayah'})
            translation = block(source_blocks[0], 'translation')
            translation['translationCredit'] = {'language': language,
                'text': ' · '.join(atom['text'] for atom in original['credit']),
                'sourceLiteralProof': [proof(atom) for atom in original['credit']]}
            converted.append(translation)
            tail = source_blocks[1:]
        else:
            tail = source_blocks
        for atom in tail:
            converted.append(block(atom, atom['kind']))
        if not converted:
            raise ValueError('Current Quran normalized section has no body')
        # Preserve the original heading as furniture; all installed headings
        # are already localized and are validated independently.
        native_text(original['heading']['text'], language)
        section = {'heading': original['heading']['text'], 'blocks': converted}
        if is_verse:
            section['ayahKey'] = section_key
        sections.append(section)
        offset = 1 if is_verse else 0
        for number, atom in enumerate(source_blocks):
            for note in atom.get('notes', []):
                attach(converted[number + offset], note, section_key=section_key)
        for citation in original['references']:
            attach(converted[-1], citation, 'reference', section_key=section_key)
        for note in original['notes']:
            attach(converted[-1], note, shared=isinstance(note, dict) and note.get('sharedPublicationNote', False),
                   section_key=section_key)
    for atom in plan['endmatter']:
        sections[-1]['blocks'].append(block(atom, 'heading' if atom['role'] == 'heading' else 'paragraph'))
    for note in plan['notes']:
        attach(sections[-1]['blocks'][-1], note, section_key=plan['sections'][-1]['key'])
    if source_paragraphs != rendered_paragraphs:
        raise ValueError('Current Quran paragraph words or order changed')
    if any(text not in output_notes for text in set(references + qualifications)):
        raise ValueError('An original Quran source reference or meaning note was lost')
    keys = record['bookCoverage']['ayahKeys']
    canonical_keys = sorted([key for key in quran if key.startswith(str(surah) + ':')], key=lambda key: int(key.split(':')[1]))
    if any(key not in canonical_keys for key in keys):
        raise ValueError('Current Quran source exceeds canonical surah coverage')
    intro_text = ''.join(block['text'] for section in sections if not section.get('ayahKey') for block in section['blocks'])
    coverage = {'schema': 'iman-reviewed-quran-coverage-v1', 'surah': surah, 'ayahKeys': keys,
                'introduction': {'state': 'included', 'readerTextSHA256': sha(intro_text.encode())}
                    if intro_text else {'state': 'not-in-reviewed-material'}}
    if keys != canonical_keys:
        coverage['scopeLabel'] = AVAILABLE_AYAHS[language]
        title += ' · ' + coverage['scopeLabel']
    input_bindings = {item['path']: item for item in [*bindings, evidence, config['quranText'], config['surahNames']]}
    reader = ''.join(block['text'] for section in sections for block in section['blocks'])
    unit = {'schema': 'iman-book-unit-v1', 'id': str(row['id']), 'language': language,
            'collection': 'tadabbur-extended', 'surah': surah, 'order': surah, 'title': title,
            'complete': True, 'reviewGate': 'published-current',
            'sourceHashes': row.get('sourceHashes') or [sources[row['json']]['sha256']],
            'inputBindings': sorted(input_bindings.values(), key=lambda item: item['path']),
            'catalogBindings': [{'collection': 'tadabbur', 'language': language, 'id': row['id']}],
            'sections': sections, 'reviewedCoverage': coverage,
            'coverageLabel': _ranges(keys, language) if keys != canonical_keys else None,
            'readerTextSHA256': sha(reader.encode()),
            'sourceReferencePreservation': {'schema': 'iman-source-reference-preservation-v1',
                'auditMode': 'literal-source-and-qualification-fidelity',
                'sourceParagraphs': len(source_paragraphs), 'preservedParagraphs': len(rendered_paragraphs),
                'sourceReferences': len(references), 'preservedReferences': len(references),
                'sourceQualifications': len(qualifications), 'preservedQualifications': len(qualifications),
                'sourceQualificationOccurrences': qualification_occurrences,
                'deduplicatedSharedQualifications': shared_qualification_duplicates,
                'lostParagraphs': 0, 'lostReferences': 0, 'lostQualifications': 0},
            'provenance': {'adapter': ADAPTER, 'sourceKind': plan['sourceKind'],
                'sourceRecordSHA256': sha(canonical(record)), 'existingReview': deepcopy(record['existingReview']),
                'currentArabicCatalogEntry': deepcopy(record['currentArabicCatalogEntry']),
                'sourceFieldsPreserved': preservation,
                'sourceParagraphSHA256': sha(''.join(source_paragraphs).encode()),
                'renderedParagraphSHA256': sha(''.join(rendered_paragraphs).encode()),
                'originalSourceQualificationsUnchanged': True, 'sourceApprovalCreated': False,
                'humanCertification': False,
                'referencePresentation': 'Exact supplied source identities and qualifications; no inferred Hadith numbering.'}}
    # Root's generic checker validates the same literal proofs again at indexing
    # and final rendering.  This adapter also checks canonical section coverage.
    from reviewed_coverage import validate as validate_coverage
    validate_coverage(unit, quran)
    return unit


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    if declaration.get('collection') != 'tadabbur-extended' or declaration.get('language') == 'ar':
        raise ValueError('Current reviewed Quran adapter needs a translated Quran scope')
    by_key = {key(row): row for row in catalog['entries']}
    excluded = set(excluded_catalog_keys)
    result = []
    for record, evidence in records(root, declaration):
        identity = ('tadabbur', record['language'], record['id'])
        if identity in excluded:
            continue
        row = by_key.get(identity)
        if row is None or not available(row):
            continue
        result.append(normalize(root, catalog, row, record, evidence))
    result.sort(key=lambda unit: unit['order'])
    return result
