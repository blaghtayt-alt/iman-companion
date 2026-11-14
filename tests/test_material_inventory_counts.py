"""Audit inventory counts against actual readers, without conferring approval.

Canonical numbered reader JSON files count once. Markdown/plain-text copies,
source envelopes, source companions and indexes do not count as extra lessons.
The checks follow the current corpus rather than fixing today's lesson counts.
"""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
LABELS = {
    'ar': 'Arabic', 'en': 'English', 'fr': 'French', 'tr': 'Turkish',
    'id': 'Indonesian', 'ms': 'Malay', 'pt-BR': 'Brazilian Portuguese',
    'ur': 'Urdu', 'bn': 'Bengali', 'hi': 'Hindi', 'ru': 'Russian',
    'es': 'Spanish', 'fa': 'Persian', 'de': 'German',
    'zh-CN': 'Simplified Chinese', 'uz': 'Uzbek', 'th': 'Thai',
    'vi': 'Vietnamese', 'ja': 'Japanese', 'fil': 'Filipino',
}


def canonical_readers(language):
    folder = ROOT / 'materials/hadith' / ('essential-' + language)
    readers = []
    for path in sorted(folder.rglob('*.json')):
        if not re.fullmatch(r'\d{3}\.json', path.name):
            continue
        if path.parent == folder:
            chapter = 1
        elif (path.parent.parent == folder
              and re.fullmatch(r'\d{2}', path.parent.name)):
            chapter = int(path.parent.name)
        else:
            continue
        readers.append((path, chapter, int(path.stem)))
    return readers


