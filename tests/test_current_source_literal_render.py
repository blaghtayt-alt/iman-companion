"""Real restored citations retain exact source strings through DOCX footnotes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from docx import Document
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import current_reviewed_quran as current
from build_books import Footnotes, check_unit, embed_fonts, checked_source_links, add_source_link_text
from check_outputs import validate_footnotes, validate_source_hyperlinks, validate_pdf_source_hyperlinks
from source_literal_text import check_bound_text, check_text, proof_list, exact_literal
from reader_xml import body_text
from historical_book_fixture import copy_projection_fixture
from restore_source_hyperlinks import restore as restore_source_hyperlinks


class CurrentLiteralRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.declaration = next(row for row in json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
                               if (row['language'], row['collection']) == ('ur', 'tadabbur-extended'))
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.source_root=Path(cls.temp.name)
        inventory=current.read(ROOT,current.PROJECTION)
        copy_projection_fixture(ROOT,cls.source_root,inventory,
            [current.PROJECTION,'materials/catalog.json','books/reviewed-books.json',
             'materials/translation-status.json','books/config.json','books/assets/quran-arabic.json','books/assets/surah-names.json','books/assets/surah-names-native-20261107.json']+
             [b['path'] for b in cls.declaration['sourceReviewBindings']])
        cls.record, cls.evidence = current.records(cls.source_root, cls.declaration)[0]
        cls.unit = current.normalize(cls.source_root, cls.catalog, cls.record['catalogEntry'], cls.record, cls.evidence)
        notes = [(text, proof_list(proofs)) for section in cls.unit['sections']
                 for block in section['blocks'] for span in block.get('spans', [])
                 for text, proofs in zip(span.get('noteTexts', []), span.get('noteLiteralProofs', []))
                 if proofs and 'https://' in text]
        cls.text, cls.proofs = notes[0]

    def test_exact_source_note_keeps_original_publisher_reference_and_url(self):
        check_bound_text(self.source_root, self.text, self.unit, self.proofs)
        with tempfile.TemporaryDirectory() as temporary:
            doc = Document(); anchor = doc.add_paragraph('اردو')
            notes = Footnotes(doc, 'ur', 'Iman Book Noto Nastaliq Urdu', 'Iman Book Noto Naskh Arabic', source_root=self.source_root)
            notes.add(anchor, self.text, source_literal_proofs=self.proofs)
            target = Path(temporary) / 'notes.docx'; doc.save(target); embed_fonts(target, {}, notes.root)
            with zipfile.ZipFile(target) as archive:
                body = etree.fromstring(archive.read('word/document.xml'))
                actual = etree.fromstring(archive.read('word/footnotes.xml'))
            self.assertEqual(notes.texts, [self.text])
            validate_footnotes(actual, body, notes.texts, 'ur', source_literal_proofs=notes.literal_proofs, root=self.source_root)
            with self.assertRaises(ValueError):
                validate_footnotes(actual, body, notes.texts, 'ur', root=self.source_root)
            tampered = deepcopy(actual)
            node = next(node for node in tampered.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if node.text and 'https://' in node.text)
            node.text += ' Unreviewed extra sentence'
            with self.assertRaises(ValueError):
                validate_footnotes(tampered, body, notes.texts, 'ur', source_literal_proofs=notes.literal_proofs, root=self.source_root)

    def test_other_materials_and_unknown_english_cannot_borrow_a_literal_exception(self):
        forged = deepcopy(self.proofs); forged[0]['materialId'] = 'other-material'
        with self.assertRaises(ValueError):
            check_bound_text(self.source_root, self.text, self.unit, forged)
        with self.assertRaises(ValueError):
            check_text(self.source_root, self.text + ' Unreviewed extra sentence', 'ur', self.proofs)
        with self.assertRaises(ValueError):
            check_bound_text(self.source_root, self.text, {**self.unit, 'inputBindings': []}, self.proofs)

    def test_changed_note_proof_array_or_credit_is_rejected(self):
        altered = deepcopy(self.unit)
        span = next(span for section in altered['sections'] for block in section['blocks']
                    for span in block.get('spans', []) if span.get('noteLiteralProofs'))
        span['noteLiteralProofs'].append(None)
        with self.assertRaisesRegex(ValueError, 'do not match'):
            check_unit(altered, altered, root=self.source_root)
        altered = deepcopy(self.unit)
        credit = next(block['translationCredit'] for section in altered['sections']
                      for block in section['blocks'] if block.get('translationCredit'))
        credit['text'] += ' Invented attribution'
        with self.assertRaises(ValueError):
            check_unit(altered, altered, root=self.source_root)

    def test_cached_validation_detects_same_size_source_edit_with_restored_mtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {item['path'] for item in self.record['sourceFiles'] + self.record['sourceConditions']}
            paths.update({current.PROJECTION, 'materials/catalog.json', 'books/reviewed-books.json',
                          'materials/translation-status.json'})
            for relative in paths:
                target = root / relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.source_root / relative, target)
            check_text(root, self.text, 'ur', self.proofs)
            path = root / self.proofs[0]['source']['path']; before = path.stat(); raw = path.read_bytes()
            self.assertIn(b'QuranEnc', raw)
            path.write_bytes(raw.replace(b'QuranEnc', b'QuranEnx', 1))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'Changed edition'):
                check_text(root, self.text, 'ur', self.proofs)

    def source_link(self):
        import current_hadith_first as first
        declaration = next(row for row in json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
                           if (row['language'], row['collection']) == ('uz', 'hadith'))
        unit = first.generate(ROOT, self.catalog, declaration)[0]
        block = next(block for section in unit['sections'] for block in section['blocks'] if block.get('hyperlinks'))
        return unit, block

    def test_required_source_link_survives_docx_with_exact_label_and_target(self):
        unit, block = self.source_link()
        checked_source_links(unit, {'sourceOnlyContext': True}, block, ROOT)
        doc = Document(); paragraph = doc.add_paragraph()
        add_source_link_text(paragraph, block['text'], block['hyperlinks'], 'uz',
                             'Iman Book Inter', 'Iman Book Noto Naskh Arabic')
        expected = [{'text': block['text'][link['start']:link['end']], 'url': link['url'],
                     'sourceLiteralProof': link['sourceLiteralProof']} for link in block['hyperlinks']]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-credit.docx'; doc.save(path)
            with zipfile.ZipFile(path) as archive:
                body = etree.fromstring(archive.read('word/document.xml'))
                relationships = etree.fromstring(archive.read('word/_rels/document.xml.rels'))
            self.assertEqual(body_text(body).strip(), block['text'])
            validate_source_hyperlinks(body, relationships, expected, 'uz', ROOT)
            target = next(item for item in relationships if item.get('Target') == expected[0]['url'])
            target.set('Target', 'https://example.invalid/changed')
            with self.assertRaisesRegex(ValueError, 'changed or disappeared'):
                validate_source_hyperlinks(body, relationships, expected, 'uz', ROOT)
        validate_pdf_source_hyperlinks([link['url'] for link in expected], expected)
        with self.assertRaisesRegex(ValueError, 'missing from PDF'):
            validate_pdf_source_hyperlinks([], expected)

    def test_source_links_require_exact_context_and_bound_original_url(self):
        unit, block = self.source_link()
        with self.assertRaises(ValueError):
            checked_source_links(unit, {}, block, ROOT)
        block['hyperlinks'][0]['url'] += '/unreviewed'
        with self.assertRaises(ValueError):
            checked_source_links(unit, {'sourceOnlyContext': True}, block, ROOT)

    def test_pdf_root_slash_is_equivalent_but_destination_changes_are_not(self):
        expected = [{'url': 'https://muslim.uz'}, {'url': 'https://muslim.uz/article?source=1#credit'}]
        validate_pdf_source_hyperlinks(['https://muslim.uz/', expected[1]['url']], expected)
        for changed in ('http://muslim.uz/', 'https://other.example/', 'https://muslim.uz/other',
                        'https://muslim.uz/?source=1', 'https://muslim.uz/#credit'):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    validate_pdf_source_hyperlinks([changed, expected[1]['url']], expected)

    def source_link_fixture(self, path):
        unit, block = self.source_link()
        checked_source_links(unit, {'sourceOnlyContext': True}, block, ROOT)
        doc = Document(); paragraph = doc.add_paragraph()
        add_source_link_text(paragraph, block['text'], block['hyperlinks'], 'uz',
                             'Iman Book Inter', 'Iman Book Noto Naskh Arabic')
        doc.save(path)
        expected = [{'text': block['text'][link['start']:link['end']], 'url': link['url'],
                     'sourceLiteralProof': link['sourceLiteralProof']} for link in block['hyperlinks']]
        with zipfile.ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        return expected, parts

    def write_link_fixture(self, path, parts):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in parts.items():
                archive.writestr(name, raw)

    def test_restoration_reinstates_exact_source_url_and_preserves_every_other_part(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-credit.docx'
            expected, parts = self.source_link_fixture(path)
            key = 'word/_rels/document.xml.rels'
            relationships = etree.fromstring(parts[key])
            target = next(item for item in relationships if item.get('Target') == expected[0]['url'])
            target.set('Target', expected[0]['url'] + '/')
            parts[key] = etree.tostring(relationships)
            self.write_link_fixture(path, parts)
            with self.assertRaisesRegex(ValueError, 'changed or disappeared'):
                validate_source_hyperlinks(etree.fromstring(parts['word/document.xml']), relationships, expected, 'uz', ROOT)
            self.assertEqual(restore_source_hyperlinks(path, expected, 'uz', ROOT), 1)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), set(parts))
                for name, raw in parts.items():
                    if name != key:
                        self.assertEqual(archive.read(name), raw, name)
                repaired = etree.fromstring(archive.read(key))
                validate_source_hyperlinks(etree.fromstring(archive.read('word/document.xml')), repaired, expected, 'uz', ROOT)
                target.set('Target', expected[0]['url'])
                self.assertEqual(etree.tostring(repaired, method='c14n'), etree.tostring(relationships, method='c14n'))
            once = path.read_bytes()
            self.assertEqual(restore_source_hyperlinks(path, expected, 'uz', ROOT), 0)
            self.assertEqual(path.read_bytes(), once)

    def test_restoration_rejects_changed_destination_label_count_or_shared_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-credit.docx'
            expected, original = self.source_link_fixture(path)
            bad_urls = ('http://muslim.uz/', 'https://other.example/', 'https://muslim.uz/other',
                        'https://muslim.uz/?source=1', 'https://muslim.uz/#credit',
                        'https://MUSLIM.uz/', 'https://muslim.uz/%2F')
            W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
            for variant in (*bad_urls, 'label', 'count', 'shared', 'shared-drawing', 'article-query'):
                with self.subTest(variant=variant):
                    parts = dict(original)
                    body = etree.fromstring(parts['word/document.xml'])
                    relationships = etree.fromstring(parts['word/_rels/document.xml.rels'])
                    target = next(item for item in relationships if item.get('Target') == expected[0]['url'])
                    target.set('Target', expected[0]['url'] + '/' if variant in {'label', 'count', 'shared', 'shared-drawing', 'article-query'} else variant)
                    node = next(node for node in body.iter(W + 'hyperlink') if node.get(R + 'id') == target.get('Id'))
                    if variant == 'label':
                        next(node.iter(W + 't')).text += ' changed'
                    elif variant in {'count', 'shared'}:
                        duplicate = deepcopy(node)
                        if variant == 'shared':
                            next(duplicate.iter(W + 't')).text = 'different link label'
                        node.getparent().append(duplicate)
                    elif variant == 'shared-drawing':
                        drawing_link = etree.SubElement(node.getparent(), '{http://schemas.openxmlformats.org/drawingml/2006/main}hlinkClick')
                        drawing_link.set(R + 'id', target.get('Id'))
                    elif variant == 'article-query':
                        article = next(item for item in relationships if item.get('Target') == expected[1]['url'])
                        article.set('Target', expected[1]['url'] + '&changed=1')
                    parts['word/document.xml'] = etree.tostring(body)
                    parts['word/_rels/document.xml.rels'] = etree.tostring(relationships)
                    self.write_link_fixture(path, parts)
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        restore_source_hyperlinks(path, expected, 'uz', ROOT)
                    self.assertEqual(path.read_bytes(), before)

    def test_restoration_handles_a_shared_relationship_only_when_all_uses_are_expected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-credit.docx'
            expected, parts = self.source_link_fixture(path)
            W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
            body = etree.fromstring(parts['word/document.xml'])
            relationships = etree.fromstring(parts['word/_rels/document.xml.rels'])
            target = next(item for item in relationships if item.get('Target') == expected[0]['url'])
            target.set('Target', expected[0]['url'] + '/')
            node = next(node for node in body.iter(W + 'hyperlink') if node.get(R + 'id') == target.get('Id'))
            node.getparent().append(deepcopy(node))
            expected.append(deepcopy(expected[0]))
            parts['word/document.xml'] = etree.tostring(body)
            parts['word/_rels/document.xml.rels'] = etree.tostring(relationships)
            self.write_link_fixture(path, parts)
            self.assertEqual(restore_source_hyperlinks(path, expected, 'uz', ROOT), 1)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read('word/document.xml'), parts['word/document.xml'])
                validate_source_hyperlinks(body, etree.fromstring(archive.read('word/_rels/document.xml.rels')), expected, 'uz', ROOT)

    def test_restoration_requires_existing_exact_source_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source-credit.docx'
            expected, parts = self.source_link_fixture(path)
            expected[0]['sourceLiteralProof']['textSHA256'] = '0' * 64
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                restore_source_hyperlinks(path, expected, 'uz', ROOT)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
