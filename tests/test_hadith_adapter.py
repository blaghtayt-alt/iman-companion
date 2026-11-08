"""Exact-source and publication-boundary checks for the real Arabic course."""
from collections import Counter
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
from adapt_ar_hadith import ADAPTER, MATERIAL_INDEX, export_projection, generate, _verify_source_preservation


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


class EssentialHadithAdapterChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.projection = export_projection(ROOT, cls.catalog)
        conf = json.loads((ROOT / 'books/config.json').read_bytes())
        cls.paths = {row[k] for key in ('chapters', 'lessons') for row in cls.projection[key]
                     for k in ('json', 'markdown')}
        cls.paths |= {MATERIAL_INDEX, 'books/config.json', conf['quranText']['path'], conf['surahNames']['path']}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in self.paths:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.catalog = deepcopy(type(self).catalog)
        self.projection_path = self.root / 'books/source-projections/ar-essential-hadith.json'
        dump(self.projection_path, type(self).projection)
        self.declaration = {'language': 'ar', 'collection': 'hadith', 'adapter': ADAPTER,
                            'hadithEdition': 'new-extended', 'materialIndex': MATERIAL_INDEX,
                            'projection': self.projection_path.relative_to(self.root).as_posix(),
                            'projectionSHA256': hashlib.sha256(self.projection_path.read_bytes()).hexdigest(),
                            'state': 'reviewed-current', 'automaticBuild': True, 'automaticRelease': False}

    def tearDown(self):
        self.temp.cleanup()

    def units(self):
        return generate(self.root, self.catalog, self.declaration)

    def test_complete_course_preserves_exact_source_and_every_chapter_once(self):
        units = self.units()
        expected = type(self).projection['lessons']
        self.assertEqual([u['id'] for u in units], [e['id'] for e in expected])
        self.assertEqual([u['order'] for u in units], sorted({e['chapter'] * 1000 + e['lesson'] for e in expected}))
        introductions, bibliographies = Counter(), Counter()
        for unit, record in zip(units, expected):
            source = json.loads((self.root / record['json']).read_bytes())
            # Includes every original run, source paragraph, link, qualification
            # and source heading, including metadata not rendered as book prose.
            self.assertEqual(unit['provenance']['sourceLesson'], source)
            self.assertNotIn('referenceReadiness', unit)
            preservation = unit['sourceReferencePreservation']
            self.assertEqual(preservation['schema'], 'iman-source-reference-preservation-v1')
            self.assertEqual(preservation['auditMode'], 'literal-source-and-qualification-fidelity')
            self.assertEqual(preservation['sourceReferences'], preservation['preservedReferences'])
            self.assertEqual(preservation['sourceQualifications'], len(source['referenceQualifications']))
            self.assertEqual(preservation['sourceQualifications'], preservation['preservedQualifications'])
            self.assertEqual(preservation['sourceParagraphs'], preservation['preservedParagraphs'])
            self.assertEqual([preservation[k] for k in ('lostReferences', 'lostQualifications', 'lostParagraphs')], [0, 0, 0])
            self.assertEqual(unit['hadithEdition'], 'new-extended')
            self.assertEqual(unit['catalogBindings'], [{'collection': 'essential-hadith', 'language': 'ar', 'id': unit['id']}])
            self.assertEqual(unit['title'], source['originalTitle'])
            for binding in unit['inputBindings']:
                self.assertEqual(hashlib.sha256((self.root / binding['path']).read_bytes()).hexdigest(), binding['sha256'])
            blocks = unit['sections'][0]['blocks']
            transformations = unit['provenance']['referenceFurnitureTransformations']
            for original, origin in [(source['mainNarration'], 'main-narration'),
                                     *((p, 'commentary') for p in source['commentary'])]:
                block = next(b for b in blocks if b['sourceOrigin'] == origin and b.get('sourceParagraph') == original['sourceParagraph'])
                moved = {p['sourceRunIndex']: p['literal'] for m in transformations
                         if m['sourceOrigin'] == origin and m['sourceParagraph'] == original['sourceParagraph']
                         for p in m['sourceRunParts']}
                self.assertEqual(''.join(moved[i] if i in moved else span['text']
                                         for i, span in enumerate(block['spans'])), original['text'])
                self.assertEqual(len(block['spans']), len(original['runs']))
                for index, run in enumerate(original['runs']):
                    self.assertEqual(block['spans'][index]['bold'], bool(run.get('bold')))
            self.assertEqual(next(b['text'] for b in blocks if b['sourceOrigin'] == 'main-reference'), source['reference']['text'])
            for block in blocks:
                if block['sourceOrigin'] == 'chapter-introduction':
                    introductions[unit['chapter']] += 1
                if block['sourceOrigin'] == 'chapter-bibliography':
                    bibliographies[unit['chapter']] += 1
            chapter = next(c for c in type(self).projection['chapters'] if c['number'] == unit['chapter'])
            self.assertEqual(unit['chapterTitle'], chapter['title'])
        for chapter in type(self).projection['chapters']:
            original = json.loads((self.root / chapter['json']).read_bytes())
            self.assertEqual(introductions[chapter['number']], len(original['introduction']))
            self.assertEqual(bibliographies[chapter['number']], len(original['bibliography']))
            current = [u for u in units if u['chapter'] == chapter['number']]
            self.assertEqual(current[0]['provenance']['chapterIntroduction'], original['introduction'])
            self.assertEqual(current[-1]['provenance']['chapterBibliography'], original['bibliography'])
            # Required source licenses remain literal, including Latin credits.
            self.assertEqual([b['text'] for b in current[-1]['sections'][0]['blocks']
                              if b['sourceOrigin'] == 'chapter-bibliography'], [p['text'] for p in original['bibliography']])

    def test_literal_references_qualifications_and_unknown_locators_are_not_invented(self):
        units = self.units()
        unknown = []
        for unit in units:
            source = unit['provenance']['sourceLesson']
            notes = [b['text'] for b in unit['sections'][0]['blocks'] if b['kind'] == 'note']
            notes += [n for b in unit['sections'][0]['blocks'] for s in b.get('spans', []) for n in s.get('noteTexts', [])]
            for qualification in source['referenceQualifications']:
                self.assertTrue(any(qualification in note for note in notes), qualification)
            for move in unit['provenance']['referenceFurnitureTransformations']:
                if move['binding'] is None:
                    unknown.append(move)
                    self.assertEqual(move['presentation'], {'noteTexts': [move['literal']]})
                if move['presentation'].get('noteTexts'):
                    self.assertIn(move['literal'], notes)
            rendered = ''.join(b['text'] for b in unit['sections'][0]['blocks']) + ''.join(notes)
            for link in source['externalSourceLinks']:
                self.assertNotIn(link['url'], rendered)
            # The binding inventory and adapter do not manufacture approval.
            self.assertFalse(self.declaration['automaticRelease'])
        self.assertTrue(unknown, 'Real course includes book-only/ambiguous source locators')
        totals = Counter()
        for unit in units:
            totals.update({k: v for k, v in unit['sourceReferenceDiagnostics'].items() if type(v) is int})
        self.assertGreater(totals['quranGroupsWithoutImmediateTypedReference'], 0)
        self.assertGreater(totals['quotationGroupsWithoutImmediateReference'], 0)
        self.assertGreater(totals['literalReferencesWithoutTypedClassification'], 0)

    def test_literal_book_page_credit_and_repeated_narration_are_preserved_without_false_typing(self):
        units = {u['id']: u for u in self.units()}
        scholarly = units['essential-01-004']
        move = next(m for m in scholarly['provenance']['referenceFurnitureTransformations'] if m['literal'] == '[الفوائد ص31]')
        self.assertIsNone(move['binding'])
        self.assertEqual(move['presentation'], {'noteTexts': ['[الفوائد ص31]']})
        main = units['essential-01-001']
        repeated = next(s for b in main['sections'][0]['blocks'] if b.get('sourceOrigin') == 'commentary'
                        for s in b.get('spans', []) if s['text'] == '«جميعا»')
        self.assertNotIn('citations', repeated)
        self.assertNotIn('verseKeys', repeated)
        self.assertGreater(main['sourceReferenceDiagnostics']['quotationGroupsWithoutImmediateReference'], 0)
        self.assertEqual(main['sourceReferencePreservation']['lostReferences'], 0)
        self.assertEqual(scholarly['sourceReferencePreservation']['lostReferences'], 0)

    def test_source_preservation_proof_rejects_a_lost_note_or_main_reference(self):
        unit = self.units()[0]
        source = unit['provenance']['sourceLesson']
        transformations = unit['provenance']['referenceFurnitureTransformations']
        arguments = (unit['provenance']['chapterIntroduction'], unit['provenance']['chapterBibliography'])
        blocks = deepcopy(unit['sections'][0]['blocks'])
        span = next(s for b in blocks for s in b.get('spans', []) if s.get('noteTexts'))
        span.pop('noteTexts')
        with self.assertRaisesRegex(ValueError, 'source reference placement was lost'):
            _verify_source_preservation(source, blocks, transformations, *arguments)
        blocks = [b for b in unit['sections'][0]['blocks'] if b.get('sourceOrigin') != 'main-reference']
        with self.assertRaisesRegex(ValueError, 'source paragraph was lost'):
            _verify_source_preservation(source, blocks, transformations, *arguments)

    def test_changed_lesson_bytes_or_projection_cannot_silently_rebuild(self):
        source = self.root / type(self).projection['lessons'][0]['json']
        original = source.read_bytes()
        source.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'source bindings or current coverage changed'):
            self.units()
        source.write_bytes(original)
        self.projection_path.write_bytes(self.projection_path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'projection changed'):
            self.units()

    def test_split_source_labels_and_bidi_controls_keep_exact_literal_binding(self):
        units = self.units()
        split = [(unit, move) for unit in units for move in unit['provenance']['referenceFurnitureTransformations']
                 if len(move['sourceRunParts']) > 1]
        self.assertTrue(split, 'Real Word source contains labels split across formatting runs')
        for unit, move in split:
            self.assertEqual(''.join(p['literal'] for p in move['sourceRunParts']), move['literal'])
            self.assertTrue(move['presentation'].get('verseKeys'))
            block = next(b for b in unit['sections'][0]['blocks'] if b.get('sourceOrigin') == move['sourceOrigin']
                         and b.get('sourceParagraph') == move['sourceParagraph'])
            positions = [p['sourceRunIndex'] for p in move['sourceRunParts']]
            self.assertEqual(sum(bool(block['spans'][i].get('verseKeys')) for i in positions), 1)
            self.assertTrue(all(block['spans'][i]['text'] == '' for i in positions))

    def test_new_current_member_cannot_be_omitted_and_legacy_does_not_enter(self):
        row = deepcopy(next(e for e in self.catalog['entries'] if e.get('collection') == 'essential-hadith' and e.get('language') == 'ar'))
        row['id'] = 'essential-99-001'
        self.catalog['entries'].append(row)
        with self.assertRaisesRegex(ValueError, 'coverage changed'):
            self.units()
        self.catalog['entries'][-1]['collection'] = 'hadith'
        self.catalog['entries'][-1]['id'] = 'legacy-short-303'
        self.assertEqual([u['id'] for u in self.units()], [e['id'] for e in type(self).projection['lessons']])

    def test_source_run_corruption_is_rejected_before_rendering(self):
        path = self.root / type(self).projection['lessons'][0]['json']
        source = json.loads(path.read_bytes())
        source['commentary'][0]['runs'][0]['text'] += ' تبديل'
        dump(path, source)
        with self.assertRaisesRegex(ValueError, 'runs differ from paragraph text'):
            self.units()

    def test_duplicate_chapter_lesson_position_is_rejected(self):
        rows = [e for e in self.catalog['entries'] if e.get('collection') == 'essential-hadith' and e.get('language') == 'ar']
        rows[1]['chapter'], rows[1]['lesson'] = rows[0]['chapter'], rows[0]['lesson']
        with self.assertRaisesRegex(ValueError, 'order is missing or ambiguous'):
            self.units()

    def test_changed_chapter_bibliography_is_bound_to_every_member(self):
        path = self.root / type(self).projection['chapters'][0]['json']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'source bindings or current coverage changed'):
            self.units()

    def test_projection_inventory_is_read_only_and_order_independent(self):
        before = deepcopy(self.catalog)
        expected = type(self).projection
        self.catalog['entries'].reverse()
        self.assertEqual(export_projection(self.root, self.catalog), expected)
        self.catalog['entries'].reverse()
        self.assertEqual(self.catalog, before)
        bad = deepcopy(self.declaration)
        bad['hadithEdition'] = 'legacy-short'
        with self.assertRaisesRegex(ValueError, 'Unsupported Essential Hadith'):
            generate(self.root, self.catalog, bad)


if __name__ == '__main__':
    unittest.main()
