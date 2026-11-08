from pathlib import Path
import sys
import tempfile
import unittest
from xml.dom import minidom
from xml.etree.ElementTree import canonicalize
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from normalize_toc_hyperlinks import W, normalize, normalize_document_xml
from toc_sync import toc_nodes
from word_layout_check import contents
from lxml import etree


def fixture(*, anchor='chapter', style='TOC1', tooltip=True):
    hint = ' w:tooltip="A &amp; B &quot;quoted&quot; ١٦&#9;٣"' if tooltip else ''
    target = f' w:anchor="{anchor}"' if anchor is not None else ''
    return (f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:x="urn:preserved"><w:body>
<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>
<w:hyperlink{hint}{target} w:history="1" x:extra="exact">
<w:r><w:rPr><w:rtl w:val="1"/></w:rPr><w:t xml:space="preserve">A &amp; B ١٦ </w:t></w:r>
<w:r><w:tab/><w:t>٣</w:t></w:r></w:hyperlink></w:p>
<w:p><w:bookmarkStart w:id="4" w:name="chapter"/><w:r><w:t>Heading</w:t></w:r><w:bookmarkEnd w:id="4"/></w:p>
</w:body></w:document>''').encode()


class TocHyperlinkImportTests(unittest.TestCase):
    def test_attribute_order_only_preserves_text_target_tooltip_and_unknown_properties(self):
        before = fixture()
        after, changed = normalize_document_xml(before)
        self.assertEqual(changed, 1)
        self.assertEqual(canonicalize(before), canonicalize(after))
        link = minidom.parseString(after).getElementsByTagNameNS(W, 'hyperlink')[0]
        self.assertEqual(link.attributes.item(link.attributes.length - 1).localName, 'tooltip')
        self.assertEqual(link.getAttributeNS(W, 'anchor'), 'chapter')
        self.assertEqual(link.getAttributeNS(W, 'tooltip'), 'A & B "quoted" ١٦\t٣')
        root = etree.fromstring(after)
        self.assertEqual(contents(root), [{'anchor': 'chapter', 'cachedPage': 3}])
        self.assertEqual([node.text for node in toc_nodes(root)], ['٣'])
        self.assertEqual(normalize_document_xml(after), (after, 0))

    def test_only_internal_contents_links_need_this_compatibility_change(self):
        for raw in (fixture(style='Normal'), fixture(anchor=None), fixture(tooltip=False)):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_document_xml(raw), (raw, 0))

    def test_missing_or_wrong_anchor_remains_invalid(self):
        for anchor in (None, '', 'wrong'):
            with self.subTest(anchor=anchor):
                repaired, _ = normalize_document_xml(fixture(anchor=anchor))
                with self.assertRaisesRegex(ValueError, 'bookmark'):
                    contents(etree.fromstring(repaired))
        raw = fixture().replace(b'<w:hyperlink', b'<x:span').replace(b'</w:hyperlink>', b'</x:span>')
        repaired, _ = normalize_document_xml(raw)
        with self.assertRaisesRegex(ValueError, 'no unique link'):
            toc_nodes(etree.fromstring(repaired))

    def test_package_preserves_all_other_member_bytes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'fixture.docx'
            members = {'word/document.xml': fixture(), 'word/footnotes.xml': b'exact notes',
                       'word/fonts/font.odttf': bytes(range(256)), 'word/_rels/document.xml.rels': b'exact relationships'}
            with ZipFile(file, 'w', ZIP_DEFLATED) as archive:
                archive.comment = b'preserved package comment'
                for name, raw in members.items():
                    archive.writestr(name, raw)
            self.assertEqual(normalize(file), 1)
            with ZipFile(file) as archive:
                self.assertEqual(archive.comment, b'preserved package comment')
                self.assertEqual(archive.namelist(), list(members))
                for name, raw in members.items():
                    actual = archive.read(name)
                    self.assertEqual(canonicalize(actual), canonicalize(raw)) if name == 'word/document.xml' else self.assertEqual(actual, raw)
            saved = file.read_bytes()
            self.assertEqual(normalize(file), 0)
            self.assertEqual(file.read_bytes(), saved)

    def test_doctype_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DTD'):
            normalize_document_xml(fixture().replace(b'<w:document', b'<!DOCTYPE w:document><w:document', 1))


if __name__ == '__main__':
    unittest.main()
