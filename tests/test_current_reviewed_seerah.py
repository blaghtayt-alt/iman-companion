"""Preserve the exact published lecture-sequence readers and their review limits.

The corpus fixture copies the installed source publications into a temporary
root. Negative cases change that fixture only; no source approval is created.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))

import current_reviewed_seerah as current
from build_books import check_unit
from source_literal_text import normalize_lines


EXPECTED_CHAPTERS = {'de': 9, 'es': 10, 'fa': 10, 'fil': 2, 'hi': 10,
                     'ja': 2, 'ru': 10, 'th': 2, 'uz': 2, 'vi': 2, 'zh-CN': 9}
HELD_LANGUAGES = {'de', 'es', 'fa', 'hi', 'ru', 'zh-CN'}
LECTURE_CREDIT = ('Source: Ahmad al-Sayyid’s Seerah lecture sequence; Arabic summaries '
                  'prepared for Iman Companion. Credited quotations keep their publishers’ terms.')


def output_blocks(unit):
    return [block for section in unit['sections'] for block in section['blocks']]


def at_pointer(value, pointer):
    for part in pointer:
        value = value[part]
    return value


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CurrentReviewedSeerah(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.inventory = json.loads((ROOT / current.PROJECTION).read_text(encoding='utf8'))
        cls.records = {(row['language'], row['id']): row for row in cls.inventory['records']}
        paths = {current.PROJECTION, 'materials/catalog.json', 'materials/translation-status.json',
                 'books/reviewed-books.json', 'books/assets/quran-arabic.json'}
        for record in cls.records.values():
            paths.update(item['path'] for item in record['sourceFiles'] + record['sourceConditions'])
        for path in paths:
            target = cls.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        cls.catalog = json.loads((cls.root / 'materials/catalog.json').read_text(encoding='utf8'))
        cls.declarations = json.loads((cls.root / 'books/reviewed-books.json').read_text(encoding='utf8'))
        cls.scopes = {row['language']: row for row in cls.declarations['books']
                      if row.get('collection') == 'seerah' and row.get('edition') == current.EDITION}
        cls.evidence = current.binding(cls.root, current.PROJECTION)
        cls.units = {}
        cls.scope_units = {}
        for language in sorted(EXPECTED_CHAPTERS):
            units = current.generate(cls.root, cls.catalog, cls.scopes[language])
            cls.scope_units[language] = units
            cls.units.update(((unit['language'], unit['id']), unit) for unit in units)

    def payload(self, identity):
        path = self.records[identity]['catalogEntry']['json']
        return json.loads((self.root / path).read_text(encoding='utf8'))

    @contextmanager
    def changed_json(self, path, change):
        target = self.root / path
        original = target.read_bytes()
        value = json.loads(original)
        change(value)
        target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
        try:
            yield value
        finally:
            target.write_bytes(original)

    def test_exact_68_chapters_in_distinct_edition(self):
        expected = {(language, str(chapter)) for language, count in EXPECTED_CHAPTERS.items()
                    for chapter in range(1, count + 1)}
        self.assertEqual(len(expected), 68)
        self.assertEqual(set(self.records), expected)
        self.assertEqual(set(self.units), expected)
        self.assertFalse(self.inventory['sourceApprovalCreated'])
        self.assertFalse(self.inventory['humanCertification'])
        self.assertEqual(current.inventory(self.root, self.catalog, self.inventory['sourceCommit']),
                         self.inventory)
        for record in self.records.values():
            self.assertEqual(record['edition'], 'current-lecture-sequence')
            self.assertNotIn('edition', record['existingPublication']['catalogEntryBeforeEditionClassification'])
            self.assertFalse(record['existingPublication']['humanCertification'])

    def test_decimal_identities_and_canonical_chapter_order(self):
        for language, count in EXPECTED_CHAPTERS.items():
            with self.subTest(language=language):
                units = self.scope_units[language]
                self.assertEqual([unit['id'] for unit in units], [str(n) for n in range(1, count + 1)])
                self.assertEqual([unit['chapter'] for unit in units], list(range(1, count + 1)))
                self.assertEqual([unit['order'] for unit in units], list(range(1, count + 1)))
                self.assertEqual([unit['ordering'] for unit in units],
                                 [{'kind': 'global-sequence', 'sequence': n} for n in range(1, count + 1)])

    def test_all_reader_blocks_and_source_only_notes_keep_text_order_and_roles(self):
        body_count = source_only_count = 0
        for identity, unit in self.units.items():
            source = self.payload(identity)
            lecture = identity[0] in HELD_LANGUAGES
            content = source['content'] if lecture else source
            expected = [(index if lecture else block['index'], block, False)
                        for index, block in enumerate(content['blocks'])]
            source_only = source.get('sourceProvenance', {}).get('sourceOnlyBlocks', [])
            expected.extend((block['index'], block, True) for block in source_only)
            expected.sort(key=lambda item: item[0])
            actual = []
            for block in output_blocks(unit):
                pointer = block['sourceLiteralProof']['pointer']
                reader = (pointer[:2] == ['content', 'blocks'] if lecture else pointer[:1] == ['blocks'])
                extra = pointer[:2] == ['sourceProvenance', 'sourceOnlyBlocks']
                if (reader or extra) and pointer[-1] == 'text':
                    actual.append((block['text'], block['kind'], block['role']))
            wanted = []
            for _, block, source_note in expected:
                kind = 'note' if source_note else {'source': 'note', 'ayah': 'translation', 'hadith': 'quotation'}.get(block['kind'], block['kind'])
                role = 'note' if source_note else {'source': 'note', 'ayah': 'quran', 'hadith': 'hadith', 'heading': 'heading'}.get(block['kind'], 'body')
                wanted.append((normalize_lines(block['text']), kind, role))
            with self.subTest(identity=identity):
                self.assertEqual(actual, wanted)
            body_count += len(content['blocks'])
            source_only_count += len(source_only)
        self.assertEqual(body_count, 3845)
        self.assertEqual(source_only_count, 36)

    def test_every_question_and_all_three_choices_are_preserved(self):
        questions = choices = 0
        for identity, unit in self.units.items():
            source = self.payload(identity)
            expected = []
            for question in source['questions']:
                value = question['translation'] if identity[0] in HELD_LANGUAGES else question
                expected.append((normalize_lines(value['question']), 'heading'))
                expected.extend((normalize_lines(option), 'list-item') for option in value['options'])
                questions += 1
                choices += len(value['options'])
            actual = [(block['text'], block['kind']) for block in output_blocks(unit)
                      if block['sourceLiteralProof']['pointer'][:1] == ['questions']]
            with self.subTest(identity=identity):
                self.assertEqual(actual, expected)
        self.assertEqual(questions, 340)
        self.assertEqual(choices, 1020)

    def test_reader_notes_and_glossary_definitions_are_complete(self):
        notes = glossary = 0
        for identity, unit in self.units.items():
            source = self.payload(identity)
            for name, keys in [('readerNotes', ('id', 'title', 'marker', 'text')),
                               ('glossary', ('term', 'meaning'))]:
                expected = [normalize_lines(item[key]) for item in source.get(name, [])
                            for key in keys if key in item]
                actual = [block['text'] for block in output_blocks(unit)
                          if block['sourceLiteralProof']['pointer'][:1] == [name]]
                with self.subTest(identity=identity, field=name):
                    self.assertEqual(actual, expected)
            notes += len(source.get('readerNotes', []))
            glossary += len(source.get('glossary', []))
        self.assertEqual(notes, 19)
        self.assertEqual(glossary, 24)

    def test_original_publication_notice_and_source_credit_remain_visible(self):
        for identity, unit in self.units.items():
            source = self.payload(identity)
            text = [block['text'] for block in output_blocks(unit)]
            with self.subTest(identity=identity):
                if identity[0] in HELD_LANGUAGES:
                    self.assertIn(normalize_lines(source['notice']), text)
                    self.assertIn(LECTURE_CREDIT, text)
                else:
                    self.assertIn(normalize_lines(source['status']), text)
                    self.assertIn(normalize_lines(source['sourceCredit']), text)
                self.assertFalse(unit['provenance']['sourceApprovalCreated'])
                self.assertFalse(unit['provenance']['humanCertification'])
                self.assertIn('human verification', unit['provenance']['reviewQualification'])

    def test_channel_credit_names_urls_and_relationships_survive(self):
        found = []
        def leaves(value):
            if isinstance(value, str):
                yield normalize_lines(value)
            elif isinstance(value, dict):
                for child in value.values():
                    yield from leaves(child)
            elif isinstance(value, list):
                for child in value:
                    yield from leaves(child)
        for identity, unit in self.units.items():
            source = self.payload(identity)
            if 'channelCredit' not in source:
                continue
            found.append(identity)
            printed = '\n'.join(block['text'] for block in output_blocks(unit))
            for text in leaves(source['channelCredit']):
                self.assertIn(text, printed, identity)
        self.assertEqual(set(found), {('vi', '1'), ('vi', '2'), ('th', '1')})

    def test_published_edition_reviewer_credits_are_retained(self):
        expected = [
            (('ja', '2'), ['sourceProvenance', 'sourceConditionsAndVersions', 'hadithIslamHouse', 'reviewer']),
            (('ja', '2'), ['sourceProvenance', 'selectedTargetParentsAndNotes', 'hadith', 0, 'reviewer']),
            (('vi', '2'), ['sourceProvenance', 'sourceCredit', 'H3', 'reviewer']),
            (('vi', '2'), ['sourceProvenance', 'sourceCredit', 'H3', 'sourceUseInferenceAndReservations',
                           'actualNamedEdition', 'reviewer']),
        ]
        for identity, pointer in expected:
            credit = at_pointer(self.payload(identity), pointer)
            printed = '\n'.join(block['text'] for block in output_blocks(self.units[identity]))
            self.assertIn(credit, printed, (identity, pointer))

    def test_public_source_metadata_survives_even_when_embedded_in_reader_text(self):
        examples = [
            (('de', '5'), ['review', 'quoteProvenance', 0, 'metadata', 'catalog', 'description']),
            (('de', '5'), ['review', 'quoteProvenance', 0, 'metadata', 'sourceURL']),
            (('de', '2'), ['review', 'quoteProvenance', 0, 'label']),
        ]
        for identity, pointer in examples:
            original = normalize_lines(at_pointer(self.payload(identity), pointer))
            unit = self.units[identity]
            reader = '\n'.join(block['text'] for section in unit['sections']
                               if not section.get('sourceOnlyContext') for block in section['blocks'])
            context = '\n'.join(block['text'] for section in unit['sections']
                                if section.get('sourceOnlyContext') for block in section['blocks'])
            with self.subTest(identity=identity, pointer=pointer):
                self.assertIn(original, reader)
                self.assertIn(original, context)

    def test_shared_reuse_grant_keeps_its_antecedent_once_per_language(self):
        original = normalize_lines((self.root / 'materials/REUSE.md').read_text(encoding='utf8'))
        grant = next(paragraph for paragraph in original.split('\n\n')
                     if paragraph.startswith('My original editorial contributions'))
        for language, units in self.scope_units.items():
            first = [block['text'] for block in output_blocks(units[0])]
            self.assertEqual(first.count(grant), 1, language)
            for later in units[1:]:
                self.assertNotIn(grant, [block['text'] for block in output_blocks(later)])

    def test_existing_question_review_hashes_and_all_unresolved_bindings_remain_explicit(self):
        verified = unresolved = 0
        for identity, record in self.records.items():
            evidence = record['questionReviewEvidence']
            self.assertEqual(self.units[identity]['provenance']['questionReviewEvidence'], evidence)
            if identity[0] not in HELD_LANGUAGES:
                continue
            source = self.payload(identity)
            if identity[1] == '1':
                self.assertTrue(evidence['unresolvedReviewBinding'])
                self.assertFalse(evidence['normalizationEquivalenceEstablished'])
                self.assertEqual(evidence['recordedFinalQuestionsSha256'], source['review']['finalQuestionsSha256'])
            for question in evidence['questions']:
                if question['status'] == 'exact-existing-review-hash-verified':
                    verified += 1
                else:
                    self.assertEqual(question['status'], 'unreconciled-existing-review-binding')
                    unresolved += 1
        self.assertEqual(verified, 280)
        self.assertEqual(unresolved, 10)

    def test_twelve_recovered_question_objects_match_the_original_qualified_approvals(self):
        matches = 0
        for language in ('hi', 'ru', 'es', 'fa'):
            source = self.payload((language, '1'))
            evidence = self.records[language, '1']['questionReviewEvidence']
            questions = {question['id']: question for question in source['questions']}
            for question in evidence['questions']:
                for binding in question.get('matchingExistingQuestionObjectReviewBindings', []):
                    original = questions[question['id']]
                    flat = {'id': original['id'], **original['translation']}
                    digest = sha(json.dumps(flat, ensure_ascii=False, sort_keys=True).encode('utf8'))
                    approved = at_pointer(source, binding['hashPointer'][:-1])
                    self.assertEqual(at_pointer(source, binding['hashPointer']), digest)
                    self.assertEqual(binding['currentProjectionSHA256'], digest)
                    self.assertEqual(binding['projection'], 'existing-question-id-plus-translation-fields')
                    self.assertEqual((approved['language'], approved['id']), (language, question['id']))
                    self.assertEqual(approved['decision'], 'approved-independent-ai-reviewed')
                    self.assertTrue(approved['answerOrderVerified'])
                    self.assertFalse(approved['humanCertification'])
                    matches += 1
        self.assertEqual(matches, 12)

    def test_complete_units_pass_the_existing_validator(self):
        for identity, unit in self.units.items():
            with self.subTest(identity=identity):
                check_unit(unit, {'language': identity[0], 'collection': 'seerah', 'id': identity[1]}, root=self.root)
                current.verify_preservation(unit, self.records[identity])
                for kind in ('Paragraphs', 'References', 'Qualifications'):
                    self.assertEqual(unit['sourceReferencePreservation']['lost' + kind], 0)

    def test_exact_original_reference_witnesses_keep_their_proper_scope(self):
        def reference(language, chapter, position):
            unit = self.units[language, str(chapter)]
            return next(item for item in unit['provenance']['referenceAssociations']['quotations']
                        if item['originalBlock'] == position)
        german = reference('de', 3, 4)
        self.assertEqual(german['verseKeys'], ['5:50'])
        self.assertTrue(german['existingReviewBindings'])
        hindi = reference('hi', 5, 9)
        self.assertEqual(hindi['verseKeys'], ['74:2'])
        self.assertTrue(hindi['existingReviewBindings'])
        japanese_caption = reference('ja', 2, 17)
        self.assertEqual(japanese_caption['verseKeys'], ['93:6'])
        self.assertIsNotNone(japanese_caption['suppliedReferencePointer'])
        repeated = reference('ja', 1, 23)
        self.assertEqual(repeated['verseKeys'], ['105:1-5'])
        self.assertEqual(repeated['exactRepeatedParentQuotation']['referenceScope'],
                         'existing-cited-parent-passage')
        persian = reference('fa', 3, 20)
        self.assertTrue(persian['bound'])
        self.assertEqual(persian['verseKeys'], ['2:199'])
        totals = {key: sum(unit['referenceReadiness'][key] for unit in self.units.values())
                  for key in ('unboundQuranSegments', 'unboundHadithSegments',
                              'unboundScholarSegments', 'unresolvedSourceReferenceCount')}
        self.assertEqual(totals, {'unboundQuranSegments': 0, 'unboundHadithSegments': 0,
                                 'unboundScholarSegments': 0, 'unresolvedSourceReferenceCount': 0})

    def test_native_surah_name_table_is_an_immutable_source_binding(self):
        record = self.records['fa', '3']
        path = 'books/assets/surah-names.json'
        binding = current.binding(self.root, path)
        self.assertIn(binding, record['sourceConditions'])
        self.assertIn(binding, self.units['fa', '3']['inputBindings'])
        quotation = next(item for item in self.units['fa', '3']['provenance']['referenceAssociations']['quotations']
                         if item['originalBlock'] == 20)
        self.assertEqual(len(quotation['exactNativeNameBindings']), 1)
        evidence = quotation['exactNativeNameBindings'][0]
        self.assertEqual(evidence['sourcePointer'], ['content', 'blocks', 21, 'text'])
        self.assertEqual(evidence['nameTable'], binding)
        self.assertEqual(evidence['namePointer'], ['fa', 1])
        self.assertEqual(evidence['exactNativeName'], 'بقره')
        self.assertEqual(evidence['exactLocator'], 'بقره: ۱۹۹')
        original = normalize_lines(self.payload(('fa', '3'))['content']['blocks'][21]['text'])
        start, end = evidence['locatorRange']
        self.assertEqual(original[start:end], evidence['exactLocator'])
        self.assertEqual(evidence['sourceTextSHA256'], sha(original.encode('utf8')))
        with self.changed_json(path, lambda names: names['fa'].__setitem__(1, 'Changed name')):
            with self.assertRaises(ValueError):
                current.normalize(self.root, self.catalog, record['catalogEntry'], record, self.evidence)

    def test_source_text_mutation_is_rejected(self):
        record = self.records['ja', '1']
        with self.changed_json(record['catalogEntry']['json'],
                               lambda source: source['blocks'][0].update(text='Changed source text')):
            with self.assertRaises(ValueError):
                current.normalize(self.root, self.catalog, record['catalogEntry'], record, self.evidence)

    def test_source_question_omission_is_rejected(self):
        record = self.records['hi', '1']
        with self.changed_json(record['catalogEntry']['json'], lambda source: source['questions'].pop()):
            with self.assertRaises(ValueError):
                current.normalize(self.root, self.catalog, record['catalogEntry'], record, self.evidence)

    def test_question_cannot_be_removed_by_recomputing_the_output_hash(self):
        unit = deepcopy(self.units['ja', '1'])
        for section in unit['sections']:
            if section['blocks'][0]['sourceLiteralProof']['pointer'][:1] == ['questions']:
                del section['blocks'][0]
                break
        unit['readerTextSHA256'] = sha(''.join(block['text'] for block in output_blocks(unit)).encode('utf8'))
        with self.assertRaises(ValueError):
            current.verify_preservation(unit, self.records['ja', '1'])

    def test_source_qualification_cannot_be_deleted_from_the_display_plan(self):
        for purpose in ('review-qualification', 'source-credit', 'shared-source-companion'):
            record = deepcopy(self.records['ja', '1'])
            position = next(n for n, field in enumerate(record['displayPlan']['fields'])
                            if field['purpose'] == purpose)
            del record['displayPlan']['fields'][position]
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                current.validate_record(self.root, record, record['catalogEntry'], self.catalog)

    def test_shared_public_source_conditions_are_hash_bound(self):
        path = self.root / 'materials/REUSE.md'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\nChanged source condition.\n')
            record = self.records['ja', '1']
            with self.assertRaises(ValueError):
                current.validate_record(self.root, record, record['catalogEntry'], self.catalog)
        finally:
            path.write_bytes(original)

    def test_all_six_question_review_holds_are_required(self):
        for language in sorted(HELD_LANGUAGES):
            scope = self.scopes[language]
            self.assertTrue(scope['automaticBuild'])
            self.assertFalse(scope['automaticRelease'])
            self.assertIn('question', scope['releaseHold'].lower())
            for change in ({'automaticRelease': True}, {'releaseHold': ''}):
                def apply(value):
                    row = next(item for item in value['books']
                               if item['language'] == language and item['collection'] == 'seerah')
                    row.update(change)
                with self.changed_json('books/reviewed-books.json', apply):
                    with self.subTest(language=language, change=change), self.assertRaisesRegex(ValueError, 'release hold'):
                        current.generate(self.root, self.catalog, scope)

    def test_warm_literal_cache_cannot_bypass_a_removed_question_review_hold(self):
        unit = self.units['de', '2']
        identity = {'language': 'de', 'collection': 'seerah', 'id': '2'}
        # The first validation deliberately fills the shared source-literal cache.
        check_unit(unit, identity, root=self.root)
        def remove_hold(value):
            scope = next(row for row in value['books']
                         if row['language'] == 'de' and row['collection'] == 'seerah')
            scope.update(automaticRelease=True, releaseHold='')
        with self.changed_json('books/reviewed-books.json', remove_hold):
            # No source, projection, or normalized reader bytes have changed.
            with self.assertRaisesRegex(ValueError, 'release hold'):
                check_unit(unit, identity, root=self.root)

    def test_first_pair_scopes_retain_word_and_visual_gates(self):
        for language in set(EXPECTED_CHAPTERS) - HELD_LANGUAGES:
            scope = self.scopes[language]
            self.assertTrue(scope['automaticBuild'])
            self.assertTrue(scope['automaticRelease'])
            self.assertTrue(scope['requireActualWordLayout'])
            self.assertTrue(scope['requireFinalVisualAcceptance'])

    def test_arabic_new_adult_edition_cannot_enter_this_adapter(self):
        declaration = next(row for row in self.declarations['books']
                           if row['language'] == 'ar' and row['collection'] == 'seerah')
        with self.assertRaisesRegex(ValueError, 'distinct lecture-sequence'):
            current.generate(self.root, self.catalog, declaration)
        record = self.records['ja', '1']
        row = deepcopy(record['catalogEntry'])
        row['edition'] = 'new-adult'
        with self.assertRaises(ValueError):
            current.validate_record(self.root, record, row, self.catalog)

    def test_padded_or_out_of_scope_chapter_identity_is_rejected(self):
        record = self.records['ja', '1']
        for changes in ({'id': '01'}, {'id': '3', 'chapter': 3}, {'language': 'en'}):
            row = {**record['catalogEntry'], **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                current.validate_record(self.root, record, row, self.catalog)

    def test_duplicate_projection_record_is_rejected(self):
        def duplicate(value):
            value['records'].append(deepcopy(self.records['ja', '1']))
        with self.changed_json(current.PROJECTION, duplicate):
            scope = deepcopy(self.scopes['ja'])
            scope['sourceReviewBindings'] = [current.binding(self.root, current.PROJECTION)]
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                current.records(self.root, scope)

    def test_explicitly_excluded_catalog_key_is_not_duplicated(self):
        units = current.generate(self.root, self.catalog, self.scopes['ja'],
                                 excluded_catalog_keys={('seerah', 'ja', '1')})
        self.assertEqual([unit['id'] for unit in units], ['2'])


if __name__ == '__main__':
    unittest.main()
