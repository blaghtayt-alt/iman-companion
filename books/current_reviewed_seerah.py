"""Adapt exact existing reviewed lecture-sequence readers without new approval.

These are their own installed editions, not translations of the newer Arabic
adult edition. Original model-review limitations, public source qualifications,
questions and their unresolved historical review bindings remain explicit.
"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re
import unicodedata

from bibliography import expand_verse_key, native_text
from book_edition_scope import available, inside, pinned
from locale_copy import locale
from source_literal_text import normalize_lines

SCHEMA = 'iman-current-reviewed-seerah-source-bindings-v1'
ADAPTER = 'current-reviewed-seerah-v1'
EDITION = 'current-lecture-sequence'
PROJECTION = 'books/source-projections/current-reviewed-seerah.json'
LECTURE = {'hi': 10, 'ru': 10, 'es': 10, 'fa': 10, 'de': 9, 'zh-CN': 9}
FIRST_PAIR = ('ja', 'vi', 'th', 'uz', 'fil')
SUPPORTED = {**LECTURE, **{language: 2 for language in FIRST_PAIR}}
COMMON = ('materials/REUSE.md', 'materials/SOURCES-AND-METHOD.md')
FIRST_INDEX = 'materials/seerah/reviewed-first-pair/README.md'
LECTURE_INDEX = 'materials/seerah/combined/README.md'
SURAH_NAMES = 'books/assets/surah-names.json'
CREDIT = 'Source: Ahmad al-Sayyid’s Seerah lecture sequence; Arabic summaries prepared for Iman Companion. Credited quotations keep their publishers’ terms.'
QUALIFICATION = ('Exact existing independently model-reviewed published lecture-sequence reader; '
                 'human verification remains needed. No new translation, source, Word or visual approval is created.')
# Public source contexts are selected explicitly. Review transcripts, authoring
# workpapers and earlier replacement candidates are not a second reader body.
PUBLIC_REVIEW = ('quoteProvenance', 'hadithQuoteProvenance', 'hadithQuoteStatus',
                 'hadithEditorialGap', 'hadithEditorialGaps', 'QuranEditionMetadata',
                 'rights')
PRIVATE_KEYS = {'localFile', 'localPdf', 'replacementFile', 'comparisonFile', 'visualEvidence',
                'reviewer', 'independentReviewer', 'reviewDate', 'reviewFocus', 'reviewRecords',
                'targetBeforeQuranAssembly', 'sourceParagraphs',
                'inputFile', 'outputFile', 'reportFile', 'cachePath'}
HEX = re.compile(r'[a-f0-9]{64}')
PRIVATE_PATH = re.compile(r'''(?<![A-Za-z0-9])(?:/workspace/|/mnt/data/|/tmp/|/root/|work/|[A-Za-z]:\\)[^\s,;)\]}<>"'`]+''')
CATALOGUE_PLUMBING = {'direction', 'language_iso_code', 'last_update', 'file', 'database_url',
    'database_uncompressed_url', 'key', 'id', 'sura', 'aya', 'locale', 'retrieved',
    'paragraphIndex', 'paragraphIndices', 'appendixStartIndex', 'fullSourceAppendixIndex',
    'labelLocations', 'targetParagraph', 'arabicSourceParagraph', 'sourceParagraphs',
    'pdf_size', 'pdf_cover', 'pdf_pure_size', 'pdf_pure_cover', 'epub_url', 'epub_size',
    'epub_cover', 'queries', 'query', 'field', 'reviewRequired', 'reviewFocus'}
DUPLICATE_READER_FIELDS = {'text', 'translation', 'arabic', 'sourceArabic', 'arabicQuotedText',
    'displayedText', 'integratedParagraph', 'target', 'quotedText', 'quotedParagraph',
    'exactText', 'publishedOriginal', 'displayedParagraph', 'publishedSpans', 'arabicExcerpt'}
PUBLIC_NOTE_CONTEXT = ('note', 'footnote', 'qualification', 'reservation', 'rights', 'permission',
                       'condition', 'transcript', 'issue', 'sunnasourcebasis', 'sourceuse', 'sourcefirst')
RAW_PAGE_EVIDENCE = ('materials/seerah/de/chapter-04.json',
                     ('review', 'quoteProvenance', 1, 'originalPageText'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')


def historical_hash(value):
    """The original reviews used the default spaced JSON serialization."""
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8'))


def pointer(value, path):
    for part in path:
        if isinstance(value, list) and type(part) is int:
            value = value[part]
        elif isinstance(value, dict) and isinstance(part, str):
            value = value[part]
        else:
            raise ValueError('Invalid current Seerah source pointer')
    return value


def _stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@lru_cache(maxsize=256)
def _source_bytes(path, stamp):
    raw = path.read_bytes()
    if _stamp(path) != stamp:
        raise ValueError('Seerah source changed during inspection')
    return raw


@lru_cache(maxsize=256)
def _source_json(path, stamp):
    return json.loads(_source_bytes(path, stamp))


def raw(root, relative):
    path = inside(Path(root), relative)
    return _source_bytes(path, _stamp(path))


def read(root, relative):
    path = inside(Path(root), relative)
    return _source_json(path, _stamp(path))


def binding(root, relative):
    return {'path': relative, 'sha256': sha(raw(root, relative))}


def _paths(language, chapter):
    base = (f'materials/seerah/{language}/chapter-{chapter:02d}' if language in LECTURE
            else f'materials/seerah/reviewed-first-pair/{language}/{chapter:02d}')
    return base + '.json', base + '.md'


def _question_evidence(payload, language, chapter):
    questions = payload.get('questions')
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError('Each existing Seerah chapter must keep its five questions')
    if len({question.get('id') for question in questions}) != len(questions):
        raise ValueError('Duplicate Seerah question identity')
    for question in questions:
        value = question['translation'] if language in LECTURE else question
        if (not isinstance(value.get('question'), str) or not value['question'].strip()
                or not isinstance(value.get('options'), list) or len(value['options']) != 3
                or any(not isinstance(option, str) or not option.strip() for option in value['options'])):
            raise ValueError('Changed Seerah question or answer-choice structure')
    result = {'currentSourceQuestionsPreserved': True, 'currentQuestionsSHA256': historical_hash(questions),
              'questions': [], 'normalizationEquivalenceEstablished': False}
    if language not in LECTURE:
        result.update(status='existing-published-model-review-qualification',
                      independentlyHashVerified=False, unresolvedReviewBinding=False)
        return result
    review = payload['review']
    if chapter > 1:
        original = review.get('questions', [])
        if len(original) != len(questions):
            raise ValueError('Seerah per-question review inventory changed')
        for index, (question, approved) in enumerate(zip(questions, original)):
            digest = historical_hash(question['translation'])
            if approved.get('id') != question['id'] or approved.get('translationSHA256') != digest:
                raise ValueError('Seerah question differs from its existing exact review')
            result['questions'].append({'id': question['id'], 'currentTranslationSHA256': digest,
                'matchingExistingReviewHashPointers': [['review', 'questions', index, 'translationSHA256']],
                'status': 'exact-existing-review-hash-verified'})
        result.update(status='exact-existing-per-question-hashes-verified', unresolvedReviewBinding=False)
        return result

    def hashes(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'translationSHA256', 'translationSha256'} and isinstance(child, str):
                    yield path + [key], child
                elif isinstance(child, (dict, list)):
                    yield from hashes(child, path + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from hashes(child, path + [index])

    recorded = list(hashes(review, ['review']))
    for question in questions:
        digest = historical_hash(question['translation'])
        matches = [path for path, value in recorded if value == digest]
        object_digest = historical_hash({'id': question['id'], **question['translation']})
        object_matches = []
        extra = review.get('extraQuestionsIndependentReview', {})
        for index, approved in enumerate(extra.get('records', [])):
            if (approved.get('language'), approved.get('id')) != (language, question['id']):
                continue
            if (extra.get('status') == 'approved-independent-ai-reviewed'
                    and extra.get('humanCertification') is False
                    and approved.get('decision') == 'approved-independent-ai-reviewed'
                    and approved.get('humanCertification') is False
                    and approved.get('answerOrderVerified') is True
                    and approved.get('approvedTranslationSha256') == object_digest):
                object_matches.append({
                    'hashPointer': ['review', 'extraQuestionsIndependentReview', 'records', index, 'approvedTranslationSha256'],
                    'projection': 'existing-question-id-plus-translation-fields',
                    'currentProjectionSHA256': object_digest,
                    'language': language, 'id': question['id'],
                    'decision': approved['decision'], 'humanCertification': False})
        result['questions'].append({'id': question['id'], 'currentTranslationSHA256': digest,
            'matchingExistingReviewHashPointers': matches,
            'matchingExistingQuestionObjectReviewBindings': object_matches,
            'status': 'exact-existing-review-hash-verified' if matches or object_matches else 'unreconciled-existing-review-binding'})
    result.update(recordedFinalQuestionsSha256=review.get('finalQuestionsSha256'),
                  aggregateHashStatus='unreconciled-with-current-normalized-questions',
                  status='unreconciled-existing-review-binding', unresolvedReviewBinding=True)
    if not HEX.fullmatch(str(result['recordedFinalQuestionsSha256'])):
        raise ValueError('Original first-chapter question review claim is missing')
    return result


def _source_contract(root, row, catalog):
    language = row.get('language')
    chapter = row.get('chapter')
    if (language not in SUPPORTED or type(chapter) is not int or not 1 <= chapter <= SUPPORTED[language]
            or str(row.get('id')) != str(chapter) or row.get('collection') != 'seerah'
            or row.get('edition') != EDITION or not available(row)
            or row.get('translationStatus') != 'ai-translated-needs-verification'):
        raise ValueError('Outside the exact current reviewed lecture-sequence edition')
    json_path, md_path = _paths(language, chapter)
    if row.get('json') != json_path or row.get('markdown') != md_path:
        raise ValueError('Current Seerah source paths differ from the installed reader')
    payload = read(root, json_path)
    if payload.get('language') != language:
        raise ValueError('Current Seerah source language changed')
    arabic_path = f'materials/seerah/ar/chapter-{chapter:02d}.json'
    arabic = read(root, arabic_path)
    if arabic.get('chapter') != chapter or arabic.get('language') != 'ar':
        raise ValueError('Original lecture-sequence Arabic source identity changed')
    if language in LECTURE:
        review = payload.get('review', {})
        content = payload.get('content', {})
        digest = historical_hash(content)
        claim = review.get('finalTranslationSha256') if chapter == 1 else review.get('integratedTranslationSHA256')
        if (payload.get('chapter') != chapter or review.get('chapterId') != chapter
                or review.get('locale') != language or review.get('status') != 'approved-independent-ai-reviewed'
                or review.get('humanCertification') is not False
                or payload.get('publicationStatus') != 'ai-translated-needs-verification'
                or digest != claim or historical_hash(arabic['content']) != review.get('sourceArabicSHA256')):
            raise ValueError('Existing Seerah reader, Arabic source or qualified review binding changed')
        if ('AI translated' not in payload.get('notice', '') or 'needs verification' not in payload['notice']
                or 'not certification' not in payload['notice']):
            raise ValueError('Original Seerah human-verification qualification changed')
        if content.get('paragraphs') != [block.get('text') for block in content.get('blocks', [])]:
            raise ValueError('Seerah ordinary and typed reader paragraphs differ')
        status = {'sourceStatus': payload['publicationStatus'], 'notice': payload['notice'],
                  'reviewStatus': review['status'], 'humanCertification': False,
                  'reviewSHA256': sha(canonical(review)), 'readerContentSHA256': digest,
                  'recordedReaderHashField': 'finalTranslationSha256' if chapter == 1 else 'integratedTranslationSHA256',
                  'arabicSourceSHA256': review['sourceArabicSHA256'], 'arabicSourceHashVerified': True}
    else:
        content = payload
        translation_status = read(root, 'materials/translation-status.json')
        group = catalog.get('seerahFirstPairs1003')
        other = translation_status.get('seerahFirstPairs1003')
        if (payload.get('id') != f'seerah-{chapter:02d}' or row.get('status') != 'current-app-edition'
                or payload.get('status') != 'independently model-reviewed; human verification needed'
                or not isinstance(group, dict) or not isinstance(other, dict)
                or language not in group.get('languages', []) or language not in other.get('languages', [])
                or chapter not in group.get('chapters', []) or chapter not in other.get('chapters', [])
                or 'installed locally and published' not in group.get('scope', '')
                or 'human verification needed' not in other.get('status', '')):
            raise ValueError('Existing first-pair Seerah publication qualification changed')
        status = {'sourceStatus': payload['status'], 'catalogFields': {'seerahFirstPairs1003': deepcopy(group)},
                  'translationStatusFields': {'seerahFirstPairs1003': deepcopy(other)},
                  'humanCertification': False, 'arabicSourceHashVerified': False,
                  'arabicSourceQualification': 'Bound original lecture-sequence reference; no unavailable translation-equivalence hash is invented.'}
    if not isinstance(content.get('title'), str) or not content['title'].strip() or not content.get('blocks'):
        raise ValueError('Empty current Seerah reader')
    markdown = normalize_lines(raw(root, md_path).decode('utf8'))
    for block in content['blocks']:
        if (block.get('kind') not in {'heading', 'paragraph', 'ayah', 'hadith', 'source'}
                or not isinstance(block.get('text'), str) or not block['text'].strip()
                or normalize_lines(block['text']) not in markdown):
            raise ValueError('Original Seerah typed reader is missing from its ordinary published reading')
    return payload, status, _question_evidence(payload, language, chapter)


def _private(key, value):
    if (key in PRIVATE_KEYS or re.search(r'(?:sha256|sha1|digest)$', key, re.I)
            or key in {'inputFileSha256', 'before', 'after'}):
        return True
    if isinstance(value, str):
        return (bool(PRIVATE_PATH.fullmatch(value.strip()))
                or value == 'root' or bool(re.fullmatch(r'(?:/?root/)?[a-z_]*(?:translation|review)[a-z_]*[0-9]+', value)))
    return False


def _scalar(value):
    if isinstance(value, str):
        return normalize_lines(value)
    if type(value) in (int, float, bool):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError('Source metadata field is not a printable scalar')


def _field_text(root, field):
    if field.get('displayMode') == 'source-citation':
        return '; '.join(_field_text(root, {**part, 'sourcePath': field['sourcePath']}) for part in field['parts'])
    if field['pointer'] == ['$text']:
        text = normalize_lines(raw(root, field['sourcePath']).decode('utf8'))
        start, end = field.get('range', (0, len(text)))
        return text[start:end]
    value = pointer(read(root, field['sourcePath']), field['pointer'])
    text = _scalar(value)
    if field.get('displayMode') == 'labelled-source-field':
        # Mixed public qualifications keep every surrounding source character.
        # Only actual private locator substrings are replaced by a visible ellipsis.
        if field.get('privateLocatorRanges') != [list(match.span()) for match in PRIVATE_PATH.finditer(text)]:
            raise ValueError('Private source-locator disposition changed')
        text = PRIVATE_PATH.sub('[…]', text)
        text = field['label'] + ': ' + text
    return text


def _caption(key):
    """Short source-provided field words, never a JSON path or schema token."""
    words = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key).replace('_', ' ')
    return words[:1].upper() + words[1:]


def _public_leaf(value, path, reader_texts, *, first_pair):
    key = next((part for part in reversed(path) if isinstance(part, str)), '')
    if first_pair:
        return True
    context = '/'.join(str(part) for part in path).lower()
    note = any(word in context for word in PUBLIC_NOTE_CONTEXT)
    if key in CATALOGUE_PLUMBING:
        return False
    if key in {'type', 'mode', 'status', 'reviewStatus', 'translationStatus', 'normalization'}:
        # Complete publisher limitations survive; machine enum tokens do not.
        return isinstance(value, str) and len(value.split()) >= 5
    if key in {'humanCertification', 'humanVerified'} and not note:
        return False  # The supplied notice already preserves this qualification.
    if key in DUPLICATE_READER_FIELDS and not note:
        return False
    duplicate_quotation = (key in {'quote', 'publishedExcerpt', 'hadith_text', 'hadith_text_ar'}
                           or (key == 'title' and 'fullRecord' in path))
    if duplicate_quotation and isinstance(value, str) and not note and len(value) > 40:
        normalized = normalize_lines(value).strip()
        if any(normalized == text.strip() or normalized in text for text in reader_texts):
            return False
    return True


def _compact_context(root, fields):
    """Group short publication facts and print exact duplicate context once."""
    grouped, pending = [], []
    def flush():
        if len(pending) <= 1:
            grouped.extend(pending)
        else:
            first = pending[0]
            item = {key: deepcopy(value) for key, value in first.items()
                    if key not in {'label', 'privateLocatorRanges', 'textSHA256'}}
            item['pointer'] = first['pointer'][:-1]
            item['displayMode'] = 'source-citation'
            item['parts'] = [{key: deepcopy(value) for key, value in part.items()
                              if key in {'pointer', 'displayMode', 'label', 'privateLocatorRanges'}} for part in pending]
            item['textSHA256'] = sha(_field_text(root, item).encode('utf8'))
            grouped.append(item)
        pending.clear()
    for field in fields:
        short = (field['section'] == 'source-context' and field['purpose'] == 'source-qualification'
                 and len(_field_text(root, field)) <= 180 and '\n' not in _field_text(root, field))
        if short:
            if pending and (field['sourcePath'], field['pointer'][:-1]) != (pending[0]['sourcePath'], pending[0]['pointer'][:-1]):
                flush()
            pending.append(field)
        else:
            flush(); grouped.append(field)
    flush()
    result, seen = [], {}
    for field in grouped:
        if field['section'] != 'source-context':
            result.append(field)
            continue
        text = _field_text(root, field)
        if text in seen:
            # Only complete identical source context is deduplicated. All source
            # pointers remain explicit aliases; reader prose/questions never are.
            seen[text].setdefault('aliases', []).append(deepcopy(field))
        else:
            result.append(field); seen[text] = field
    return result


def _companion_visible(relative, paragraph):
    if relative == LECTURE_INDEX:
        return paragraph.startswith(('I prepared these summaries', '**AI translated', 'These materials are open source'))
    if relative == FIRST_INDEX:
        return paragraph.startswith(('These reader texts follow', 'Other chapters are not represented'))
    if relative == 'materials/REUSE.md':
        return paragraph.startswith(('My original editorial contributions', 'You may use those contributions',
                                     'This dedication covers', 'All translated summaries'))
    if relative == 'materials/SOURCES-AND-METHOD.md':
        return paragraph.startswith(('The summaries follow', 'The summaries aim', 'Hadith reading files preserve',
                                     'For the newer Seerah translations', 'Arabic remains the reference', 'All non-Arabic summaries'))
    return False


def reader_plan(root, row, payload):
    language, chapter, source = row['language'], row['chapter'], row['json']
    fields, excluded, evidence_only = [], [], []
    content = payload.get('content', payload)
    reader_texts = [normalize_lines(block['text']) for block in content['blocks']]
    def field(path, purpose, *, kind='paragraph', role='body', section='reader', label=None, **extra):
        value = pointer(payload, path)
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        item = {'sourcePath': source, 'pointer': list(path), 'purpose': purpose,
                'kind': kind, 'role': role, 'section': section,
                'displayMode': 'labelled-source-field' if label is not None else 'value', **extra}
        if label is not None:
            item['label'] = label
            item['privateLocatorRanges'] = [list(match.span()) for match in PRIVATE_PATH.finditer(_scalar(value))]
        item['textSHA256'] = sha(_field_text(root, item).encode('utf8'))
        fields.append(item)
    def public_tree(value, path):
        if isinstance(value, dict):
            for name, child in value.items():
                if (source, tuple(path + [name])) == RAW_PAGE_EVIDENCE:
                    # This is the raw entire PDF page, including its layout
                    # controls and unrelated later narrations. The selected
                    # quotation, complete required footnote and publication
                    # conditions have their own exact reader/source fields.
                    # Keep the extraction untouched as bound source evidence;
                    # neither strip its controls nor add it as a second reader.
                    quote = pointer(payload, path)
                    body = ['content', 'blocks', quote['paragraphIndex'], 'text']
                    if (not isinstance(child, str) or not isinstance(quote.get('displayedText'), str)
                            or quote['displayedText'] not in pointer(payload, body)):
                        raise ValueError('Raw PDF evidence lost its separately preserved selected quotation')
                    retained = [body] + [path + [key] for key in (
                        'reference', 'publisherFootnote366', 'publishedPage', 'edition', 'sourceURL',
                        'permissionPage', 'permissionStatement', 'normalization')]
                    if any(pointer(payload, item) in (None, '') for item in retained):
                        raise ValueError('Raw PDF evidence lost a required public source qualification')
                    evidence_only.append({'sourcePath': source, 'pointer': path + [name],
                        'originalTextSHA256': sha(child.encode('utf8')),
                        'disposition': 'raw-whole-page-extraction-retained-as-source-evidence',
                        'retainedDisplayPointers': retained,
                        'readerTextRewritten': False, 'sourceTextRewritten': False})
                    continue
                publisher_reviewer = (name == 'reviewer' and path and path[0] == 'sourceProvenance' and not _private('', child))
                if _private(name, child) and not publisher_reviewer:
                    excluded.append(path + [name])
                else:
                    public_tree(child, path + [name])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if _private('', child):
                    excluded.append(path + [index])
                else:
                    public_tree(child, path + [index])
        elif value is not None:
            if _public_leaf(value, path, reader_texts, first_pair=language in FIRST_PAIR):
                key = next(part for part in reversed(path) if isinstance(part, str))
                field(path, 'source-qualification', role='note', section='source-context', label=_caption(key))

    prefix = ['content'] if language in LECTURE else []
    content = pointer(payload, prefix)
    notice = ['notice'] if language in LECTURE else ['status']
    field(notice, 'review-qualification', role='note')
    indexed = [(index if language in LECTURE else block['index'], index, block)
               for index, block in enumerate(content['blocks'])]
    sources = payload.get('sourceProvenance', {}).get('sourceOnlyBlocks', []) if language not in LECTURE else []
    merged = [(position, prefix + ['blocks', index], block, False) for position, index, block in indexed]
    merged.extend((block['index'], ['sourceProvenance', 'sourceOnlyBlocks', index], block, True)
                  for index, block in enumerate(sources))
    if len({position for position, _, _, _ in merged}) != len(merged):
        raise ValueError('Overlapping Seerah reader and source-note positions')
    for position, path, block, source_only in sorted(merged):
        for extra in ('meaningLabel', 'excerptQualification'):
            if block.get(extra):
                field(path + [extra], 'meaning-qualification', role='note', originalBlock=position)
        source_note = source_only or block['kind'] == 'source'
        kind = 'note' if source_note else {'ayah': 'translation', 'hadith': 'quotation'}.get(block['kind'], block['kind'])
        role = 'note' if source_note else {'ayah': 'quran', 'hadith': 'hadith', 'heading': 'heading'}.get(block['kind'], 'body')
        field(path + ['text'], 'source-reference' if source_note else 'reader-block',
              kind=kind, role=role, originalBlock=position, sourceKind=block['kind'])
    for index, question in enumerate(payload['questions']):
        base = ['questions', index] + (['translation'] if language in LECTURE else [])
        field(base + ['question'], 'question', kind='heading', section='questions')
        for option in range(len(pointer(payload, base)['options'])):
            field(base + ['options', option], 'answer-choice', kind='list-item', section='questions')
    if language not in LECTURE:
        for name, purpose in (('readerNotes', 'reader-note'), ('glossary', 'glossary')):
            for index, item in enumerate(payload.get(name, [])):
                for key in (('id', 'title', 'marker', 'text') if name == 'readerNotes' else ('term', 'meaning')):
                    if key in item:
                        field([name, index, key], purpose, role='note', section=name,
                              label=None,
                              kind='heading' if key in {'title', 'term'} else 'paragraph')
        field(['sourceCredit'], 'source-credit', role='note', section='source-context')
        if payload.get('channelCredit') is not None:
            public_tree(payload['channelCredit'], ['channelCredit'])
        for name, value in payload.get('sourceProvenance', {}).items():
            if name == 'sourceOnlyBlocks':
                continue
            if name in {'readerNotes', 'glossary'} and value == payload.get(name):
                continue  # Exact duplicate representations have one printed instance.
            public_tree(value, ['sourceProvenance', name])
    else:
        for name in PUBLIC_REVIEW:
            if name in payload['review']:
                public_tree(payload['review'][name], ['review', name])
        for name in ('sources', 'decisions'):
            value = payload['review'].get('sourceSearch', {}).get(name)
            if value is not None:
                public_tree(value, ['review', 'sourceSearch', name])
        markdown = normalize_lines(raw(root, row['markdown']).decode('utf8'))
        if markdown.count(CREDIT) != 1:
            raise ValueError('Original Seerah lecture credit is missing or ambiguous')
        start = markdown.index(CREDIT)
        fields.append({'sourcePath': row['markdown'], 'pointer': ['$text'], 'range': [start, start + len(CREDIT)],
                       'displayMode': 'value', 'purpose': 'source-credit', 'kind': 'paragraph', 'role': 'note',
                       'section': 'source-context', 'textSHA256': sha(CREDIT.encode('utf8'))})
    # Shared published qualification/reuse companions appear once, in chapter 1.
    if chapter == 1:
        companions = [LECTURE_INDEX if language in LECTURE else FIRST_INDEX, *COMMON]
        for relative in companions:
            text = normalize_lines(raw(root, relative).decode('utf8'))
            for match in re.finditer(r'\S(?:.*?\S)?(?=\n[ \t]*\n|\Z)', text, re.S):
                start, end = match.span()
                if not _companion_visible(relative, text[start:end]):
                    continue
                fields.append({'sourcePath': relative, 'pointer': ['$text'], 'range': [start, end],
                    'displayMode': 'value', 'purpose': 'shared-source-companion', 'kind': 'paragraph', 'role': 'note',
                    'section': 'source-context', 'textSHA256': sha(text[start:end].encode('utf8'))})
    compact = _compact_context(root, fields)
    def displayed_pointers(field):
        yield tuple(field['pointer'])
        for part in field.get('parts', []) + field.get('aliases', []):
            yield from displayed_pointers(part)
    displayed = {item for field in compact if field['sourcePath'] == source for item in displayed_pointers(field)}
    if any(tuple(item) not in displayed for evidence in evidence_only for item in evidence['retainedDisplayPointers']):
        raise ValueError('Required quotation or source qualification was omitted beside raw PDF evidence')
    return {'title': {'sourcePath': source, 'pointer': prefix + ['title'], 'displayMode': 'value'},
            'fields': compact, 'privateEvidencePointersExcludedFromReader': excluded,
            **({'sourceEvidenceOnlyFields': evidence_only} if evidence_only else {}),
            'sourceContextDisposition': 'Recorded source qualifications and research history, separate from current reader prose; no new review or authentication claim.'}


def _record(root, row, catalog, source_commit):
    payload, status, questions = _source_contract(root, row, catalog)
    chapter, language = row['chapter'], row['language']
    conditions = [LECTURE_INDEX if language in LECTURE else FIRST_INDEX, *COMMON, SURAH_NAMES,
                  f'materials/seerah/ar/chapter-{chapter:02d}.json', f'materials/seerah/ar/chapter-{chapter:02d}.md']
    return {'collection': 'seerah', 'language': language, 'id': str(row['id']), 'chapter': chapter, 'edition': EDITION,
            'catalogEntry': {key: deepcopy(value) for key, value in row.items() if key != 'bookReaderUnit'},
            'sourceFiles': [binding(root, row[name]) for name in ('json', 'markdown')],
            'sourceConditions': [binding(root, name) for name in conditions],
            'existingPublication': {'sourceCommit': source_commit,
                'catalogEntryBeforeEditionClassification': {key: deepcopy(value) for key, value in row.items() if key not in {'bookReaderUnit', 'edition'}},
                **status}, 'questionReviewEvidence': questions,
            'displayPlan': reader_plan(root, row, payload), 'qualification': QUALIFICATION}


def inventory(root, catalog, source_commit):
    root = Path(root).resolve()
    if not re.fullmatch(r'[a-f0-9]{40}', source_commit):
        raise ValueError('Bind the existing published source commit explicitly')
    records = []
    for language, count in sorted(SUPPORTED.items()):
        for chapter in range(1, count + 1):
            matches = [row for row in catalog['entries']
                       if (row.get('collection'), row.get('language'), str(row.get('id'))) == ('seerah', language, str(chapter))]
            if len(matches) != 1:
                raise ValueError('Missing or duplicate current Seerah catalogue chapter')
            records.append(_record(root, matches[0], catalog, source_commit))
    return {'schema': SCHEMA, 'sourceCommit': source_commit, 'edition': EDITION, 'records': records,
            'sourceApprovalCreated': False, 'humanCertification': False,
            'scope': 'Exactly 68 installed qualified model-reviewed chapters in eleven distinct lecture-sequence language editions; newer Arabic adult chapters are separate.'}


def records(root, declaration):
    result = []
    for evidence in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(Path(root), evidence))
        if data.get('schema') == SCHEMA:
            result.extend((record, evidence) for record in data['records']
                          if record.get('language') == declaration.get('language'))
    if len({record['id'] for record, _ in result}) != len(result):
        raise ValueError('Duplicate current Seerah source inventory identity')
    return result


def validate_record(root, record, row, catalog):
    source_commit = record.get('existingPublication', {}).get('sourceCommit', '')
    if not re.fullmatch(r'[a-f0-9]{40}', source_commit):
        raise ValueError('Missing original published Seerah source commit')
    for item in record.get('sourceFiles', []) + record.get('sourceConditions', []):
        pinned(Path(root), item)
    expected = _record(Path(root), row, catalog, source_commit)
    if record != expected:
        raise ValueError('Current Seerah source, review qualifications, questions or display plan changed')
    if record['language'] in LECTURE:
        declarations = read(root, 'books/reviewed-books.json')
        scopes = [item for item in declarations['books'] if (item.get('language'), item.get('collection')) == (record['language'], 'seerah')]
        if (len(scopes) != 1 or scopes[0].get('automaticRelease') is not False
                or not isinstance(scopes[0].get('releaseHold'), str) or 'question' not in scopes[0]['releaseHold'].lower()):
            raise ValueError('Unreconciled first-chapter question review requires its explicit scope release hold')
    return record['sourceFiles'] + record['sourceConditions']


def literal_sources(record):
    sources = {item['path']: item for item in record['sourceFiles'] + record['sourceConditions']}
    found, seen = [], set()
    for field in [record['displayPlan']['title'], *record['displayPlan']['fields']]:
        item = {'source': sources[field['sourcePath']], 'pointer': field['pointer']}
        identity = (field['sourcePath'], tuple(field['pointer']))
        if identity not in seen:
            seen.add(identity)
            found.append(item)
    return found


def literal_value(root, record, proof):
    fields = [record['displayPlan']['title'], *record['displayPlan']['fields']]
    matches = [field for field in fields if field['sourcePath'] == proof['source']['path']
               and field['pointer'] == proof['pointer'] and field.get('displayMode', 'value') == proof.get('displayMode', 'value')
               and (field.get('textSHA256') or sha(_field_text(root, field).encode('utf8'))) == proof.get('textSHA256')]
    if not matches:
        raise ValueError('Seerah literal proof is not on a selected original field')
    if proof['pointer'] == ['$text']:
        text = normalize_lines(raw(root, proof['source']['path']).decode('utf8'))
        if not any(field.get('range') == [proof.get('start'), proof.get('end')] for field in matches):
            raise ValueError('Seerah source companion proof range changed')
        return text
    values = {_field_text(root, field) for field in matches}
    if len(values) != 1:
        raise ValueError('Ambiguous Seerah source field presentation')
    return values.pop()


def _verse_keys(value, quran):
    """Read only explicit numeric locators that exist in the bound Quran cache."""
    values = value if isinstance(value, list) else [value]
    keys = []
    for text in values:
        if not isinstance(text, str):
            continue
        digits = ''.join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in text)
        for match in re.finditer(r'(?<![0-9])([0-9]{1,3})\s*[:：]\s*([0-9]{1,3})(?:\s*[-–—]\s*([0-9]{1,3}))?', digits):
            surah, first, last = match.groups()
            key = str(int(surah)) + ':' + str(int(first)) + ('-' + str(int(last)) if last and last != first else '')
            try:
                expanded = expand_verse_key(key)
            except ValueError:
                continue
            if expanded and all(item in quran for item in expanded) and key not in keys:
                keys.append(key)
    return keys


def _named_verse_bindings(root, row, fields, quran):
    """Resolve an explicit native-name locator by exact table equality only."""
    names = read(root, SURAH_NAMES).get(row['language'], [])
    if (not isinstance(names, list) or len(names) != 114
            or any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != 114):
        raise ValueError('Current Seerah needs the exact complete native surah-name inventory')
    found = []
    for field in fields:
        if field is None:
            continue
        text = _field_text(root, field)
        for index, name in enumerate(names):
            pattern = r'(?<!\w)' + re.escape(name) + r'\s*[:：]\s*([\d]+)(?:\s*[-–—]\s*([\d]+))?(?!\d)'
            for match in re.finditer(pattern, text):
                first, last = match.groups()
                first = ''.join(str(unicodedata.digit(char)) for char in first)
                last = ''.join(str(unicodedata.digit(char)) for char in last) if last else None
                keys = _verse_keys(f'{index + 1}:{first}' + ('-' + last if last else ''), quran)
                if keys:
                    found.append({'sourcePointer': field['pointer'], 'sourceTextSHA256': field['textSHA256'],
                                  'exactLocator': match.group(), 'locatorRange': list(match.span()),
                                  'nameTable': binding(root, SURAH_NAMES), 'namePointer': [row['language'], index],
                                  'exactNativeName': name, 'verseKeys': keys})
    return found


def _review_verse_bindings(payload, field, text, quran):
    """Use the original review's paragraph identity and exact quoted text.

    A grouped review entry is split only by its own complete verse translations;
    its full verse list is never assigned wholesale to every narrative paragraph.
    """
    found = []
    for index, quote in enumerate(payload.get('review', {}).get('quoteProvenance', [])):
        if not isinstance(quote, dict):
            continue
        if 'quran' not in str(quote.get('type', '')).lower() and 'verseKey' not in quote:
            continue
        positions = quote.get('paragraphIndices', [quote.get('paragraphIndex')])
        if field['originalBlock'] not in positions:
            continue
        base = ['review', 'quoteProvenance', index]
        keys, witnesses = [], []
        for name in ('integratedParagraph', 'displayedText', 'quotedText'):
            value = quote.get(name)
            if not isinstance(value, str) or not value.strip():
                continue
            claim = quote.get(name + 'SHA256')
            if claim is not None and claim != sha(value.encode('utf8')):
                continue
            normalized = normalize_lines(value)
            if normalized in text:
                witnesses.append({'pointer': base + [name], 'textSHA256': sha(normalized.encode('utf8'))})
        if witnesses and len(positions) == 1:
            for name in ('verseKey', 'reference', 'references', 'verses', 'displayedSourceNote', 'label'):
                keys.extend(key for key in _verse_keys(quote.get(name), quran) if key not in keys)

        def verse_records(value, path):
            if isinstance(value, dict):
                translation = value.get('translation')
                if isinstance(translation, str) and normalize_lines(translation).strip() and normalize_lines(translation) in text:
                    local = _verse_keys(value.get('reference', value.get('verseKey')), quran)
                    if type(value.get('sura')) is int and type(value.get('aya')) is int:
                        local.extend(_verse_keys(f"{value['sura']}:{value['aya']}", quran))
                    if local:
                        yield local, {'pointer': path + ['translation'], 'textSHA256': sha(normalize_lines(translation).encode('utf8'))}
                else:
                    for name, child in value.items():
                        if isinstance(child, (list, dict)):
                            yield from verse_records(child, path + [name])
            elif isinstance(value, list):
                for offset, child in enumerate(value):
                    yield from verse_records(child, path + [offset])

        for name in ('exactText', 'record', 'records', 'sourceRecords', 'currentRecords'):
            for local, witness in verse_records(quote.get(name), base + [name]):
                keys.extend(key for key in local if key not in keys)
                witnesses.append(witness)
        if keys:
            found.append({'sourcePointer': base, 'originalBlock': field['originalBlock'],
                          'verseKeys': keys, 'exactQuotationWitnesses': witnesses})
    return found


def reference_plan(root, row, record):
    """Count exact supplied quotation/reference associations, never infer a grade."""
    original = [field for field in record['displayPlan']['fields']
                if field['purpose'] in {'reader-block', 'source-reference'}]
    quran = read(root, 'books/assets/quran-arabic.json')
    payload = read(root, row['json'])
    readings = []
    orphaned = 0
    for index, field in enumerate(original):
        if field['purpose'] == 'source-reference':
            if index == 0 or original[index - 1].get('sourceKind') == 'heading':
                orphaned += 1
            continue
        if field.get('sourceKind') not in {'ayah', 'hadith'}:
            continue
        next_field = original[index + 1] if index + 1 < len(original) else None
        following = next_field if next_field and next_field['purpose'] == 'source-reference' else None
        text = _field_text(root, field)
        support = text + ('\n' + _field_text(root, following) if following else '')
        keys, review_bindings, named_bindings, parent = [], [], [], None
        if field['sourceKind'] == 'ayah':
            keys = _verse_keys(support, quran)
            if not keys and next_field and next_field.get('sourceKind') == 'paragraph':
                locator = _field_text(root, next_field)
                # The app sometimes stores a standalone chapter/verse caption as
                # an ordinary paragraph. Preserve its kind, but use its locator.
                if len(locator) <= 120 and '\n' not in locator and len(_verse_keys(locator, quran)) == 1:
                    keys = _verse_keys(locator, quran)
                    following = next_field
            review_bindings = _review_verse_bindings(payload, field, text, quran)
            for item in review_bindings:
                keys.extend(key for key in item['verseKeys'] if key not in keys)
            if not keys:
                caption = following
                if caption is None and next_field and next_field.get('sourceKind') == 'paragraph':
                    candidate = _field_text(root, next_field)
                    if len(candidate) <= 120 and '\n' not in candidate:
                        caption = next_field
                named_bindings = _named_verse_bindings(root, row, [field, caption], quran)
                for item in named_bindings:
                    keys.extend(key for key in item['verseKeys'] if key not in keys)
                    if caption is not None and item['sourcePointer'] == caption['pointer']:
                        following = caption
            if not keys and index > 0 and original[index - 1].get('sourceKind') == 'ayah':
                previous = original[index - 1]
                cited = next((item for item in readings if item['originalBlock'] == previous['originalBlock']), None)
                previous_text = _field_text(root, previous)
                matches = [line.strip() for line in previous_text.splitlines()
                           if len(line.strip()) >= 24 and line.strip() in text and not _verse_keys(line, quran)]
                if cited and cited['bound'] and len(matches) == 1:
                    # The complete repeated quotation is already cited in its
                    # immediately preceding parent passage. Retain that supplied
                    # parent range; do not invent an individual verse number.
                    keys = list(cited['verseKeys'])
                    parent = {'sourcePointer': previous['pointer'], 'sourceTextSHA256': previous['textSHA256'],
                              'exactRepeatedLineSHA256': sha(matches[0].encode('utf8')),
                              'referenceScope': 'existing-cited-parent-passage'}
        bound = bool(keys) if field['sourceKind'] == 'ayah' else following is not None
        readings.append({'originalBlock': field['originalBlock'], 'sourceKind': field['sourceKind'],
                         'sourcePointer': field['pointer'], 'sourceTextSHA256': field['textSHA256'],
                         'suppliedReferencePointer': following['pointer'] if following else None,
                         'verseKeys': keys, 'existingReviewBindings': review_bindings,
                         'exactNativeNameBindings': named_bindings,
                         'exactRepeatedParentQuotation': parent, 'bound': bound})
    return {'method': 'Exact supplied numeric or pinned native-name verse locators, original paragraph-and-quotation review bindings, immediately following source captions, and exact complete-line repeats from the immediately preceding cited passage; no invented citation or authentication.',
            'quotations': readings,
            'readiness': {'unboundQuranSegments': sum(not item['bound'] and item['sourceKind'] == 'ayah' for item in readings),
                          'unboundHadithSegments': sum(not item['bound'] and item['sourceKind'] == 'hadith' for item in readings),
                          'unboundScholarSegments': 0,
                          'unresolvedSourceReferenceCount': orphaned}}


def verify_preservation(unit, record):
    """A correct reader hash alone cannot excuse omitted source fields."""
    if (unit.get('provenance', {}).get('sourceEvidenceOnlyFields', [])
            != record['displayPlan'].get('sourceEvidenceOnlyFields', [])):
        raise ValueError('Seerah raw-source evidence disposition changed or disappeared')
    actual = unit.get('provenance', {}).get('sourceDisplayFields', [])
    expected = record['displayPlan']['fields']
    if len(actual) != len(expected):
        raise ValueError('Seerah display ledger omits original source fields')
    for field, output in zip(expected, actual):
        if {key: value for key, value in output.items() if key not in {'outputSection', 'blockIndex'}} != field:
            raise ValueError('Seerah display ledger differs from the exact source plan')
        block = unit['sections'][output['outputSection']]['blocks'][output['blockIndex']]
        if sha(block['text'].encode('utf8')) != field['textSHA256']:
            raise ValueError('Seerah reader, question, note or source qualification was changed or omitted')


def normalize(root, catalog, row, record, evidence):
    from build_books import check_unit
    from source_literal_text import SCHEMA as LITERAL_SCHEMA
    root = Path(root).resolve()
    files = validate_record(root, record, row, catalog)
    source_map = {item['path']: item for item in files}
    title = _field_text(root, record['displayPlan']['title'])
    native_text(title, row['language'])
    references = reference_plan(root, row, record)
    by_position = {item['originalBlock']: item for item in references['quotations']}
    sections, ledger = [], []
    section_order = ('reader', 'questions', 'readerNotes', 'glossary', 'source-context')
    destinations = {}
    for name in section_order:
        if not any(field['section'] == name for field in record['displayPlan']['fields']):
            continue
        destinations[name] = len(sections)
        section = {'blocks': []}
        if name == 'source-context':
            section.update(heading=locale(row['language'])['creditsTitle'], sourceOnlyContext=True)
        sections.append(section)
    for field in record['displayPlan']['fields']:
        text = _field_text(root, field)
        if sha(text.encode('utf8')) != field['textSHA256']:
            raise ValueError('Original Seerah field changed during normalization')
        start, end = field.get('range', (0, len(text)))
        proof = {'schema': LITERAL_SCHEMA, 'language': row['language'], 'materialId': str(row['id']),
                 'source': deepcopy(source_map[field['sourcePath']]), 'inventory': deepcopy(evidence),
                 'pointer': deepcopy(field['pointer']), 'start': start, 'end': end,
                 'displayMode': field['displayMode'], 'textSHA256': sha(text.encode('utf8'))}
        block = {'kind': field['kind'], 'text': text, 'role': field['role'], 'sourceLiteralProof': proof}
        citation = by_position.get(field.get('originalBlock')) if field['purpose'] == 'reader-block' else None
        if citation and citation['sourceKind'] == 'ayah' and citation['verseKeys']:
            block['spans'] = [{'text': text, 'role': 'quran', 'verseKeys': citation['verseKeys'],
                               'explicitSourceReferencePlaced': True}]
        if field['section'] == 'source-context':
            block['sourceOnlyContext'] = True
        section_index = destinations[field['section']]
        blocks = sections[section_index]['blocks']
        ledger.append({**deepcopy(field), 'outputSection': section_index, 'blockIndex': len(blocks)})
        blocks.append(block)
    fields = record['displayPlan']['fields']
    reference_count = sum(field['purpose'] == 'source-reference' for field in fields)
    paragraph_count = sum(field['purpose'] == 'reader-block' for field in fields)
    qualification_count = len(fields) - reference_count - paragraph_count
    inputs = {item['path']: item['sha256'] for item in files + [evidence]}
    texts = ''.join(block['text'] for section in sections for block in section['blocks'])
    unit = {'schema': 'iman-book-unit-v1', 'id': str(row['id']), 'language': row['language'],
            'collection': 'seerah', 'edition': EDITION, 'chapter': row['chapter'], 'order': row['chapter'],
            'ordering': {'kind': 'global-sequence', 'sequence': row['chapter']},
            'title': title, 'complete': True, 'reviewGate': 'published-current',
            'sourceHashes': [source_map[row['json']]['sha256']],
            'inputBindings': [{'path': path, 'sha256': digest} for path, digest in sorted(inputs.items())],
            'catalogBindings': [{'collection': 'seerah', 'language': row['language'], 'id': row['id']}],
            'sections': sections, 'readerTextSHA256': sha(texts.encode('utf8')),
            'referenceReadiness': references['readiness'],
            'sourceReferencePreservation': {'schema': 'iman-source-reference-preservation-v1',
                'auditMode': 'literal-source-and-qualification-fidelity',
                'sourceReferences': reference_count, 'preservedReferences': reference_count,
                'sourceQualifications': qualification_count, 'preservedQualifications': qualification_count,
                'sourceParagraphs': paragraph_count, 'preservedParagraphs': paragraph_count,
                'lostReferences': 0, 'lostQualifications': 0, 'lostParagraphs': 0},
            'provenance': {'adapter': ADAPTER, 'sourceRecordSHA256': sha(canonical(record)),
                'sourceDisplayFields': ledger, 'referenceAssociations': references,
                'sourceStatus': record['existingPublication']['sourceStatus'],
                'reviewQualification': record['qualification'], 'sourceEdition': EDITION,
                'questionReviewEvidence': deepcopy(record['questionReviewEvidence']),
                **({'sourceEvidenceOnlyFields': deepcopy(record['displayPlan']['sourceEvidenceOnlyFields'])}
                   if record['displayPlan'].get('sourceEvidenceOnlyFields') else {}),
                'sourceContextDisposition': record['displayPlan']['sourceContextDisposition'],
                'sourceApprovalCreated': False, 'humanCertification': False}}
    verify_preservation(unit, record)
    check_unit(unit, {'language': row['language'], 'collection': 'seerah', 'id': str(row['id'])}, root=root)
    return unit


def generate(root, catalog, declaration, *, excluded_catalog_keys=()):
    if (declaration.get('collection'), declaration.get('adapter'), declaration.get('edition')) != ('seerah', ADAPTER, EDITION):
        raise ValueError('Current reviewed Seerah adapter needs its distinct lecture-sequence declaration')
    excluded = set(excluded_catalog_keys)
    result = []
    for record, evidence in records(root, declaration):
        identity = ('seerah', record['language'], str(record['id']))
        if identity in excluded:
            continue
        rows = [row for row in catalog['entries']
                if (row.get('collection'), row.get('language'), str(row.get('id'))) == identity]
        if len(rows) != 1:
            raise ValueError('Current reviewed Seerah chapter disappeared or is ambiguous')
        result.append(normalize(root, catalog, rows[0], record, evidence))
    return result
