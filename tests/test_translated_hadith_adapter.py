"""Source fidelity and eligibility regression checks for translated Hadith books."""
from copy import deepcopy
import json
from pathlib import Path
from shutil import copyfile
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))

from adapt_translated_hadith import generate, note_fields
from book_edition_scope import select
from build_books import check_unit
from multilingual_readiness import inventory
from reviewed_hadith_sources import ADAPTER
from source_literal_text import check_text, exact_literal, sha


class TranslatedHadithTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.declarations = json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
        cls.scopes = {row['language']: row for row in cls.declarations if row.get('adapter') == ADAPTER}
        cls.units = {language: generate(ROOT, cls.catalog, declaration) for language, declaration in cls.scopes.items()}

    def write(self, root, relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')

    def literal_fixture(self, root):
        """Copy exact existing inputs into an isolated, mutable review fixture."""
        unit = deepcopy(self.units['ja'][0])
        for binding in unit['inputBindings']:
            path = root / binding['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            copyfile(ROOT / binding['path'], path)
        self.write(root, 'books/reviewed-books.json',
                   {'schema': 'iman-reviewed-books-v1', 'books': [self.scopes['ja']]})
        self.write(root, 'materials/catalog.json', self.catalog)
        block = next(block for section in unit['sections'] for block in section['blocks']
                     if block.get('sourceLiteralProof'))
        return unit, block

    def test_all_nineteen_translated_languages_prepare_exact_fifty_lessons(self):
        self.assertEqual(len(self.units), 19)
        self.assertEqual(sum(len(value) for value in self.units.values()), 50)
        for language, units in self.units.items():
            self.assertTrue({'essential-01-002', 'essential-01-003'}.issubset({unit['id'] for unit in units}), language)
            self.assertNotIn('essential-01-001', {unit['id'] for unit in units})
            for unit in units:
                self.assertFalse(unit['provenance']['sourceApprovalCreated'])
                self.assertFalse(unit['provenance']['humanCertification'])
                check_unit(unit, unit, root=ROOT)

    def test_complete_readings_preserve_every_character_except_structural_whitespace(self):
        import re
        for language, units in self.units.items():
            for unit in units:
                row = next(row for row in self.catalog['entries'] if row.get('language') == language and row.get('id') == unit['id'] and row['collection'] == 'essential-hadith')
                payload = json.loads((ROOT / row['json']).read_bytes())
                reader = payload.get('reader', payload)
                actual = unit['title'] + ''.join(block['text'] for section in unit['sections'] for block in section['blocks'])
                self.assertEqual(re.sub(r'\s+', '', actual), re.sub(r'\s+', '', reader['reading']))
                self.assertEqual(unit['sourceReferencePreservation']['lostParagraphs'], 0)

    def test_missing_english_and_french_translator_notes_are_restored(self):
        for language, expected in [('en', 8), ('fr', 5)]:
            unit = next(unit for unit in self.units[language] if unit['lesson'] == 2)
            self.assertEqual(len(unit['provenance']['additionalPublishedNotes']), expected)
            notes = [note for section in unit['sections'] for block in section['blocks']
                     for span in block.get('spans', []) for note in span.get('noteTexts', [])]
            self.assertEqual(len(notes), expected)
        english = self.units['en'][0]
        notes = [note for block in english['sections'][0]['blocks'] for span in block.get('spans', []) for note in span.get('noteTexts', [])]
        self.assertTrue(any('not to be confused' in note for note in notes))

    def test_display_notes_keep_json_field_and_list_order(self):
        reader = {
            'referenceNotes': [{'id': 'r1', 'text': 'Reference one'}, {'id': 'r2', 'text': 'Reference two'}],
            'mainNotes': [{'id': 'm1', 'text': 'Main note'}],
            'title': 'Fixture',
            'readerNotes': [{'id': 'a1', 'text': 'Additional note'}],
            'sections': [
                {'publisherNotes': [{'id': 'p1', 'text': 'Published note'}],
                 'notes': [{'id': 's1', 'text': 'Section note'}]},
                {'notes': [{'id': 's2', 'text': 'Next section'}],
                 'publisherNotes': [{'id': 'p2', 'text': 'Next published note'}]},
            ],
        }
        result = [(section, field, note['id']) for section, field, _, note in note_fields(reader)]
        self.assertEqual(result, [
            (None, 'referenceNotes', 'r1'), (None, 'referenceNotes', 'r2'),
            (None, 'mainNotes', 'm1'), (None, 'readerNotes', 'a1'),
            (0, 'publisherNotes', 'p1'), (0, 'notes', 's1'),
            (1, 'notes', 's2'), (1, 'publisherNotes', 'p2'),
        ])

    def test_current_first_lessons_remain_unbound_instead_of_silently_approved(self):
        selected, report = select(ROOT, self.catalog, self.scopes['fr'])
        self.assertEqual([row['id'] for row in selected], ['essential-01-002', 'essential-01-003', 'essential-01-004'])
        self.assertEqual([row['id'] for row in report['unknownLegacyRows']], ['essential-01-001'])
        self.assertFalse(report['unknownRowsApproved'])

    def test_unknown_later_lesson_does_not_join_from_its_filename(self):
        catalog = deepcopy(self.catalog)
        catalog['entries'].append({'collection': 'essential-hadith', 'language': 'en', 'id': 'essential-01-005', 'chapter': 1, 'lesson': 5, 'status': 'current-app-edition', 'json': 'missing-new-source.json'})
        selected, report = select(ROOT, catalog, self.scopes['en'])
        self.assertNotIn('essential-01-005', [row['id'] for row in selected])
        self.assertIn('essential-01-005', [row['id'] for row in report['unknownLegacyRows']])

    def test_withdrawn_or_held_lesson_is_excluded(self):
        for status in ('held', 'withdrawn', 'draft'):
            catalog = deepcopy(self.catalog)
            row = next(row for row in catalog['entries'] if row.get('language') == 'en' and row.get('id') == 'essential-01-003' and row['collection'] == 'essential-hadith')
            row['status'] = status
            units = generate(ROOT, catalog, self.scopes['en'])
            self.assertEqual([unit['lesson'] for unit in units], [2, 4])

    def test_changed_source_identity_or_review_qualification_fails(self):
        for change in ('source', 'review'):
            catalog = deepcopy(self.catalog)
            if change == 'source':
                row = next(row for row in catalog['entries'] if row.get('language') == 'en' and row.get('id') == 'essential-01-003' and row['collection'] == 'essential-hadith')
                row['json'] = 'different-source.json'
            else:
                catalog['essentialThird1016']['status'] = 'Pending review'
            with self.assertRaises(ValueError):
                generate(ROOT, catalog, self.scopes['en'])

    def test_source_conditions_are_bound_and_retained(self):
        unit = next(unit for unit in self.units['ja'] if unit['lesson'] == 4)
        self.assertIn('materials/hadith/essential-ja/004-sources.json', [value['path'] for value in unit['inputBindings']])
        second = self.units['ja'][0]
        self.assertIn('quranSato', second['provenance']['sourceProvenance'])
        self.assertTrue(any('QuranEnc.com' in block['text'] for block in second['sections'][0]['blocks']))

    def test_literal_exception_requires_exact_source_and_review_inputs(self):
        unit = self.units['ja'][0]
        block = next(block for block in unit['sections'][0]['blocks'] if block.get('sourceLiteralProof'))
        proof = block['sourceLiteralProof']
        self.assertEqual(exact_literal(ROOT, proof), block['text'])
        with self.assertRaisesRegex(ValueError, 'exact repository'):
            check_text(None, block['text'], 'ja', [proof], exact=True)
        altered = deepcopy(proof)
        altered['end'] -= 1
        with self.assertRaises(ValueError):
            check_text(ROOT, block['text'], 'ja', [altered], exact=True)
        altered = deepcopy(proof)
        altered['pointer'] = ['reader', 'sourceProvenance']
        with self.assertRaisesRegex(ValueError, 'reading field'):
            check_text(ROOT, block['text'], 'ja', [altered], exact=True)

    def test_literal_exception_does_not_allow_added_english_or_wrong_language(self):
        unit = self.units['ja'][0]
        block = next(block for block in unit['sections'][0]['blocks'] if block.get('sourceLiteralProof'))
        with self.assertRaisesRegex(ValueError, 'Untranslated Latin'):
            check_text(ROOT, block['text'] + ' Unreviewed extra sentence', 'ja', [block['sourceLiteralProof']])
        with self.assertRaisesRegex(ValueError, 'another language'):
            check_text(ROOT, block['text'], 'ar', [block['sourceLiteralProof']])
        tampered = deepcopy(unit)
        tampered['inputBindings'] = []
        with self.assertRaisesRegex(ValueError, 'not bound'):
            check_unit(tampered, tampered, root=ROOT)

    def test_literal_rejects_caller_inventory_even_when_its_hash_is_bound_to_unit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            unit, block = self.literal_fixture(root)
            proof = block['sourceLiteralProof']
            self.assertEqual(exact_literal(root, proof), block['text'])
            old = proof['inventory']
            path = root / 'materials/caller-inventory.json'
            path.write_bytes((root / old['path']).read_bytes())
            forged = {'path': path.relative_to(root).as_posix(), 'sha256': sha(path.read_bytes())}
            unit['inputBindings'] = [forged if binding == old else binding for binding in unit['inputBindings']]
            for section in unit['sections']:
                for item in section['blocks']:
                    if item.get('sourceLiteralProof'):
                        item['sourceLiteralProof']['inventory'] = forged
            with self.assertRaisesRegex(ValueError, 'active translated-Hadith review inventory'):
                check_unit(unit, unit, root=root)

    def test_literal_requires_active_scope_and_unwithdrawn_review_binding(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _, block = self.literal_fixture(root)
            proof = block['sourceLiteralProof']
            for field, value in [('sourceReviewBindings', []), ('state', 'held'), ('automaticBuild', False)]:
                with self.subTest(field=field):
                    declaration = deepcopy(self.scopes['ja'])
                    declaration[field] = value
                    self.write(root, 'books/reviewed-books.json',
                               {'schema': 'iman-reviewed-books-v1', 'books': [declaration]})
                    with self.assertRaisesRegex(ValueError, 'active translated-Hadith review inventory'):
                        exact_literal(root, proof)
            declaration = deepcopy(self.scopes['ja'])
            declaration['automaticRelease'] = False
            self.write(root, 'books/reviewed-books.json',
                       {'schema': 'iman-reviewed-books-v1', 'books': [declaration]})
            self.assertEqual(exact_literal(root, proof), block['text'])

    def test_literal_revalidates_current_source_and_original_review_qualification(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _, block = self.literal_fixture(root)
            proof = block['sourceLiteralProof']
            for change in ('held', 'removed', 'source', 'review'):
                with self.subTest(change=change):
                    catalog = deepcopy(self.catalog)
                    row = next(row for row in catalog['entries']
                               if (row.get('collection'), row.get('language'), row.get('id'))
                               == ('essential-hadith', 'ja', proof['materialId']))
                    if change == 'held':
                        row['status'] = 'held'
                    elif change == 'removed':
                        catalog['entries'].remove(row)
                    elif change == 'source':
                        row['json'] = 'materials/unreviewed-replacement.json'
                    else:
                        catalog['essentialSecond1003']['scope'] = 'Review withdrawn; private draft only.'
                    self.write(root, 'materials/catalog.json', catalog)
                    with self.assertRaises(ValueError):
                        exact_literal(root, proof)

    def test_literal_proofs_count_each_repeated_source_paragraph(self):
        block = next(block for block in self.units['ja'][0]['sections'][0]['blocks'] if block.get('sourceLiteralProof'))
        text = block['text']
        proof = block['sourceLiteralProof']
        self.assertEqual(check_text(ROOT, text + '\n\n' + text, 'ja', [proof, proof]), text + '\n\n' + text)
        with self.assertRaises(ValueError):
            check_text(ROOT, text + '\n\n' + text, 'ja', [proof])
        with self.assertRaisesRegex(ValueError, 'missing or duplicated'):
            check_text(ROOT, text, 'ja', [proof, proof])

    def test_source_lesson_numbers_do_not_renumber_missing_lessons(self):
        self.assertEqual([unit['sourceLessonNumber'] for unit in self.units['en']], [2, 3, 4])
        unit = deepcopy(self.units['en'][0])
        unit['sourceLessonNumber'] = 1
        with self.assertRaisesRegex(ValueError, 'source position'):
            check_unit(unit, unit, root=ROOT)

    def test_all_language_inventory_distinguishes_legacy_and_missing_sources(self):
        report = inventory(ROOT)
        self.assertEqual(report['languageCount'], 20)
        self.assertEqual(report['scopeCount'], 80)
        self.assertEqual(report['automaticPreparationScopes'], 42)
        scopes = {(row['language'], row['collection']): row for row in report['scopes']}
        self.assertEqual(scopes[('ja', 'hadith')]['eligibleUnits'], 3)
        self.assertEqual(scopes[('ja', 'seerah')]['eligibleUnits'], 0)
        self.assertEqual(scopes[('ja', 'seerah')]['legacyEditionUnits'], 2)
        self.assertEqual(scopes[('fr', 'articles')]['eligibleUnits'], 0)
        self.assertEqual(scopes[('fr', 'articles')]['historicalUnits'], 1)
        self.assertFalse(report['sourceApprovalCreated'])

    def test_unreviewed_fatiha_does_not_block_verified_ikhlas_in_three_languages(self):
        for language in ('ru', 'vi', 'fil'):
            declaration = next(row for row in self.declarations if row['language'] == language and row['collection'] == 'tadabbur-extended')
            selected, report = select(ROOT, self.catalog, declaration)
            self.assertEqual([row['id'] for row in selected], ['112:extended'])
            self.assertTrue({'1:extended', 'fatiha-extended'}.intersection(row['id'] for row in report['unknownLegacyRows']))


if __name__ == '__main__':
    unittest.main()
