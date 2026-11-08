"""Real current-reader regressions for the omitted first Hadith translations.

These tests exercise the checked-in reader bytes and source/review bindings.
They never publish, translate, approve, or alter the repository's source files.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))

import current_hadith_first as first
from book_edition_scope import POLICY
from source_literal_text import check_text, normalize_lines


class CurrentFirstHadith(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.inventory = json.loads((ROOT / first.PROJECTION).read_bytes())
        cls.by_language = {item['language']: item for item in cls.inventory['records']}
        paths = {first.PROJECTION, 'materials/catalog.json', 'materials/translation-status.json'}
        for record in cls.inventory['records']:
            paths.update(item['path'] for item in record['sourceFiles'] + record['sourceConditions'])
        for exclusion in cls.inventory['excludedCurrentRows']:
            paths.update(item['path'] for item in exclusion['sourceFiles'])
        for path in paths:
            destination = cls.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, destination)
        cls.catalog = json.loads((cls.root / 'materials/catalog.json').read_bytes())
        cls.binding = first._binding(cls.root, first.PROJECTION)
        cls.declarations = {'schema': 'iman-reviewed-books-v1', 'books': [
            {'language': lang, 'collection': 'hadith', 'state': 'reviewed-current',
             'automaticBuild': True, 'scopePolicy': POLICY,
             'sourceReviewBindings': [cls.binding]}
            for lang in first.SUPPORTED]}
        (cls.root / 'books/reviewed-books.json').write_text(
            json.dumps(cls.declarations, ensure_ascii=False), encoding='utf8')
        cls.units = {}
        for language, record in cls.by_language.items():
            cls.units[language] = first.normalize(
                cls.root, cls.catalog, record['catalogEntry'], record, cls.binding)

    def payload(self, language):
        record = self.by_language[language]
        return json.loads((self.root / record['catalogEntry']['json']).read_bytes())

    def reader(self, language):
        return self.payload(language)[first.SPEC[language][0]]

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

    def test_only_current_reviewed_first_readers_are_selected(self):
        self.assertEqual(set(self.units), set(first.SUPPORTED))
        self.assertEqual(len(self.units), 11)
        self.assertNotIn('ja', self.units)
        self.assertNotIn('fr', self.units)
        exclusion, = self.inventory['excludedCurrentRows']
        self.assertEqual(exclusion['language'], 'fr')
        self.assertIn('PENDING_ACTUAL_DISTINCT_FINAL', exclusion['reviewStatus'])

    def test_each_reader_preserves_all_49_commentary_paragraphs_in_order(self):
        # Read the original schema fields directly, independently of displayPlan.
        for language, unit in self.units.items():
            with self.subTest(language=language):
                reader = self.reader(language)
                source = reader[first.SPEC[language][1]]
                self.assertEqual(len(source), 49)
                actual = [block['text'] for block in unit['sections'][0]['blocks']]
                cursor = 0
                for paragraph in source:
                    text = normalize_lines(paragraph['text'])
                    position = actual.index(text, cursor)
                    self.assertEqual(actual.count(text), 1)
                    cursor = position + 1
                self.assertEqual(unit['title'], reader['title'])
                self.assertEqual(unit['sourceLessonNumber'], 1)
                self.assertEqual(unit['order'], 1001)

    def test_complete_original_main_narrations_are_preserved(self):
        paths = {'id': ['mainHadith', 'text'], 'ms': ['mainNarration'],
                 'pt-BR': ['mainNarration', 'text'], 'ur': ['main'],
                 'bn': ['main_text'], 'hi': ['main_text'], 'de': ['main'],
                 'ru': ['mainNarration', 'text'], 'es': ['mainNarration', 'text'],
                 'fa': ['mainNarration', 'text'], 'uz': ['main']}
        for language, path in paths.items():
            with self.subTest(language=language):
                source = normalize_lines(first.pointer(self.reader(language), path))
                blocks = [b['text'] for b in self.units[language]['sections'][0]['blocks']]
                self.assertEqual(blocks.count(source), 1)

    def test_every_required_note_body_survives_exactly(self):
        expected_counts = {'bn': 81, 'de': 19, 'es': 29, 'fa': 16, 'hi': 34,
                           'id': 26, 'ms': 0, 'pt-BR': 26, 'ru': 15, 'ur': 75, 'uz': 11}
        for language, unit in self.units.items():
            with self.subTest(language=language):
                reader = self.reader(language)
                notes = []
                for name in ('notes', 'readerNotes', 'readingNotes', 'reading_notes',
                             'requiredMeaningNotes', 'main_notes'):
                    notes.extend(reader.get(name, []))
                for paragraph in reader[first.SPEC[language][1]]:
                    notes.extend(paragraph.get('notes', []))
                self.assertEqual(len(notes), expected_counts[language])
                output = [b['text'] for section in unit['sections'] for b in section['blocks']]
                for note in notes:
                    self.assertIn(normalize_lines(note['text']), output)
                preservation = unit['sourceReferencePreservation']
                self.assertEqual(preservation['sourceQualifications'], len(notes))
                self.assertEqual(preservation['preservedQualifications'], len(notes))
                self.assertEqual(preservation['lostQualifications'], 0)

    def test_brazilian_reading_notes_are_not_skipped_by_legacy_note_field_names(self):
        notes = self.reader('pt-BR')['reading_notes']
        self.assertEqual(len(notes), 26)
        output = [b['text'] for b in self.units['pt-BR']['sections'][0]['blocks']]
        for note in notes:
            self.assertEqual(output.count(normalize_lines(note['text'])), 1)

    def test_bengali_explicit_main_and_section_note_anchors_both_survive(self):
        reader = self.reader('bn')
        note = next(n for n in reader['notes'] if n['id'] == 'BN:main:sin')
        self.assertEqual(note['sections'], ['main', 'S21'])
        output = [b['text'] for b in self.units['bn']['sections'][0]['blocks']]
        self.assertEqual(output.count(normalize_lines(note['text'])), 2)
        index = output.index(normalize_lines(reader['sections'][20]['text']))
        next_index = output.index(normalize_lines(reader['sections'][21]['text']))
        self.assertIn(normalize_lines(note['text']), output[index + 1:next_index])

    def test_uzbek_source_only_notes_are_exported_separately(self):
        reader = self.reader('uz')
        source_notes = [n for n in reader['notes'] if n.get('placement') == 'source-only parent context']
        self.assertEqual(len(source_notes), 10)
        unit = self.units['uz']
        self.assertEqual(len(unit['sections']), 2)
        self.assertTrue(unit['sections'][1]['sourceOnlyContext'])
        ordinary = [b['text'] for b in unit['sections'][0]['blocks']]
        appendix = [b['text'] for b in unit['sections'][1]['blocks']]
        for note in source_notes:
            self.assertNotIn(normalize_lines(note['text']), ordinary)
            self.assertIn(normalize_lines(note['text']), appendix)
        notice = next(n['text'] for n in reader['notes'] if n['id'] == 'UZ:qualified-hadith-notice')
        self.assertEqual(ordinary.count(normalize_lines(notice)), 1)
        self.assertIn(reader['originalQuranNotice'], appendix)
        self.assertTrue(any(b['path'].endswith('TERRA-CONSUMER-CONTRACT934.json')
                            for b in unit['inputBindings']))
        self.assertEqual(unit['provenance']['sourceOnlyNoteCount'], 10)

    def test_uzbek_all_public_companions_are_complete_in_detached_reader(self):
        record = self.by_language['uz']
        unit = self.units['uz']
        appendix = unit['sections'][1]['blocks']
        ledger = [item for item in unit['provenance']['sourceDisplayFields']
                  if item['outputSection'] == 'source-notes']
        actual_files = {item['sourcePath'] for item in ledger if item['pointer'] == ['$text']}
        self.assertEqual(actual_files, {first.UZ_SOURCE_DIRECTORY + name
                                        for name in first.UZ_PUBLIC_TEXT_FILES})
        for name in first.UZ_PUBLIC_TEXT_FILES:
            path = first.UZ_SOURCE_DIRECTORY + name
            source = normalize_lines((self.root / path).read_bytes().decode('utf8'))
            fields = [item for item in ledger if item['sourcePath'] == path]
            with self.subTest(companion=name):
                self.assertEqual(''.join(appendix[item['blockIndex']]['text'] for item in fields), source)
                cursor = 0
                for item in fields:
                    start, end = item['literalRange']
                    self.assertEqual(start, cursor)
                    self.assertEqual(appendix[item['blockIndex']]['text'], source[start:end])
                    cursor = end
                self.assertEqual(cursor, len(source))
        context = record['displayPlan']['sourceOnlyExportContext']
        self.assertEqual(context['readableCompanionCount'], 4)
        self.assertFalse(context['privateMaterialIncluded'])
        self.assertTrue(all(block['sourceOnlyContext'] for block in appendix))

    def test_uzbek_all_99_parents_metadata_and_ten_publisher_notes_are_preserved(self):
        reader = self.reader('uz')
        unit = self.units['uz']
        context = unit['provenance']['sourceOnlyExportContext']
        self.assertEqual(len(context['sourceParents']), 99)
        self.assertEqual(len(context['publisherNotes']), 10)
        for parent, mapping in zip(reader['sourceParents'], context['sourceParents']):
            with self.subTest(parent=parent['id']):
                self.assertEqual(mapping['parentId'], parent['id'])
                raw = (self.root / mapping['source']['path']).read_bytes().decode('utf8')
                start, end = mapping['rawCodePointRange']
                self.assertEqual(raw[start:end], parent['text'])
                self.assertIn(json.dumps(parent['metadata'], ensure_ascii=False, indent=2), raw)
                start, end = mapping['normalizedCodePointRange']
                self.assertEqual(normalize_lines(raw)[start:end], normalize_lines(parent['text']))
                self.assertEqual(mapping['sourceURL'], parent['sourceURL'])
        for mapping in context['publisherNotes']:
            note = first.pointer(self.payload('uz'), mapping['readerPointer'])
            raw = (self.root / mapping['source']['path']).read_bytes().decode('utf8')
            start, end = mapping['rawCodePointRange']
            self.assertEqual(raw[start:end], note)
        self.assertEqual(sum(parent['kind'] == 'Quran' for parent in reader['sourceParents']), 79)
        for parent in reader['sourceParents'][:79]:
            self.assertEqual(parent['metadata']['sourceRecord']['footnotes'], '')
        audit = unit['sourceContextPreservation']
        self.assertEqual(audit['preservedParents'], 99)
        self.assertEqual(audit['preservedPublisherNotes'], 10)
        self.assertEqual(audit['preservedReadableCompanions'], 4)

    def test_uzbek_source_qualifications_are_exact_and_private_research_is_not_displayed(self):
        unit = self.units['uz']
        appendix = [block['text'] for block in unit['sections'][1]['blocks']]
        record = self.by_language['uz']
        allowed = first.literal_sources(record)
        source = next(item for item in record['sourceFiles']
                      if item['path'] == record['catalogEntry']['json'])
        for path in first.UZ_FINAL_QUALIFICATION_FIELDS:
            pointer = ['reader', 'sourceQualification', *path]
            value = normalize_lines(first.pointer(self.payload('uz'), pointer))
            self.assertIn(value, appendix)
            self.assertIn({'source': source, 'pointer': pointer}, allowed)
        for path in (['reader', 'sourceQualification', 'own27'],
                     ['reader', 'sourceQualification', 'openDuties', 'otherActualPrivateResearch'],
                     ['reader', 'sourceQualification', 'openDuties', 'recipient']):
            self.assertNotIn({'source': source, 'pointer': path}, allowed)
            self.assertNotIn(normalize_lines(first.pointer(self.payload('uz'), path)), appendix)
        private = next(item for item in record['sourceFiles']
                       if item['path'].endswith('FINAL-SOURCE-REVIEW-FINDING934.json'))
        with self.assertRaisesRegex(ValueError, 'public export allowlist'):
            first.literal_value(self.root, record, {'source': private, 'pointer': ['$text']})
        for item in record['displayPlan']['sourceOnlyExport']:
            self.assertNotIn('historical-evidence-not-bundled:', item['sourcePath'])

    def test_uzbek_publisher_credit_has_two_exact_bound_hyperlinks(self):
        unit = self.units['uz']
        credit, = [block for block in unit['sections'][1]['blocks'] if block.get('hyperlinks')]
        metadata = next(parent['metadata'] for parent in self.reader('uz')['sourceParents']
                        if 'creditRequired' in parent['metadata'])
        self.assertEqual(credit['text'], metadata['creditRequired'])
        self.assertTrue(credit['sourceOnlyContext'])
        check_text(self.root, credit['text'], 'uz', [credit['sourceLiteralProof']], exact=True)
        expected = [('расмий веб-портали', metadata['homeURL']), ('хабар беради', metadata['articleURL'])]
        self.assertEqual(len(credit['hyperlinks']), 2)
        for link, (label, url) in zip(credit['hyperlinks'], expected):
            self.assertEqual(credit['text'][link['start']:link['end']], label)
            self.assertEqual(link['url'], url)
            check_text(self.root, url, 'uz', [link['sourceLiteralProof']], exact=True)
            altered = deepcopy(link['sourceLiteralProof'])
            altered['pointer'] = ['reader', 'sourceQualification', 'status']
            with self.assertRaises(ValueError):
                check_text(self.root, url, 'uz', [altered], exact=True)

    def test_uzbek_credit_links_cannot_swap_individually_valid_destinations(self):
        from build_books import check_unit
        altered = deepcopy(self.units['uz'])
        credit, = [block for block in altered['sections'][1]['blocks'] if block.get('hyperlinks')]
        first_link, second_link = credit['hyperlinks']
        for name in ('url', 'sourceLiteralProof'):
            first_link[name], second_link[name] = second_link[name], first_link[name]
        with self.assertRaises(ValueError):
            check_unit(altered, {'language': 'uz', 'collection': 'hadith', 'id': first.UNIT_ID}, root=self.root)

    def test_uzbek_credit_links_cannot_move_to_different_valid_paragraph_words(self):
        from build_books import check_unit
        altered = deepcopy(self.units['uz'])
        credit, = [block for block in altered['sections'][1]['blocks'] if block.get('hyperlinks')]
        # The destination and both exact source proofs remain valid. Only the
        # hyperlink's labelled words differ, which must also fail closed.
        credit['hyperlinks'][0]['start'] = 0
        credit['hyperlinks'][0]['end'] = len('Ўзбекистон')
        with self.assertRaises(ValueError):
            check_unit(altered, {'language': 'uz', 'collection': 'hadith', 'id': first.UNIT_ID}, root=self.root)

    def test_existing_spans_never_rewrite_a_published_quote(self):
        count = 0
        for unit in self.units.values():
            for section in unit['sections']:
                for block in section['blocks']:
                    if block.get('spans'):
                        count += 1
                        self.assertEqual(''.join(s['text'] for s in block['spans']), block['text'])
        self.assertGreater(count, 200)

    def test_literal_publisher_names_are_bound_to_exact_current_source_fields(self):
        proofs = []
        for language, unit in self.units.items():
            for section in unit['sections']:
                for block in section['blocks']:
                    if block.get('sourceLiteralProof'):
                        proof = block['sourceLiteralProof']
                        check_text(self.root, block['text'], language, [proof], exact=True)
                        proofs.append((language, block, proof))
        self.assertGreaterEqual(len(proofs), 10)
        language, block, proof = proofs[0]
        altered = deepcopy(proof)
        altered['pointer'] = ['status']
        with self.assertRaises(ValueError):
            check_text(self.root, block['text'], language, [altered], exact=True)

    def test_changed_reader_bytes_fail_closed(self):
        record = self.by_language['ms']
        with self.changed_json(record['catalogEntry']['json'],
                               lambda value: value['reading']['commentarySections'][0].update(text='changed')):
            with self.assertRaises(ValueError):
                first.validate_record(self.root, record, record['catalogEntry'], self.catalog)

    def test_changed_source_companion_fails_closed(self):
        record = self.by_language['uz']
        path = next(b['path'] for b in record['sourceFiles'] if b['path'].endswith('TERRA-CONSUMER-CONTRACT934.json'))
        with self.changed_json(path, lambda value: value.update(scope='changed')):
            with self.assertRaises(ValueError):
                first.validate_record(self.root, record, record['catalogEntry'], self.catalog)

    def test_superseded_or_withdrawn_catalogue_rows_are_rejected(self):
        record = self.by_language['id']
        for update in ({'status': 'superseded'}, {'current': False}, {'archived': True}):
            with self.subTest(update=update):
                row = {**record['catalogEntry'], **update}
                with self.assertRaises(ValueError):
                    first.validate_record(self.root, record, row, self.catalog)

    def test_changed_arabic_source_requires_new_correspondence(self):
        def change(value):
            value['commentary'][0]['text'] += ' changed'
        with self.changed_json(first.ARABIC_CURRENT, change):
            with self.assertRaisesRegex(ValueError, 'superseded Arabic reader'):
                first.snapshot(self.root, self.catalog, self.inventory['sourceCommit'])

    def test_whole_commentary_cannot_drop_or_reorder_a_section(self):
        row = self.by_language['ms']['catalogEntry']
        for operation in ('drop', 'reorder'):
            payload = self.payload('ms')
            sections = payload['reading']['commentarySections']
            if operation == 'drop':
                del sections[0]
            else:
                sections[0], sections[1] = sections[1], sections[0]
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                first.reader_plan(self.root, row, payload)

    def test_changed_review_qualification_cannot_be_inferred_from_filename(self):
        record = self.by_language['ms']
        catalog = deepcopy(self.catalog)
        catalog['essentialFirst871']['languages'].remove('ms')
        with self.assertRaises(ValueError):
            first.validate_record(self.root, record, record['catalogEntry'], catalog)

    def test_current_binding_supports_later_typed_reader_without_double_import(self):
        declaration = next(d for d in self.declarations['books'] if d['language'] == 'ms')
        produced = first.generate(self.root, self.catalog, declaration)
        self.assertEqual([unit['id'] for unit in produced], [first.UNIT_ID])
        self.assertEqual(first.generate(self.root, self.catalog, declaration,
                         excluded_catalog_keys={('essential-hadith', 'ms', first.UNIT_ID)}), [])


if __name__ == '__main__':
    unittest.main()