class MaterialInventoryCounts(unittest.TestCase):
    def test_essential_counts_match_numbered_readers_in_every_language(self):
        languages = json.loads((ROOT / 'books/config.json').read_bytes())['languages']
        self.assertEqual(set(languages), set(LABELS))
        text = (ROOT / 'materials/README.md').read_text(encoding='utf8')
        rows = re.findall(r'^\| essential-hadith \| ([^|]+) \| ([^|]+) \|$',
                          text, flags=re.MULTILINE)
        self.assertEqual(len(rows), len(LABELS), 'Missing or duplicate inventory language')
        table = {label.strip(): value.strip() for label, value in rows}
        self.assertEqual(set(table), set(LABELS.values()))
        for language, label in LABELS.items():
            with self.subTest(language=language):
                readers = canonical_readers(language)
                self.assertTrue(readers, 'No canonical reader files for ' + language)
                match = re.fullmatch(r'(\d+) lessons?(?: pages, (\d+) chapters)?',
                                     table[label])
                self.assertIsNotNone(match, 'Unrecognized inventory count: ' + table[label])
                self.assertEqual(int(match[1]), len(readers),
                                 'Count actual files, not the highest lesson number')
                if match[2] is not None:
                    self.assertEqual(int(match[2]), len({chapter for _, chapter, _ in readers}))

    def test_numbered_files_have_matching_unique_lesson_identities(self):
        catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        for language in LABELS:
            identities = []
            for path, chapter, lesson in canonical_readers(language):
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    value = json.loads(path.read_bytes())
                    expected = f'essential-{chapter:02d}-{lesson:03d}'
                    actual_id = value.get('id')
                    if (actual_id is None and value.get('schema') ==
                            'essential-finite-language-author-successor581-v1'):
                        # Preserve the original reviewed wrapper: this source
                        # calls its identity "unit", not "id". Its catalogue
                        # and normalized reader must still have exact approval.
                        actual_id = value.get('unit')
                        relative = path.relative_to(ROOT).as_posix()
                        rows = [row for row in catalog['entries']
                                if row.get('json') == relative]
                        self.assertEqual(len(rows), 1)
                        self.assertEqual((rows[0]['collection'], rows[0]['language'], rows[0]['id']),
                                         ('essential-hadith', language, expected))
                        from book_edition_scope import typed_basis
                        self.assertIsNotNone(typed_basis(ROOT, rows[0]))
                    if actual_id is None:
                        relative=path.relative_to(ROOT).as_posix()
                        rows=[row for row in catalog['entries'] if row.get('json')==relative]
                        if rows:
                            # Registration may preserve an original path-only
                            # reader. Require its exact typed approval instead
                            # of requiring that it stay unregistered forever.
                            self.assertEqual(len(rows),1)
                            self.assertEqual((rows[0]['collection'],rows[0]['language'],str(rows[0]['id'])),('essential-hadith',language,expected))
                            from book_edition_scope import typed_basis
                            self.assertIsNotNone(typed_basis(ROOT,rows[0]))
                            actual_id=str(rows[0]['id'])
                        else:
                            from book_content_coverage import discover_readers
                            discovery=discover_readers(ROOT,[language],catalog)
                            candidates=[r for r in discovery['readers'] if r.get('json')==relative]
                            self.assertEqual(len(candidates),1)
                            self.assertEqual(candidates[0]['id'],expected)
                            actual_id=candidates[0]['id']
                    self.assertEqual(actual_id, expected)
                    reader = value.get('reader', {})
                    reader_language = reader.get('locale', language) if isinstance(reader, dict) else language
                    actual_language = value.get('language', reader_language)
                    self.assertEqual(actual_language, language)
                    identities.append(expected)
            self.assertEqual(len(identities), len(set(identities)),
                             'Duplicate canonical reader identity in ' + language)

    def test_path_only_reader_transitions_to_exact_registered_approval(self):
        from test_source_publisher import SourcePublishingTests
        from publish_approved_material import apply
        from published_library import sha
        fixture=SourcePublishingTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        _,handoff=fixture.handoff(text='Reviewed fixture reader.')
        source='materials/hadith/essential-en/006.json';ident='essential-01-006'
        fixture.write(source,{'language':'en','text':'Reviewed fixture reader.','fixture':'No real approval'})
        binding={'path':source,'sha256':sha((fixture.root/source).read_bytes())}
        material={'collection':'essential-hadith','language':'en','id':ident}
        unit=json.loads((fixture.root/handoff['readerUnit']['path']).read_bytes())
        unit.update(language='en',collection='hadith',id=ident,title='Hadith 6',order=6,chapter=1,lesson=6,hadithEdition='new-extended',sourceHashes=[binding['sha256']],inputBindings=[binding],catalogBindings=[material])
        unit['sections'][0]['blocks'][0]['citations']=[{'type':'hadith','book':'muslim','number':'1'}]  # Synthetic reference fixture only.
        reader=fixture.write(handoff['readerUnit']['path'],unit)
        handoff.update(catalogEntry={**material,'json':source,'current':True,'chapter':1,'lesson':6},sourceBindings=[binding],canonicalOrder=6)
        handoff['approval']['material']=material;handoff['readerUnit']['sha256']=sha(reader.read_bytes())
        file=fixture.write('handoff.json',handoff)
        with patch(__name__+'.ROOT',fixture.root),patch.dict(LABELS,{'en':'English'},clear=True):
            self.test_numbered_files_have_matching_unique_lesson_identities()
            receipt=apply(fixture.root,file);self.assertFalse(receipt['sourceApprovalCreated'])
            scope=next(row for row in json.loads((fixture.root/'books/reviewed-books.json').read_bytes())['books'] if row['language']=='en')
            self.assertTrue(scope['requireActualWordLayout']);self.assertFalse(scope['automaticRelease'])
            self.test_numbered_files_have_matching_unique_lesson_identities()
            fixture.write(source,{'language':'en','text':'Unreviewed later edit'})
            from book_edition_scope import typed_basis
            row=json.loads((fixture.root/'materials/catalog.json').read_bytes())['entries'][0]
            with self.assertRaisesRegex(ValueError,'Changed edition review/source input'):
                typed_basis(fixture.root,row)

    def test_japanese_first_lesson_source_presence_is_not_render_loss(self):
        source_ids = {f'essential-{chapter:02d}-{lesson:03d}'
                      for _, chapter, lesson in canonical_readers('ja')}
        catalog = json.loads((ROOT / 'docs/books/catalog.json').read_bytes())
        books = [book for book in catalog['languages']['ja']['books']
                 if book['collection'] == 'hadith']
        self.assertEqual(len(books), 1)
        coverage = books[0]['coverage']
        first = 'essential-01-001'
        absent = {item['id']: item['reason'] for item in coverage['absentEarlierLessons']}
        if first in source_ids:
            self.assertNotIn(first, absent,
                             'A newly installed first reader must no longer be labelled absent')
        else:
            self.assertEqual(absent.get(first), 'current-source-not-installed')
            for field in ('sourceIds', 'selectedIds', 'includedIds'):
                self.assertNotIn(first, coverage[field])
            self.assertNotIn(first, {item['id'] for item in coverage['missingCurrent']},
                             'An absent source is not a rendered lesson awaiting publication')


if __name__ == '__main__':
    unittest.main()
