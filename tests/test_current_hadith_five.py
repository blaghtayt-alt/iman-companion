"""The omitted Filipino fifth lesson remains the exact reviewed publication."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import current_hadith_five as current
from book_edition_scope import key, select
from build_books import check_unit


class CurrentFifthHadith(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.declaration = next(row for row in json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
                               if (row['language'], row['collection']) == ('fil', 'hadith'))
        cls.record, cls.evidence = current.records(ROOT, cls.declaration)[0]
        cls.row = next(row for row in cls.catalog['entries'] if key(row) == current.IDENTITY)
        cls.unit = current.generate(ROOT, cls.catalog, cls.declaration)[0]
        cls.source = json.loads((ROOT / current.JSON_PATH).read_bytes())

    def test_current_catalogue_registers_the_original_fifth_lesson_once(self):
        self.assertEqual(self.row, current.catalogue_entry())
        selected, _ = select(ROOT, self.catalog, self.declaration)
        self.assertEqual([row['lesson'] for row in selected], [2, 3, 5])
        self.assertEqual(self.unit['sourceLessonNumber'], 5)
        self.assertFalse(self.unit['provenance']['sourceApprovalCreated'])

    def test_complete_reviewed_reader_and_embedded_notes_survive(self):
        actual = self.unit['title'] + ''.join(block['text'] for section in self.unit['sections'] for block in section['blocks'])
        self.assertEqual(re.sub(r'\s+', '', actual), re.sub(r'\s+', '', self.source['reader']))
        self.assertEqual(self.unit['provenance']['sourceReadingSHA256'], self.source['readerSHA256'])
        check_unit(self.unit, self.unit, root=ROOT)

    def test_all_original_quran_spans_keep_exact_words_and_references(self):
        actual = [(span['text'], span['verseKeys'][0]) for section in self.unit['sections']
                  for block in section['blocks'] for span in block['spans'] if span['role'] == 'quran']
        expected = [(self.source['reader'][item['start']:item['end']], item['ref']) for item in self.source['quranSpans']]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 53)

    def test_exact_published_companions_and_arabic_revision_are_bound(self):
        paths = {item['path'] for item in self.unit['inputBindings']}
        self.assertTrue({current.JSON_PATH, current.TEXT_PATH, current.INDEX_PATH,
                         current.ARABIC_PATH, current.ARABIC_MD, current.PROJECTION}.issubset(paths))
        self.assertEqual(self.record['existingPublication']['commit'], current.PUBLICATION)

    def test_changed_or_superseded_source_cannot_reuse_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for binding in self.record['sourceFiles'] + self.record['sourceConditions']:
                path = root / binding['path']; path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / binding['path'], path)
            path = root / current.ARABIC_PATH
            path.write_text('{}', encoding='utf8')
            with self.assertRaises(ValueError):
                current.validate_record(root, self.record, self.row, self.catalog)
        for status in ('superseded', 'withdrawn', 'draft'):
            row = {**self.row, 'status': status}
            with self.assertRaises(ValueError):
                current.validate_record(ROOT, self.record, row, self.catalog)

    def test_false_publication_and_later_publisher_identity_are_checked(self):
        forged = deepcopy(self.record); forged['existingPublication']['commit'] = '0' * 40
        with self.assertRaises(ValueError):
            current.validate_record(ROOT, forged, self.row, self.catalog)
        catalog = deepcopy(self.catalog)
        row = next(row for row in catalog['entries'] if key(row) == current.IDENTITY)
        row['bookReaderUnit'] = {'path': 'later-reader.json', 'sha256': 'a' * 64}
        snap = current.snapshot(ROOT, catalog, '0' * 40)['records'][0]
        self.assertNotIn('bookReaderUnit', snap['catalogEntry'])
        current.validate_record(ROOT, snap, row, catalog)

    def test_existing_typed_reader_is_not_duplicated(self):
        self.assertEqual(current.generate(ROOT, self.catalog, self.declaration,
                                         excluded_catalog_keys={current.IDENTITY}), [])


if __name__ == '__main__':
    unittest.main()
