"""Real legacy adapters combined with synthetic, explicitly labelled approvals.

Every publisher receipt below is a test fixture, never a real source approval.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import adapt_ar_articles
import adapt_ar_hadith
import adapt_ar_seerah
from publish_approved_material import apply, bytes_json
from published_library import sha
from historical_book_fixture import pinned_fixture

ADAPTERS = {'articles': adapt_ar_articles, 'seerah': adapt_ar_seerah, 'hadith': adapt_ar_hadith}
SOURCE_COLLECTIONS = {'articles': 'articles', 'seerah': 'seerah', 'hadith': 'essential-hadith'}


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes_json(value))
    return path


class MixedMaterialAdapterChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full_catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.declarations = json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
        cls.conf = json.loads((ROOT / 'books/config.json').read_bytes())

    @contextmanager
    def scope(self, collection):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            declaration = deepcopy(next(d for d in self.declarations
                                        if d['language'] == 'ar' and d['collection'] == collection))
            catalog = deepcopy(self.full_catalog)
            rows = [r for r in catalog['entries'] if r.get('collection') == SOURCE_COLLECTIONS[collection]
                    and r.get('language') == 'ar' and adapt_ar_articles.current_record(r)
                    and (collection != 'seerah' or r.get('edition') == 'new-adult')]
            paths = {declaration['projection'], declaration['materialIndex'], 'books/config.json',
                     'books/assets/quran-arabic.json', self.conf['quranText']['path'], self.conf['surahNames']['path']}
            paths.update(r[k] for r in rows for k in ('json', 'markdown') if r.get(k))
            if collection == 'hadith':
                projection = json.loads((ROOT / declaration['projection']).read_bytes())
                paths.update(c[k] for c in projection['chapters'] for k in ('json', 'markdown'))
            for relative in paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            if collection == 'articles':
                # Keep the old citation projection and its pinned inputs as a
                # historical code fixture; never refresh production review pins.
                projection=json.loads((root/declaration['projection']).read_bytes())
                index=json.loads((root/declaration['materialIndex']).read_bytes())
                for article in projection['articles']:
                    row=next(r for r in rows if r['id']==article['id'])
                    item=next(r for r in index['articles'] if r['id']==article['id'])
                    row.update(title=article['title'],sourceHashes=[article['sourceSHA256']],readingSHA256=article['readingSHA256'])
                    item.update(title=article['title'],preparedSourceSHA256=article['sourceSHA256'],readingSHA256=article['readingSHA256'])
                    (root/row['markdown']).write_bytes(pinned_fixture(ROOT,row['markdown'],article['materialSHA256']))
                write(root,declaration['materialIndex'],index)
            # The fixtures explicitly pin shared bytes even if an older checkout
            # has not yet received the production declaration hash.
            if collection != 'hadith':
                declaration['materialIndexSHA256'] = sha((root / declaration['materialIndex']).read_bytes())
            write(root, 'materials/catalog.json', catalog)
            write(root, 'books/reviewed-books.json', {'schema': 'iman-reviewed-books-v1', 'books': [declaration]})
            yield root, declaration, rows

    def publish_fixture(self, root, collection, rows, *, correction=False):
        entry = deepcopy(rows[0])
        if not correction:
            entry['id'] = {'articles': 'article-fixture-approved', 'seerah': 'new-seerah099', 'hadith': 'essential-99-001'}[collection]
            entry['number'] = 99
            if collection in {'seerah', 'hadith'}:
                entry['chapter'] = 99
            if collection == 'hadith':
                entry['lesson'] = 1
        for key in ('markdown', 'index', 'readingSHA256', 'sourceChapterId', 'bookReaderUnit'):
            entry.pop(key, None)
        ident = str(entry['id'])
        source = f'materials/test-fixture/{collection}/{ident}.json'
        review = f'materials/test-fixture/{collection}/{ident}-review.json'
        reader = f'materials/test-fixture/{collection}/{ident}-reader.json'
        text = 'هذا نص اختبار اصطناعي فقط، وليس موافقة أو مادة منشورة حقيقية.'
        write(root, source, {'fixtureOnly': True, 'text': text})
        write(root, review, {'fixtureOnly': True, 'reviewer': 'TEST ONLY; no real review or publication'})
        source_binding = {'path': source, 'sha256': sha((root / source).read_bytes())}
        entry.update(json=source, current=True, sourceHashes=[source_binding['sha256']], title='مادة اختبارية', originalTitle='مادة اختبارية')
        material = {k: entry[k] for k in ('collection', 'language', 'id')}
        order = (entry['chapter'] * 1000 + entry['lesson'] if collection == 'hadith'
                 else entry['chapter'] if collection == 'seerah' else entry.get('number') or entry['position'])
        # Deliberately use a different unit ID from the catalogue ID. Exclusion
        # must follow exact catalogue identity, not a reader filename heuristic.
        unit = {'schema': 'iman-book-unit-v1', 'language': 'ar', 'collection': collection,
                'id': 'fixture-reader-' + ident, 'order': order, 'title': 'مادة اختبارية',
                'complete': True, 'reviewGate': 'published-current', 'sourceHashes': [source_binding['sha256']],
                'readerTextSHA256': sha(text.encode()), 'inputBindings': [source_binding],
                'catalogBindings': [material], 'sections': [{'blocks': [{'kind': 'paragraph', 'text': text}]}]}
        if collection == 'hadith':
            unit.update(hadithEdition='new-extended', chapter=entry['chapter'], lesson=entry['lesson'],
                        ordering={'kind': 'chapter-lesson', 'chapter': entry['chapter'], 'lesson': entry['lesson']})
            unit['sections'][0]['blocks'][0]['citations'] = [{'type': 'hadith', 'book': 'muslim', 'number': '1'}]
        if collection == 'seerah':
            unit.update(chapter=entry['chapter'], ordering={'kind': 'global-sequence', 'sequence': order})
        write(root, reader, unit)
        handoff = {'schema': 'iman-approved-material-publication-v1',
                   'expectedCatalogSHA256': sha((root / 'materials/catalog.json').read_bytes()),
                   'catalogEntry': entry, 'sourceBindings': [source_binding], 'canonicalOrder': order,
                   'readerUnit': {'path': reader, 'sha256': sha((root / reader).read_bytes())},
                   'approval': {'decision': 'approved', 'approvalId': 'TEST-FIXTURE-ONLY-' + collection + ident,
                                'reviewer': {'kind': 'fixture', 'id': 'NO REAL APPROVAL'}, 'wholeMaterial': True,
                                'material': material, 'readerTextSHA256': unit['readerTextSHA256'],
                                'reviewArtifacts': [{'path': review, 'sha256': sha((root / review).read_bytes())}]}}
        path = write(root, 'fixture-handoff.json', handoff)
        receipt = apply(root, path)
        self.assertFalse(receipt['sourceApprovalCreated'])
        self.assertFalse(receipt['scopeReleaseHoldsChanged'])
        return (entry['collection'], entry['language'], ident), receipt

    def generate(self, root, declaration, excluded):
        catalog = json.loads((root / 'materials/catalog.json').read_bytes())
        return ADAPTERS[declaration['collection']].generate(root, catalog, declaration,
                                                         excluded_catalog_keys=excluded)

    def index(self, root, collection, count):
        result = subprocess.run([sys.executable, str(ROOT / 'books/index_units.py'), '--root', str(root),
                                 '--commit', '0' * 40, '--language', 'ar', '--collection', collection],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((root / 'books/manifest.json').read_bytes())
        self.assertEqual(len(manifest['units']), count)
        return manifest

    def test_approved_additions_extend_each_legacy_book_without_projection_regeneration(self):
        for collection in ADAPTERS:
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                key, receipt = self.publish_fixture(root, collection, rows)
                with self.assertRaises(ValueError):
                    self.generate(root, declaration, ())  # Original whole-scope failure.
                generated = self.generate(root, declaration, {key})
                self.assertEqual({u['id'] for u in generated}, {r['id'] for r in rows})
                manifest = self.index(root, collection, len(rows) + 1)
                self.assertIn(receipt['readerUnit']['path'], {u['path'] for u in manifest['units']})

    def test_approved_corrections_replace_one_legacy_identity_and_keep_remaining_sources_bound(self):
        for collection in ADAPTERS:
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                key, receipt = self.publish_fixture(root, collection, rows, correction=True)
                with self.assertRaises(ValueError):
                    self.generate(root, declaration, ())
                generated = self.generate(root, declaration, {key})
                self.assertEqual({u['id'] for u in generated}, {r['id'] for r in rows if str(r['id']) != key[2]})
                self.index(root, collection, len(rows))
                untouched = next(r for r in rows if str(r['id']) != key[2])
                path = root / untouched.get('json', untouched.get('markdown'))
                path.write_bytes(path.read_bytes() + b' ')
                with self.assertRaises(ValueError):
                    self.generate(root, declaration, {key})

    def test_unknown_new_members_are_not_hidden_by_an_approved_exclusion(self):
        for collection in ADAPTERS:
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                key, _ = self.publish_fixture(root, collection, rows)
                catalog = json.loads((root / 'materials/catalog.json').read_bytes())
                unknown = deepcopy(rows[0])
                unknown['id'] = 'unknown-unapproved-member'
                catalog['entries'].append(unknown)
                write(root, 'materials/catalog.json', catalog)
                with self.assertRaises(ValueError):
                    self.generate(root, declaration, {key})
                if collection == 'articles':
                    unknown['translationStatus'] = 'current-unapproved-fixture'
                    write(root, 'materials/catalog.json', catalog)
                    with self.assertRaisesRegex(ValueError, 'no eligible legacy source or approved publisher snapshot'):
                        self.generate(root, declaration, {key})

    def test_exclusion_requires_an_immutable_whole_material_publisher_approval(self):
        for collection in ADAPTERS:
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                ordinary = (rows[0]['collection'], 'ar', str(rows[0]['id']))
                with self.assertRaisesRegex(ValueError, 'exact approved publisher snapshot'):
                    self.generate(root, declaration, {ordinary})
                key, receipt = self.publish_fixture(root, collection, rows)
                path = root / receipt['readerUnit']['path']
                reader = json.loads(path.read_bytes())
                reader['title'] = 'تغيير بعد الموافقة الاختبارية'
                write(root, receipt['readerUnit']['path'], reader)
                with self.assertRaisesRegex(ValueError, 'Changed edition review/source input'):
                    self.generate(root, declaration, {key})

    def test_per_material_approval_cannot_excuse_a_shared_index_or_chapter_change(self):
        for collection in ADAPTERS:
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                key, _ = self.publish_fixture(root, collection, rows, correction=True)
                path = root / declaration['materialIndex']
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                with self.assertRaisesRegex(ValueError, 'shared material index'):
                    self.generate(root, declaration, {key})
                if collection == 'hadith':
                    path.write_bytes(original)
                    projection = json.loads((root / declaration['projection']).read_bytes())
                    chapter = root / projection['chapters'][0]['json']
                    chapter.write_bytes(chapter.read_bytes() + b' ')
                    with self.assertRaisesRegex(ValueError, 'shared chapter binding changed'):
                        self.generate(root, declaration, {key})

    def test_article_and_seerah_mixed_scopes_require_an_explicit_shared_index_hash(self):
        for collection in ('articles', 'seerah'):
            with self.subTest(collection=collection), self.scope(collection) as (root, declaration, rows):
                key, _ = self.publish_fixture(root, collection, rows)
                declaration.pop('materialIndexSHA256')
                with self.assertRaisesRegex(ValueError, 'shared material index'):
                    self.generate(root, declaration, {key})


if __name__ == '__main__':
    unittest.main()
