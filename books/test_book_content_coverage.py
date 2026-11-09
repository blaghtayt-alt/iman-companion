"""Coverage diagnostics are not source approval or release authorization."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from bibliography import native_text
from book_content_coverage import COPY, discover_readers, download_coverage, presentation, scope_coverage
from download_tables import render_ready


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conf = json.loads((Path(__file__).parent / 'config.json').read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
        return path

    def row(self, number, language='ja', **extra):
        ident = f'essential-01-{number:03d}'
        path = f'materials/hadith/essential-{language}/{number:03d}.json'
        self.write(path, {'id': ident, 'language': language, 'reader': {'reading': 'Fixture text'}})
        return {'collection': 'essential-hadith', 'language': language, 'id': ident,
                'chapter': 1, 'lesson': number, 'json': path, **extra}

    def book(self, rows, language='ja', collection='hadith'):
        name = f'Iman_Companion_{language}_{collection}.docx'
        prefix = 'https://github.com/example/test/releases/download/fixture/'
        return {'language': language, 'collection': collection, 'file': name,
                'download': prefix + name, 'pdfDownload': prefix + name[:-5] + '.pdf',
                'sha256': 'a' * 64, 'pdfSha256': 'b' * 64,
                'units': [{'id': row['id'], 'title': self.conf['languages'][language]['titles'][collection]} for row in rows]}

    def test_missing_first_translation_differs_from_an_unbound_installed_first_lesson(self):
        rows = [self.row(number) for number in (2, 3, 4)]
        book = self.book(rows)
        before = deepcopy(book)
        absent = scope_coverage(self.root, 'ja', 'hadith', {'entries': rows}, selected=rows, book=book)
        self.assertEqual(absent['missingCurrent'], [])
        self.assertEqual([row['id'] for row in absent['absentEarlierLessons']], ['essential-01-001'])
        first = self.row(1)
        unbound = scope_coverage(self.root, 'ja', 'hadith', {'entries': [first, *rows]}, selected=rows, book=book)
        self.assertFalse(unbound['absentEarlierLessons'])
        self.assertEqual([(row['id'], row['reason']) for row in unbound['missingCurrent']],
                         [('essential-01-001', 'source-not-bound')])
        self.assertEqual(book, before)
        self.assertFalse(unbound['sourceApprovalCreated'])

    def test_uncatalogued_filipino_fifth_lesson_is_not_silently_ignored_or_approved(self):
        rows = [self.row(number, 'fil') for number in (2, 3)]
        fifth = self.row(5, 'fil')
        result = scope_coverage(self.root, 'fil', 'hadith', {'entries': rows}, selected=rows, book=self.book(rows, 'fil'))
        self.assertEqual(result['unregisteredSourceIds'], [fifth['id']])
        self.assertEqual(result['missingCurrent'][0]['reason'], 'source-not-catalogued')
        self.assertNotIn(fifth['id'], result['selectedIds'])
        self.assertNotIn(fifth['id'], result['includedIds'])
        self.assertEqual([row['lesson'] for row in result['absentEarlierLessons']], [1, 4])

    def test_nested_reader_locale_is_recognized_without_changing_eligibility(self):
        row = self.row(1, 'uz')
        self.write(row['json'], {'id': row['id'], 'reader': {'locale': 'uz', 'main': 'Fixture'}})
        result = scope_coverage(self.root, 'uz', 'hadith', {'entries': [row]}, selected=[], book=None)
        self.assertFalse(result['errors'])
        self.assertEqual(result['missingCurrent'][0]['reason'], 'source-not-bound')
        self.assertFalse(result['selectedIds'])

    def test_uncatalogued_extended_quran_reader_is_reported_but_archive_is_not(self):
        self.write('materials/tadabbur/ja/extended/075.json', {'surah': 75, 'language': 'ja', 'mode': 'extended'})
        self.write('materials/tadabbur/ja/archive/076.json', {'surah': 76, 'language': 'ja', 'mode': 'extended'})
        result = scope_coverage(self.root, 'ja', 'tadabbur-extended', {'entries': []}, selected=[])
        self.assertEqual(result['sourceIds'], ['75:extended'])
        self.assertEqual(result['unregisteredSourceIds'], ['75:extended'])
        self.assertFalse(result['selectedIds'])

    def test_retired_file_and_archive_copy_do_not_reenter_current_coverage(self):
        retired = self.row(1, status='superseded')
        current = self.row(2)
        self.write('materials/hadith/essential-ja/sources/003.json', {'id': 'essential-01-003', 'language': 'ja'})
        self.write('materials/hadith/essential-ja/OLD-004.json', {'id': 'essential-01-004', 'language': 'ja'})
        result = scope_coverage(self.root, 'ja', 'hadith', {'entries': [retired, current]}, selected=[current], book=self.book([current]))
        self.assertEqual(result['sourceIds'], [current['id']])
        self.assertEqual(result['missingCurrent'], [])

    def test_competing_path_is_reported_without_treating_it_as_current(self):
        row = self.row(2)
        row['json'] = 'materials/approved/ja/lesson-2.json'
        result = scope_coverage(self.root, 'ja', 'hadith', {'entries': [row]}, selected=[row], book=self.book([row]))
        self.assertEqual(len(result['competingSources']), 1)
        self.assertEqual(result['competingSources'][0]['reason'], 'different-from-current-catalogue-source')
        self.assertFalse(result['unregisteredSourceIds'])

    def test_newly_selected_source_is_not_labelled_included_before_replacement_release(self):
        rows = [self.row(number) for number in (1, 2, 3, 4)]
        book = self.book(rows[1:])
        result = scope_coverage(self.root, 'ja', 'hadith', {'entries': rows}, selected=rows, book=book)
        self.assertEqual(result['selectedIds'], [row['id'] for row in rows])
        self.assertEqual(result['includedIds'], [row['id'] for row in rows[1:]])
        self.assertEqual(result['missingCurrent'][0]['reason'], 'awaiting-book-release')
        rendered = presentation(result, self.conf['languages']['ja'])
        self.assertEqual(rendered['includedLabel'], '収録: ハディース 2–4')
        self.assertEqual(rendered['notes'], ['更新版の公開待ち: ハディース 1'])

    def test_french_review_conflict_requires_exact_exclusion_and_current_source_bytes(self):
        first = self.row(1, 'fr')
        status = 'COMPLETE_AUTHOR558_SUCCESSOR_PENDING_ACTUAL_DISTINCT_FINAL; historical reviews'
        self.write(first['json'], {'id': first['id'], 'language': 'fr', 'reading': {'reviewStatus': status}})
        first['markdown'] = 'materials/hadith/essential-fr/001.md'
        self.write(first['markdown'], 'Exact current reader')
        second = self.row(2, 'fr')
        bindings = [{'path': first[name], 'sha256': hashlib.sha256((self.root / first[name]).read_bytes()).hexdigest()}
                    for name in ('json', 'markdown')]
        self.write('books/source-projections/current-hadith-first.json', {
            'schema': 'iman-current-hadith-first-source-bindings-v1', 'records': [],
            'sourceApprovalCreated': False,
            'excludedCurrentRows': [{'language': 'fr', 'id': first['id'], 'sourceFiles': bindings,
                                     'reviewStatus': status, 'sourceApprovalCreated': False,
                                     'reason': 'Current final review is pending.'}]})
        arguments = (self.root, 'fr', 'hadith', {'entries': [first, second]})
        result = scope_coverage(*arguments, selected=[second], book=self.book([second], 'fr'))
        self.assertEqual(result['missingCurrent'][0]['reason'], 'review-incomplete')
        self.assertEqual(result['missingCurrent'][0]['reviewEvidence']['sourceFiles'], bindings)
        self.assertEqual(presentation(result, self.conf['languages']['fr'])['notes'],
                         ['Vérification finale incomplète : Hadith 1'])
        self.assertFalse(result['errors'])
        self.write(first['markdown'], 'Changed current reader')
        stale = scope_coverage(*arguments, selected=[second], book=self.book([second], 'fr'))
        self.assertEqual(stale['state'], 'check-pending')
        self.assertEqual(stale['missingCurrent'][0]['reason'], 'source-not-bound')
        self.assertEqual(stale['errors'][0]['stage'], 'review-exclusion')

    def test_older_seerah_edition_is_not_a_missing_new_adult_chapter(self):
        old = {'collection': 'seerah', 'language': 'ar', 'id': '1', 'chapter': 1}
        new = {'collection': 'seerah', 'language': 'ar', 'id': 'new-seerah001', 'chapter': 1, 'edition': 'new-adult'}
        result = scope_coverage(self.root, 'ar', 'seerah', {'entries': [old, new]}, selected=[new], book=self.book([new], 'ar', 'seerah'))
        self.assertEqual(result['legacyExcluded'], 1)
        self.assertEqual(result['sourceIds'], ['new-seerah001'])
        self.assertFalse(result['missingCurrent'])

    def test_bad_reader_identity_stays_visible_as_a_diagnostic_error(self):
        row = self.row(2)
        self.write('materials/hadith/essential-ja/001.json', {'id': 'essential-01-099', 'language': 'ja'})
        result = scope_coverage(self.root, 'ja', 'hadith', {'entries': [row]}, selected=[row], book=self.book([row]))
        self.assertEqual(result['state'], 'check-pending')
        self.assertIn('identity', result['errors'][0]['reason'])
        self.assertNotIn('essential-01-099', result['sourceIds'])

    def test_native_numbered_labels_cover_all_languages_without_english_fallback(self):
        self.assertEqual(set(COPY), set(self.conf['languages']))
        for language in COPY:
            with self.subTest(language=language):
                rows = [self.row(number, language) for number in (1, 2, 3, 4)]
                result = scope_coverage(self.root, language, 'hadith', {'entries': rows}, selected=rows[1:], book=self.book(rows[1:], language))
                output = presentation(result, self.conf['languages'][language])
                for text in [*COPY[language], output['includedLabel'], output['statusLabel'], *output['notes'], *output['unitLabels'].values()]:
                    native_text(text, language)
                self.assertEqual(len(output['unitLabels']), 3)
                self.assertEqual(len(output['notes']), 1)

    def test_download_tables_keep_verified_hashes_and_show_exact_included_numbers(self):
        rows = [self.row(number) for number in (1, 2, 3, 4)]
        ready = {('ja', 'hadith'): self.book(rows[1:])}
        before = deepcopy(ready)
        result = scope_coverage(self.root, 'ja', 'hadith', {'entries': rows}, selected=rows, book=ready[('ja', 'hadith')])
        result['presentation'] = presentation(result, self.conf['languages']['ja'])
        table, pages = render_ready(self.conf, ready, 'example/test', coverage={('ja', 'hadith'): result})
        self.assertIn('収録: ハディース 2–4', pages['ja'])
        self.assertIn('更新版の公開待ち: ハディース 1', pages['ja'])
        self.assertNotIn('†', table)
        self.assertIn('Each language page lists the exact included lesson or surah numbers', table)
        self.assertEqual(ready, before)
        result['includedIds'].append('essential-01-001')
        with self.assertRaisesRegex(ValueError, 'differs from the verified book'):
            render_ready(self.conf, ready, 'example/test', coverage={('ja', 'hadith'): result})

    def test_public_metadata_uses_download_ids_even_when_selected_source_inventory_grows(self):
        rows = [self.row(number) for number in (1, 2, 3)]
        self.write('materials/catalog.json', {'entries': rows})
        self.write('books/reviewed-books.json', {'books': [{'language': 'ja', 'collection': 'hadith'}]})
        ready = {('ja', 'hadith'): self.book(rows[1:])}
        before = deepcopy(ready)
        result = download_coverage(self.root, ready, conf=self.conf)[('ja', 'hadith')]
        self.assertEqual(result['includedIds'], [row['id'] for row in rows[1:]])
        self.assertEqual(result['missingCurrent'][0]['reason'], 'awaiting-book-release')
        self.assertEqual(ready, before)


if __name__ == '__main__':
    unittest.main()
