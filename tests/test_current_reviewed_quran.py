"""Regression checks against the current, previously omitted Quran readers.

The fixtures are copies of the installed source publications. No source text,
review decision, declaration or generated unit in the repository is mutated.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))

import current_reviewed_quran as current
from bibliography import native_text, quran_reference
from book_edition_scope import POLICY, select
from build_books import check_unit
from reviewed_coverage import validate as validate_coverage
from source_literal_text import check_bound_text, check_text, normalize_lines


def output_blocks(unit):
    return [block for section in unit['sections'] for block in section['blocks']]


def output_notes(unit):
    return [text for block in output_blocks(unit) for span in block.get('spans', [])
            for text in span.get('noteTexts', [])]


class CurrentReviewedQuran(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.inventory = current.read(ROOT, current.PROJECTION)
        cls.records = {(record['language'], record['id']): record
                       for record in cls.inventory['records']}
        cls.config = current.read(ROOT, 'books/config.json')
        paths = {current.PROJECTION, 'materials/catalog.json', 'books/config.json',
                 cls.config['quranText']['path'], cls.config['surahNames']['path']}
        for record in cls.records.values():
            paths.update(item['path'] for item in record['sourceFiles'] + record['sourceConditions'])
        for path in paths:
            destination = cls.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, destination)
        cls.catalog = current.read(cls.root, 'materials/catalog.json')
        cls.evidence = current.binding(cls.root, current.PROJECTION)
        cls.quran = current.read(cls.root, cls.config['quranText']['path'])
        cls.declarations = {'schema': 'iman-reviewed-books-v1', 'books': [
            {'language': language, 'collection': 'tadabbur-extended',
             'state': 'reviewed-current', 'automaticBuild': True,
             'scopePolicy': POLICY, 'sourceReviewBindings': [cls.evidence]}
            for language in sorted({language for language, _ in cls.records})]}
        (cls.root / 'books/reviewed-books.json').write_text(
            json.dumps(cls.declarations, ensure_ascii=False), encoding='utf8')
        cls.units = {identity: current.normalize(cls.root, cls.catalog,
                     record['catalogEntry'], record, cls.evidence)
                     for identity, record in cls.records.items()}

    def payload(self, identity):
        return current.read(self.root, self.records[identity]['catalogEntry']['json'])

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

    def test_inventory_restores_exact_current_candidates_and_no_obsolete_files(self):
        expected = {(language, f'{surah}:extended')
                    for language in current.ENTRY_LANGUAGES for surah in current.ENTRY_SURAHS}
        expected.update((language, 'fatiha-extended') for language in current.FATIHA_LANGUAGES)
        expected.add(('ja', '75:extended'))
        self.assertEqual(set(self.records), expected)
        self.assertEqual(len(expected), 124)
        self.assertEqual(current.snapshot(self.root, self.catalog,
                                         self.inventory['sourceCommit']), self.inventory)
        for record in self.records.values():
            self.assertFalse(record['sourceApprovalCreated'])
            self.assertFalse(record['humanCertification'])
            for source in record['sourceFiles'] + record['sourceConditions']:
                self.assertNotIn('/source-archive/', source['path'])

    def test_all_112_entry_maps_match_the_current_arabic_revision(self):
        entries = 0
        for identity, record in self.records.items():
            if record['sourceKind'] != 'reviewed-entries-map':
                continue
            with self.subTest(identity=identity):
                row = record['catalogEntry']
                self.assertEqual(row['sourceHashes'], record['currentArabicCatalogEntry']['sourceHashes'])
                for entry in self.payload(identity)['entries'].values():
                    entries += 1
                    self.assertEqual(entry['internalReviewStatus'], 'reviewed')
                    self.assertIn(entry['sourceSha256'], row['sourceHashes'])
                    self.assertEqual(entry['sourceLanguage'], 'ar')
        self.assertEqual(entries, 1608)

    def test_every_structured_paragraph_is_preserved_in_original_order(self):
        total = 0
        for identity, record in self.records.items():
            if record['sourceKind'] != 'reviewed-entries-map':
                continue
            with self.subTest(identity=identity):
                expected = [normalize_lines(block['text'])
                            for entry in self.payload(identity)['entries'].values()
                            for block in entry['blocks']]
                actual = [block['text'] for block in output_blocks(self.units[identity])
                          if block['kind'] != 'ayah']
                self.assertEqual(actual, expected)
                total += len(expected)
        self.assertEqual(total, 7027)

    def test_original_citation_references_urls_and_qualifying_words_survive(self):
        citations = 0
        for identity, record in self.records.items():
            if record['sourceKind'] != 'reviewed-entries-map':
                continue
            unit = self.units[identity]
            notes = '\n'.join(output_notes(unit))
            body = '\n'.join(block['text'] for block in output_blocks(unit))
            for entry in self.payload(identity)['entries'].values():
                for citation in entry.get('citations', []):
                    citations += 1
                    for field in ('reference', 'canonicalReference', 'sourceReference', 'url',
                                  'label', 'excerptNotice', 'quotationType'):
                        if isinstance(citation.get(field), str) and citation[field].strip():
                            self.assertIn(normalize_lines(citation[field]), notes, (identity, field))
                    if citation.get('quote'):
                        self.assertIn(normalize_lines(citation['quote']), body + notes, identity)
                    if citation.get('kind') == 'indirect report / related evidence, not a newly translated quotation':
                        self.assertIn(citation['kind'], notes, identity)
            preservation = unit['sourceReferencePreservation']
            self.assertEqual(preservation['sourceReferences'], preservation['preservedReferences'])
            self.assertEqual(preservation['lostReferences'], 0)
            self.assertNotIn('referenceReadiness', unit)
        self.assertEqual(citations, 5978)

    def test_structured_publisher_footnotes_are_not_replaced_by_attribution(self):
        supplied = 0
        def leaves(value):
            if isinstance(value, str):
                if value.strip():
                    yield normalize_lines(value)
            elif isinstance(value, dict):
                for child in value.values():
                    yield from leaves(child)
            elif isinstance(value, list):
                for child in value:
                    yield from leaves(child)
        for identity, record in self.records.items():
            if record['sourceKind'] != 'reviewed-entries-map':
                continue
            notes = '\n'.join(output_notes(self.units[identity]))
            for entry in self.payload(identity)['entries'].values():
                source = entry.get('quranTranslationSource', {})
                for text in leaves(source.get('footnotes')):
                    supplied += 1
                    self.assertIn(text, notes, identity)
        self.assertGreater(supplied, 20)

    def test_fatiha_includes_all_eight_sections_and_all_67_original_blocks(self):
        for language in current.FATIHA_LANGUAGES:
            identity = (language, 'fatiha-extended')
            source = self.payload(identity)
            unit = self.units[identity]
            with self.subTest(language=language):
                expected = [normalize_lines(source['shortCredit'])]
                expected += [normalize_lines(block['text']) for section in source['units']
                             for block in section['blocks']]
                actual = [block['text'] for block in output_blocks(unit) if block['kind'] != 'ayah']
                self.assertEqual(actual, expected)
                self.assertEqual(len(expected), 68)
                self.assertEqual(unit['reviewedCoverage']['ayahKeys'], [f'1:{n}' for n in range(1, 8)])
                self.assertEqual(unit['reviewedCoverage']['introduction']['state'], 'included')
                self.assertEqual(unit['title'], source['title'])

    def test_every_fatiha_reader_note_and_glossary_definition_is_in_the_book(self):
        counts = {'de': (0, 7), 'ja': (6, 12), 'fil': (5, 15), 'hi': (0, 0),
                  'zh-CN': (5, 14), 'fa': (0, 7), 'th': (4, 22), 'ru': (1, 10),
                  'vi': (6, 19), 'es': (5, 11), 'uz': (0, 11)}
        for language, expected_counts in counts.items():
            identity = (language, 'fatiha-extended')
            source = self.payload(identity)
            notes = '\n'.join(output_notes(self.units[identity]))
            with self.subTest(language=language):
                self.assertEqual((len(source['readerNotes']), len(source['glossary'])), expected_counts)
                for note in source['readerNotes']:
                    for field in ('title', 'text'):
                        if note.get(field):
                            self.assertIn(normalize_lines(note[field]), notes)
                for term in source['glossary']:
                    self.assertIn(normalize_lines(term['term']), notes)
                    self.assertIn(normalize_lines(term['meaning']), notes)

    def test_fatiha_source_carrier_is_bound_without_promoting_unused_source_parents(self):
        identity = ('uz', 'fatiha-extended')
        record = self.records[identity]
        path = 'materials/tadabbur/fatiha-extended/uz/sources.json'
        self.assertIn(current.binding(self.root, path), self.units[identity]['inputBindings'])
        source = current.read(self.root, path)
        transcript = source['editionsAndConditions']['Quran']['transcript']
        ordinary = '\n'.join([block['text'] for block in output_blocks(self.units[identity])] +
                             output_notes(self.units[identity]))
        self.assertNotIn(normalize_lines(transcript), ordinary)
        self.assertEqual(record['literalFields'][path], [['sourceCredit']])
        self.assertNotIn('sourceSections', json.dumps(record['literalFields'][path]))

    def test_japanese_qiyamah_retains_all_40_verses_and_complete_bounded_notes(self):
        identity = ('ja', '75:extended')
        source = self.payload(identity)
        unit = self.units[identity]
        notes = output_notes(unit)
        sections = {section['ayahKey']: section for section in unit['sections'] if section.get('ayahKey')}
        self.assertEqual(list(sections), [f'75:{n}' for n in range(1, 41)])
        total = 0
        for item in source['entries']:
            path = (Path(self.records[identity]['catalogEntry']['json']).parent / item['json']).as_posix()
            original = current.read(self.root, path)
            expected = [normalize_lines(block['text']) for block in original['unit']['blocks']]
            actual = [block['text'] for block in sections[item['key']]['blocks'][1:]]
            # The last verse is followed by its unchanged source bibliography.
            self.assertEqual(actual[:len(expected)], expected)
            total += len(expected)
            for part in original['completeReadingAndBoundedContext']:
                if part['role'] == 'note' and part.get('text'):
                    self.assertIn(normalize_lines(part['text']), notes)
        self.assertGreater(total, 200)
        front = current.read(self.root, current.QIYAMAH_FRONT)
        all_text = [block['text'] for block in output_blocks(unit)]
        for part in front[1:]:
            if part.get('text'):
                self.assertIn(normalize_lines(part['text']), all_text)
            for link in part.get('links', []):
                if link.get('url'):
                    self.assertIn(normalize_lines(link['url']), all_text)

    def test_qiyamah_deduplicates_only_shared_publication_notes_and_keeps_verse_anchors(self):
        unit = self.units['ja', '75:extended']
        evidence = unit['sourceReferencePreservation']
        self.assertEqual(evidence['sourceQualificationOccurrences'], 256)
        self.assertEqual(evidence['deduplicatedSharedQualifications'], 117)
        self.assertEqual(evidence['sourceQualifications'], 139)
        self.assertEqual(evidence['preservedQualifications'], len(output_notes(unit)))
        for key in ('75:16', '75:40'):
            section = next(section for section in unit['sections'] if section.get('ayahKey') == key)
            notes = [text for block in section['blocks'] for span in block.get('spans', [])
                     for text in span.get('noteTexts', [])]
            self.assertTrue(any(text.startswith('刊行元の訳注 · 75:16\n') for text in notes))
        shared = [row for row in unit['provenance']['sourceFieldsPreserved']
                  if row['placement'] == 'shared publication qualification already printed']
        self.assertEqual(len(shared), 117)
        self.assertTrue(all(row['printedAt']['section'] == '75:1' for row in shared))

    def test_partial_surahs_remain_explicitly_partial_with_exact_arabic(self):
        partial = []
        for identity, unit in self.units.items():
            with self.subTest(identity=identity):
                validate_coverage(unit, self.quran)
                self.assertEqual(unit['readerTextSHA256'], current.sha(
                    ''.join(block['text'] for block in output_blocks(unit)).encode()))
                for section in unit['sections']:
                    if section.get('ayahKey'):
                        self.assertEqual([block['kind'] for block in section['blocks'][:2]], ['ayah', 'translation'])
                        self.assertEqual(section['blocks'][0]['text'], self.quran[section['ayahKey']])
                        self.assertTrue(section['blocks'][1].get('translationCredit'))
                if unit['coverageLabel']:
                    partial.append(identity)
                    self.assertIn(unit['reviewedCoverage']['scopeLabel'], unit['title'])
        self.assertEqual(len(partial), 40)
        self.assertEqual(self.units['en', '17:extended']['reviewedCoverage']['ayahKeys'],
                         [f'17:{n}' for n in range(73, 82)])
        self.assertNotIn('15:10', self.units['en', '15:extended']['reviewedCoverage']['ayahKeys'])

    def test_fallback_surah_titles_use_existing_native_furniture_and_canonical_number(self):
        unit = self.units['bn', '1:extended']
        native_text(unit['title'], 'bn')
        self.assertIn('১', unit['title'])
        self.assertNotIn('Al-Fatihah', unit['title'])

    def test_original_semantic_spans_never_change_the_words(self):
        count = 0
        for unit in self.units.values():
            for block in output_blocks(unit):
                if block.get('spans'):
                    count += 1
                    self.assertEqual(''.join(span['text'] for span in block['spans']), block['text'])
        self.assertGreater(count, 1000)

    def test_native_exceptions_require_exact_current_fields_and_unit_bindings(self):
        unit = self.units['ja', 'fatiha-extended']
        credit = next(block['translationCredit'] for block in output_blocks(unit)
                      if block.get('translationCredit'))
        check_bound_text(self.root, credit['text'], unit, credit['sourceLiteralProof'])
        proof = deepcopy(credit['sourceLiteralProof'][0])
        proof['pointer'] = ['sourceDetails', 'sourcesAndVersions', 'quranSato', 'requiredTranscriptInformation']
        with self.assertRaises(ValueError):
            check_text(self.root, credit['text'], 'ja', [proof])
        proof = deepcopy(credit['sourceLiteralProof'][0])
        proof['materialId'] = '75:extended'
        with self.assertRaises(ValueError):
            check_bound_text(self.root, credit['text'], unit, [proof])
        with self.assertRaises(ValueError):
            check_bound_text(self.root, credit['text'] + ' invented unbound words', unit,
                             credit['sourceLiteralProof'])

    def test_composed_original_source_note_is_validated_without_global_latin_exemption(self):
        unit = self.units['ur', '103:extended']
        span = next(span for block in output_blocks(unit) for span in block.get('spans', [])
                    if span.get('noteLiteralProofs'))
        text, proofs = span['noteTexts'][0], span['noteLiteralProofs'][0]
        self.assertGreater(len(proofs), 1)
        check_bound_text(self.root, text, unit, proofs)
        with self.assertRaises(ValueError):
            check_bound_text(self.root, text + ' https://invented.example', unit, proofs)

    def test_representative_units_pass_the_production_checker(self):
        for identity in [('en', '103:extended'), ('ja', 'fatiha-extended'),
                         ('bn', '103:extended'), ('uz', 'fatiha-extended')]:
            unit = self.units[identity]
            with self.subTest(identity=identity):
                check_unit(unit, {field: unit[field] for field in ('id', 'language', 'collection')},
                           self.quran, root=self.root)

    def test_changed_source_paragraph_or_companion_invalidates_the_bound_reading(self):
        for identity, path, change in [
            (('en', '103:extended'), 'materials/tadabbur/en/extended/103.json',
             lambda data: data['entries']['103:1']['blocks'][0].update(text='changed')),
            (('ja', 'fatiha-extended'), 'materials/tadabbur/fatiha-extended/ja/sources.json',
             lambda data: data.update(sourceCredit='changed'))]:
            record = self.records[identity]
            with self.subTest(identity=identity), self.changed_json(path, change):
                with self.assertRaises(ValueError):
                    current.validate_record(self.root, record, record['catalogEntry'], self.catalog)

    def test_superseded_arabic_and_withdrawn_material_cannot_reuse_the_inventory(self):
        record = self.records['en', '103:extended']
        catalog = deepcopy(self.catalog)
        arabic = next(row for row in catalog['entries']
                      if (row['collection'], row['language'], str(row['id'])) == ('tadabbur', 'ar', '103:extended'))
        arabic['sourceHashes'] = ['f' * 64]
        with self.assertRaisesRegex(ValueError, 'superseded'):
            current.validate_record(self.root, record, record['catalogEntry'], catalog)
        for field in ({'status': 'superseded'}, {'current': False}, {'archived': True}):
            with self.subTest(field=field), self.assertRaises(ValueError):
                current.validate_record(self.root, record, {**record['catalogEntry'], **field}, self.catalog)

    def test_unfinished_review_and_removed_intro_are_not_silently_reaccepted(self):
        record = self.records['en', '1:extended']
        path = record['catalogEntry']['json']
        with self.changed_json(path, lambda data: data['entries']['1:1'].update(internalReviewStatus='pending')) as payload:
            with self.assertRaises(ValueError):
                current._entry_map(self.root, record['catalogEntry'], payload)
        record = self.records['ja', 'fatiha-extended']
        path = record['catalogEntry']['json']
        with self.changed_json(path, lambda data: data['units'].pop(0)) as payload:
            with self.assertRaises(ValueError):
                current._fatiha(self.root, self.catalog, record['catalogEntry'], payload)

    def test_missing_qiyamah_final_qualification_or_verse_is_rejected(self):
        record = self.records['ja', '75:extended']
        path = record['catalogEntry']['json']
        with self.changed_json(path, lambda data: data['entries'].pop(0)) as payload:
            with self.assertRaises(ValueError):
                current._qiyamah(self.root, record['catalogEntry'], payload)
        index = self.payload(('ja', '75:extended'))
        verse_path = (Path(path).parent / index['entries'][0]['json']).as_posix()
        with self.changed_json(verse_path, lambda data: data['unit'].update(releaseQualified=False)):
            with self.assertRaises(ValueError):
                current._qiyamah(self.root, record['catalogEntry'], index)

    def test_select_and_generate_honor_explicit_published_reader_precedence(self):
        declaration = next(item for item in self.declarations['books'] if item['language'] == 'ja')
        selected, _ = select(self.root, self.catalog, declaration)
        self.assertEqual({str(row['id']) for row in selected}, {'fatiha-extended', '75:extended'})
        generated = current.generate(self.root, self.catalog, declaration,
                                     excluded_catalog_keys={('tadabbur', 'ja', 'fatiha-extended')})
        self.assertEqual([unit['id'] for unit in generated], ['75:extended'])


class ExistingIkhlasPreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import adapt_ikhlas
        cls.adapter = adapt_ikhlas
        cls.units = {}
        cls.audit_inputs = {}
        catalog = current.read(ROOT, 'materials/catalog.json')
        declarations = current.read(ROOT, 'books/reviewed-books.json')
        audit = adapt_ikhlas.preservation_evidence
        for declaration in declarations['books']:
            if declaration.get('adapter') != 'reviewed-ikhlas-v1':
                continue
            def capture(*args):
                cls.audit_inputs[declaration['language']] = deepcopy(args)
                return audit(*args)
            with patch.object(adapt_ikhlas, 'preservation_evidence', side_effect=capture):
                cls.units[declaration['language']], = adapt_ikhlas.generate(ROOT, catalog, declaration)

    def test_every_existing_ikhlas_unit_has_measured_paragraph_reference_and_note_preservation(self):
        self.assertEqual(len(self.units), 19)
        for language, unit in self.units.items():
            with self.subTest(language=language):
                evidence = unit['sourceReferencePreservation']
                original_units = [current.read(ROOT,
                    f'materials/tadabbur/sources/112/{language}/112-{number:03d}.json')
                    for number in range(1, 5)]
                self.assertEqual(evidence['sourceParagraphs'], sum(len(u['paragraphs']) for u in original_units))
                self.assertEqual(evidence['sourceParagraphs'], evidence['preservedParagraphs'])
                self.assertEqual(evidence['sourceQualifications'], len(self.adapter.note_rows(original_units)))
                self.assertEqual(evidence['sourceQualifications'], evidence['preservedQualifications'])
                self.assertEqual(evidence['sourceReferences'], 65 if language in {'tr', 'id', 'ms'} else 64)
                self.assertEqual(evidence['sourceReferences'], evidence['preservedReferences'])
                self.assertTrue(unit['provenance']['exactSentenceWordsPreserved'])

    def test_ikhlas_audit_rejects_a_lost_original_paragraph(self):
        inputs = deepcopy(self.audit_inputs['en'])
        del inputs[1]['p05']
        with self.assertRaisesRegex(ValueError, 'paragraphs were not completely preserved'):
            self.adapter.preservation_evidence(*inputs)

    def test_ikhlas_audit_rejects_lost_source_references(self):
        inputs = deepcopy(self.audit_inputs['en'])
        for section in inputs[-1]:
            for block in section['blocks']:
                for span in block.get('spans', []):
                    span.pop('citations', None)
        with self.assertRaisesRegex(ValueError, 'source references were not completely preserved'):
            self.adapter.preservation_evidence(*inputs)

    def test_ikhlas_audit_rejects_a_lost_publisher_note(self):
        inputs = deepcopy(self.audit_inputs['en'])
        span = next(span for section in inputs[-1] for block in section['blocks']
                    for span in block.get('spans', []) if span.get('noteTexts'))
        span['noteTexts'].pop()
        with self.assertRaisesRegex(ValueError, 'notes were not completely preserved'):
            self.adapter.preservation_evidence(*inputs)


class BengaliCanonicalReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = current.read(ROOT, 'books/config.json')
        cls.names = current.read(ROOT, config['surahNames']['path'])

    def test_missing_verified_names_remain_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, 'Missing verified native surah name'):
            quran_reference('15:1', 'bn', self.names)
        with self.assertRaisesRegex(ValueError, 'Missing verified native surah name'):
            quran_reference('15:1', 'ur', {}, allow_numbered=True)

    def test_explicit_bengali_numeric_citation_uses_exact_canonical_range(self):
        result = quran_reference('15:1-9', 'bn', self.names, allow_numbered=True)
        self.assertEqual(result.replace('\u00a0', ' '), '(সূরা ১৫, আয়াত ১–৯)')
        native_text(result, 'bn')
        self.assertNotIn('Al-Hijr', result)
        for key in ('0:1', '115:1', '15:9-1', '15:1-287'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                quran_reference(key, 'bn', self.names, allow_numbered=True)

    def test_numeric_permission_does_not_replace_an_existing_verified_name(self):
        strict = quran_reference('112:1-4', 'bn', self.names)
        self.assertEqual(quran_reference('112:1-4', 'bn', self.names, allow_numbered=True), strict)
        self.assertIn('আল-ইখলাস', strict)


if __name__ == '__main__':
    unittest.main()
