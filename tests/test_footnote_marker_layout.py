"""Bound proven dense marker tails while preserving their source/footnote bindings."""
from io import BytesIO
from pathlib import Path
import sys
import unittest

from docx import Document
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from build_books import Footnotes, qn
from check_outputs import validate_footnotes
from reader_xml import body_text


class FootnoteMarkerLayoutTests(unittest.TestCase):
    def fixture(self, count, language='ur'):
        document = Document()
        paragraph = document.add_paragraph('মূল পাঠ অক্ষত আছে।' if language=='bn' else 'اصل عبارت محفوظ ہے۔')
        notes = Footnotes(document, language, 'Iman Book Bengali' if language=='bn' else 'Iman Book Urdu', 'Iman Book Naskh')
        for index in range(count):
            notes.add(paragraph, 'মূল উৎস সংরক্ষিত।' if language=='bn' else 'حوالہ محفوظ ہے۔', group=str(index))
        return document, paragraph, notes

    def test_bengali_dense_source_tail_preserves_every_note_and_text_binding(self):
        document, paragraph, notes = self.fixture(57,'bn')
        before = etree.tostring(paragraph._p)
        note_bytes = etree.tostring(notes.root)
        refs = list(paragraph._p.iter(qn('w:footnoteReference')))
        self.assertEqual(notes.wrap_trailing_markers(),7)
        self.assertEqual(list(paragraph._p.iter(qn('w:footnoteReference'))),refs)
        self.assertEqual([node.get(qn('w:id')) for node in refs],[str(i) for i in range(1,58)])
        self.assertEqual(etree.tostring(notes.root),note_bytes)
        self.assertEqual(body_text(paragraph._p),'মূল পাঠ অক্ষত আছে।'+'\n'*7)
        self.assertEqual(notes.wrap_trailing_markers(),0)
        validate_footnotes(notes.root,document.element.body,notes.texts,'bn',
                           preserved_identifiers=notes.identifiers,
                           source_literal_proofs=notes.literal_proofs)
        stream=BytesIO();document.save(stream);stream.seek(0)
        validate_footnotes(notes.root,Document(stream).element.body,notes.texts,'bn',
                           preserved_identifiers=notes.identifiers,
                           source_literal_proofs=notes.literal_proofs)
        for br in list(paragraph._p.iter(qn('w:br'))):br.getparent().remove(br)
        self.assertEqual(etree.tostring(paragraph._p),before)

    def test_dense_tail_preserves_source_nodes_reference_identity_and_note_bindings(self):
        document, paragraph, notes = self.fixture(62)
        source_nodes = list(paragraph._p.iter(qn('w:t')))
        source_texts = [node.text for node in source_nodes]
        refs = list(paragraph._p.iter(qn('w:footnoteReference')))
        ids = [node.get(qn('w:id')) for node in refs]
        note_bytes = etree.tostring(notes.root)
        original_properties = [etree.tostring(run.find(qn('w:rPr'))) for run in paragraph._p.findall(qn('w:r'))[1:]]
        self.assertEqual(notes.wrap_trailing_markers(), 7)
        self.assertEqual(list(paragraph._p.iter(qn('w:t'))), source_nodes)
        self.assertEqual([node.text for node in source_nodes], source_texts)
        self.assertEqual(list(paragraph._p.iter(qn('w:footnoteReference'))), refs)
        self.assertEqual([node.get(qn('w:id')) for node in refs], ids)
        self.assertEqual(etree.tostring(notes.root), note_bytes)
        self.assertEqual([etree.tostring(run.find(qn('w:rPr'))) for run in paragraph._p.findall(qn('w:r'))[1:]], original_properties)
        self.assertEqual(body_text(paragraph._p), 'اصل عبارت محفوظ ہے۔' + '\n' * 7)
        self.assertEqual([run.find(qn('w:footnoteReference')).get(qn('w:id'))
                          for run in paragraph._p.findall(qn('w:r')) if run.find(qn('w:br')) is not None],
                         ['8', '16', '24', '32', '40', '48', '56'])
        # Serialize through python-docx before applying the unchanged output
        # validator, so these are actual Word references, not a mocked model.
        stream = BytesIO();document.save(stream);stream.seek(0)
        saved = Document(stream)
        validate_footnotes(notes.root, saved.element.body, notes.texts, 'ur',
                           preserved_identifiers=notes.identifiers,
                           source_literal_proofs=notes.literal_proofs)

    def test_actual_english_french_source_paragraph_and_all_notes_survive_wrapping(self):
        import current_reviewed_quran as current
        inventory = current.read(ROOT, current.PROJECTION)
        catalog = current.read(ROOT, 'materials/catalog.json')
        evidence = current.binding(ROOT, current.PROJECTION)
        for language, count, breaks in (('en', 53, 6), ('fr', 46, 5)):
            with self.subTest(language=language):
                source = current.read(ROOT, f'materials/tadabbur/{language}/extended/098.json')
                text = source['entries']['98:1']['blocks'][34]['text']
                self.assertNotIn('\n', text)
                record = next(row for row in inventory['records']
                              if (row['language'], row['id']) == (language, '98:extended'))
                unit = current.normalize(ROOT, catalog, record['catalogEntry'], record, evidence)
                block, = [block for section in unit['sections'] for block in section['blocks']
                          if block.get('text') == text]
                document = Document()
                paragraph = document.add_paragraph()
                notes = Footnotes(document, language, 'Iman Book Inter', 'Iman Book Naskh', source_root=ROOT)
                for span_index, span in enumerate(block['spans']):
                    paragraph.add_run(span['text'])
                    for index, note in enumerate(span.get('noteTexts', [])):
                        notes.add(paragraph, note, group=f'source-{span_index}-{index}',
                                  source_literal_proofs=span['noteLiteralProofs'][index])
                self.assertEqual(len(notes.texts), count)
                self.assertEqual(body_text(paragraph._p), text)
                before = etree.tostring(paragraph._p)
                note_bytes = etree.tostring(notes.root)
                text_nodes = list(paragraph._p.iter(qn('w:t')))
                references = list(paragraph._p.iter(qn('w:footnoteReference')))
                self.assertEqual(notes.wrap_trailing_markers(), breaks)
                self.assertEqual(list(paragraph._p.iter(qn('w:t'))), text_nodes)
                self.assertEqual(list(paragraph._p.iter(qn('w:footnoteReference'))), references)
                self.assertEqual(etree.tostring(notes.root), note_bytes)
                self.assertEqual(body_text(paragraph._p), text + '\n' * breaks)
                self.assertEqual(notes.wrap_trailing_markers(), 0)
                stream = BytesIO();document.save(stream);stream.seek(0)
                validate_footnotes(notes.root, Document(stream).element.body, notes.texts, language,
                                   preserved_identifiers=notes.identifiers,
                                   source_literal_proofs=notes.literal_proofs, root=ROOT)
                for br in list(paragraph._p.iter(qn('w:br'))):br.getparent().remove(br)
                self.assertEqual(etree.tostring(paragraph._p), before)

    def test_boundary_counts_and_repeated_pass_are_stable(self):
        for count, expected in ((0, 0), (1, 0), (8, 0), (9, 1), (16, 1), (17, 2)):
            with self.subTest(count=count):
                document, paragraph, notes = self.fixture(count)
                self.assertEqual(notes.wrap_trailing_markers(), expected)
                once = etree.tostring(document.element.body)
                self.assertEqual(notes.wrap_trailing_markers(), 0)
                self.assertEqual(etree.tostring(document.element.body), once)

    def test_large_inline_cluster_followed_by_source_text_is_untouched(self):
        document, paragraph, notes = self.fixture(20)
        paragraph.add_run('مزید اصل عبارت۔')
        before = etree.tostring(document.element.body)
        self.assertEqual(notes.wrap_trailing_markers(), 0)
        self.assertEqual(etree.tostring(document.element.body), before)

    def test_only_terminal_cluster_changes_when_earlier_markers_are_inline(self):
        document, paragraph, notes = self.fixture(20)
        inline_runs = list(paragraph._p)
        paragraph.add_run('مزید اصل عبارت۔')
        for index in range(9):
            notes.add(paragraph, 'حوالہ محفوظ ہے۔', group='tail-' + str(index))
        before_inline = [etree.tostring(run) for run in inline_runs]
        before_notes = etree.tostring(notes.root)
        self.assertEqual(notes.wrap_trailing_markers(), 1)
        self.assertEqual([etree.tostring(run) for run in inline_runs], before_inline)
        self.assertEqual(etree.tostring(notes.root), before_notes)
        validate_footnotes(notes.root, document.element.body, notes.texts, 'ur')

    def test_marker_run_with_source_text_is_not_treated_as_generated_marker_tail(self):
        document, paragraph, notes = self.fixture(20)
        text = etree.SubElement(paragraph._p[-1], qn('w:t'));text.text = 'اصل متن'
        before = etree.tostring(document.element.body)
        self.assertEqual(notes.wrap_trailing_markers(), 0)
        self.assertEqual(etree.tostring(document.element.body), before)

    def test_other_languages_are_unchanged(self):
        for language in ('ar', 'fa', 'de', 'hi', 'ja'):
            with self.subTest(language=language):
                document, paragraph, notes = self.fixture(20, language)
                before = etree.tostring(document.element.body)
                self.assertEqual(notes.wrap_trailing_markers(), 0)
                self.assertEqual(etree.tostring(document.element.body), before)


if __name__ == '__main__':
    unittest.main()
