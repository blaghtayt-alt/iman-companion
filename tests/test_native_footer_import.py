from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.dom import minidom
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from lxml import etree
from native_pagination import append_native_number
from normalize_native_footer import DIGITS, W, normalize, normalize_footer_xml


def generated_footer(language):
    document = Document()
    paragraph = document.sections[0].footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    append_native_number(paragraph, 'PAGE', language, 'Pinned native text face')
    return etree.tostring(paragraph._p.getparent(), xml_declaration=True, encoding='UTF-8', standalone=True)


class NativeFooterImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the real generator; the normalizer must recognize its
        # complete numeric expression without importing its third-party deps.
        cls.footers = {language: generated_footer(language) for language in DIGITS}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'book.docx'

    def write(self, footer=None):
        self.parts = {
            'word/document.xml': b'exact source paragraphs, TOC and bookmarks',
            'word/footnotes.xml': 'exact source notes القرآن'.encode(),
            'word/header1.xml': b'exact header',
            'word/fonts/font.odttf': bytes(range(256)),
            'word/_rels/document.xml.rels': b'exact relationships',
            'word/settings.xml': b'exact updateFields setting',
            'word/footer1.xml': self.footers['ur'] if footer is None else footer,
            'word/footer2.xml': f'<w:ftr xmlns:w="{W}"><w:p/></w:ftr>'.encode(),
        }
        with ZipFile(self.file, 'w', ZIP_DEFLATED) as archive:
            archive.comment = b'preserved package comment'
            for name, value in self.parts.items():
                archive.writestr(name, value)

    def test_real_generated_expression_becomes_one_live_page_with_original_formatting(self):
        for language, raw in self.footers.items():
            with self.subTest(language=language):
                before = minidom.parseString(raw)
                repaired, changed = normalize_footer_xml(raw, language)
                after = minidom.parseString(repaired)
                self.assertEqual(changed, 1)
                self.assertEqual(sum(n.getAttributeNS(W, 'fldCharType') == 'begin'
                                     for n in before.getElementsByTagNameNS(W, 'fldChar')), 114)
                self.assertEqual([n.getAttributeNS(W, 'fldCharType')
                                  for n in after.getElementsByTagNameNS(W, 'fldChar')], ['begin', 'separate', 'end'])
                self.assertEqual([n.firstChild.data for n in after.getElementsByTagNameNS(W, 'instrText')], [' PAGE '])
                self.assertEqual([n.firstChild.data for n in after.getElementsByTagNameNS(W, 't')], [DIGITS[language][2]])
                self.assertEqual(after.getElementsByTagNameNS(W, 'pPr')[0].toxml(), before.getElementsByTagNameNS(W, 'pPr')[0].toxml())
                original_props = before.getElementsByTagNameNS(W, 'rPr')[0].toxml()
                self.assertTrue(all(node.toxml() == original_props for node in after.getElementsByTagNameNS(W, 'rPr')))
                self.assertEqual(normalize_footer_xml(repaired, language), (repaired, 0))

    def test_all_other_parts_and_empty_cover_footer_remain_byte_identical(self):
        self.write()
        self.assertEqual(normalize(self.file, 'ur'), 1)
        with ZipFile(self.file) as archive:
            self.assertEqual(archive.comment, b'preserved package comment')
            self.assertEqual(archive.namelist(), list(self.parts))
            for name, raw in self.parts.items():
                if name != 'word/footer1.xml':
                    self.assertEqual(archive.read(name), raw, name)
        once = self.file.read_bytes()
        self.assertEqual(normalize(self.file, 'ur'), 0)
        self.assertEqual(self.file.read_bytes(), once)

    def test_unknown_content_is_rejected_without_mutating_the_package(self):
        extra = ('<w:r><w:t>Keep this source note</w:t></w:r>',
                 '<w:drawing/>', '<w:pict/>', '<w:object/>',
                 '<w:hyperlink w:anchor="keep"/>', '<w:bookmarkStart w:id="1" w:name="keep"/>',
                 '<w:bookmarkEnd w:id="1"/>', '<w:r><w:instrText> DATE </w:instrText></w:r>')
        for content in extra:
            with self.subTest(content=content):
                self.write(self.footers['ur'].replace(b'</w:p>', content.encode() + b'</w:p>'))
                before = self.file.read_bytes()
                with self.assertRaises(ValueError):
                    normalize(self.file, 'ur')
                self.assertEqual(self.file.read_bytes(), before)

    def test_additional_footer_paragraph_is_not_erased(self):
        self.write(self.footers['ur'].replace(b'</w:ftr>', b'<w:p><w:r><w:t>Keep</w:t></w:r></w:p></w:ftr>'))
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Additional content'):
            normalize(self.file, 'ur')
        self.assertEqual(self.file.read_bytes(), before)

    def test_changed_formula_cache_or_field_structure_is_not_assumed_equivalent(self):
        raw = self.footers['ur']
        variants = (raw.replace(b'1000', b'9000', 1), raw.replace(b'PAGE', b'NUMPAGES', 1),
                    raw.replace('۰'.encode(), '۱'.encode(), 1),
                    raw.replace(b'w:fldCharType="end"', b'w:fldCharType="begin"', 1),
                    raw.replace(b'MOD(', b'MOD (', 1))
        for variant in variants:
            with self.subTest(variant=variant[:100]):
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    normalize_footer_xml(variant, 'ur')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            normalize_footer_xml(raw, 'ar')

    def test_ordinary_page_and_non_rtl_documents_are_unchanged(self):
        ordinary = f'<w:ftr xmlns:w="{W}"><w:p><w:fldSimple w:instr=" PAGE "><w:r><w:t>۲</w:t></w:r></w:fldSimple></w:p></w:ftr>'.encode()
        self.assertEqual(normalize_footer_xml(ordinary, 'ur'), (ordinary, 0))
        self.file.write_bytes(b'not even a ZIP; English never enters this pass')
        before = self.file.read_bytes()
        self.assertEqual(normalize(self.file, 'en'), 0)
        self.assertEqual(before, self.file.read_bytes())

    def test_dtd_and_duplicate_package_members_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DTD'):
            normalize_footer_xml(self.footers['ur'].replace(b'<w:ftr', b'<!DOCTYPE w:ftr><w:ftr', 1), 'ur')
        self.write()
        with self.assertWarns(UserWarning), ZipFile(self.file, 'a') as archive:
            archive.writestr('word/footer1.xml', self.footers['ur'])
        before = self.file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            normalize(self.file, 'ur')
        self.assertEqual(before, self.file.read_bytes())

    def test_failed_atomic_install_retains_original_and_removes_temporary_file(self):
        self.write()
        before = self.file.read_bytes()
        with patch('normalize_native_footer.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                normalize(self.file, 'ur')
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_concurrent_newer_input_is_not_overwritten(self):
        self.write()
        original = normalize_footer_xml

        def changed_input(raw, language):
            result = original(raw, language)
            self.file.write_bytes(b'newer input owned by another writer')
            return result

        with patch('normalize_native_footer.normalize_footer_xml', side_effect=changed_input):
            with self.assertRaisesRegex(ValueError, 'Document changed'):
                normalize(self.file, 'ur')
        self.assertEqual(self.file.read_bytes(), b'newer input owned by another writer')
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_helper_runs_without_site_packages(self):
        self.write()
        command = ('import sys;sys.path.insert(0,sys.argv[1]);'
                   'from normalize_native_footer import normalize;'
                   'assert normalize(sys.argv[2],"ur")==1')
        result = subprocess.run([sys.executable, '-S', '-c', command, str(ROOT / 'books'), str(self.file)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
