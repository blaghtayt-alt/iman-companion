"""Keep exact source words while rendering explicitly declared note breaks."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from docx import Document
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import adapt_ikhlas
from build_books import Footnotes, embed_fonts, qn, reference_text
from check_outputs import validate_footnotes


class SourceNoteBreakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = json.loads((ROOT / 'materials/tadabbur/fr/extended/112.json').read_bytes())
        cls.source = json.loads((ROOT / 'materials/tadabbur/sources/112/fr/112-002.json').read_bytes())
        cls.note = cls.source['publisherNotes'][0]
        cls.catalog = json.loads((ROOT / 'materials/catalog.json').read_bytes())
        cls.declaration = next(row for row in json.loads((ROOT / 'books/reviewed-books.json').read_bytes())['books']
                               if row['language'] == 'fr' and row['collection'] == 'tadabbur-extended')

    def test_actual_reviewed_reader_source_and_publisher_note_match(self):
        public = json.loads((ROOT / 'materials/tadabbur/sources/112/fr/IKHLAS-FR-PUBLIC-SOURCES682.json').read_bytes())
        self.assertEqual(self.note, self.reader['publisher_notes'][0])
        self.assertEqual(self.note['text'], public['full44quranparents_notes']['2:3']['footnotes'])
        bindings = json.loads((ROOT / 'materials/tadabbur/ikhlas-112/source-review-bindings.json').read_bytes())
        record = next(row for row in bindings['records'] if row['language'] == 'fr')
        for source in record['sourceFiles'] + record['sourceConditions']:
            with self.subTest(source=source['path']):
                self.assertEqual(hashlib.sha256((ROOT / source['path']).read_bytes()).hexdigest(), source['sha256'])

    def test_projection_is_exactly_reversible_and_never_mutates_source_row(self):
        note = deepcopy(self.note)
        before = deepcopy(note)
        display = adapt_ikhlas.note_display_text(note)
        self.assertEqual(note, before)
        self.assertEqual(display.count('\n'), 3)
        self.assertNotIn('<br />', display)
        self.assertEqual(display.replace('\n', '<br />'), note['text'])
        self.assertEqual(display.split('\n'), note['text'].split('<br />'))

    def test_changed_words_qualifiers_and_markup_are_rejected(self):
        for old, new in (('non obligatoires', 'obligatoires'), ('<br />', '<br>'),
                         ('<br />', '<p>'), ('Ṣalāt', 'prière')):
            with self.subTest(change=(old, new)):
                note = deepcopy(self.note)
                note['text'] = note['text'].replace(old, new, 1)
                with self.assertRaisesRegex(ValueError, 'exact reviewed binding'):
                    adapt_ikhlas.note_display_text(note)

    def test_changed_semantics_or_reference_binding_is_rejected(self):
        for field, value in (('scope', 'ordinary literal markup'), ('verse', '2:4'),
                             ('type', 'context_note'),
                             ('required_for', [{'binding': 'Q:75', 'sentence': 'p08.s36'}]),
                             ('required_for', [{'binding': 'Q:74', 'sentence': 'p08.s35'}]),
                             ('new_unreviewed_metadata', True)):
            with self.subTest(field=field, value=value):
                note = deepcopy(self.note)
                note[field] = value
                with self.assertRaisesRegex(ValueError, 'exact reviewed binding'):
                    adapt_ikhlas.note_display_text(note)

    def test_other_note_markup_and_text_are_not_reinterpreted(self):
        for text in ('Literal <br /> example.', '<em>Unchanged source</em>.', 'First\nsecond.'):
            note = {'id': 'unrelated-note', 'text': text}
            self.assertEqual(adapt_ikhlas.note_display_text(note), text)

    def word_fixture(self):
        document = Document()
        paragraph = document.add_paragraph('Source anchor unchanged.')
        notes = Footnotes(document, 'fr', 'Iman Book Inter', 'Iman Book Naskh')
        notes.add(paragraph, adapt_ikhlas.note_display_text(self.note), group='source-note')
        return document, notes

    def test_real_docx_has_one_anchored_note_and_three_native_breaks(self):
        document, notes = self.word_fixture()
        self.assertEqual(len(notes.root.findall(qn('w:footnote'))), 3)  # Two separator records.
        self.assertEqual(len(document.element.body.findall('.//' + qn('w:footnoteReference'))), 1)
        self.assertEqual(len(notes.root.findall('.//' + qn('w:br'))), 3)
        self.assertFalse(any('<br' in (node.text or '') for node in notes.root.iter(qn('w:t'))))
        self.assertEqual(notes.texts, [reference_text(self.note['text']).replace('<br />', '\n')])
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'note.docx'
            document.save(file)
            embed_fonts(file, {}, notes.root)
            with zipfile.ZipFile(file) as archive:
                actual_notes = etree.fromstring(archive.read('word/footnotes.xml'))
                actual_body = etree.fromstring(archive.read('word/document.xml'))
            validate_footnotes(actual_notes, actual_body, notes.texts, 'fr')

    def test_unchanged_final_validator_rejects_missing_break_and_changed_word(self):
        for mutation in ('break', 'word'):
            with self.subTest(mutation=mutation):
                document, notes = self.word_fixture()
                if mutation == 'break':
                    node = notes.root.find('.//' + qn('w:br'))
                    node.getparent().remove(node)
                else:
                    node = next(node for node in notes.root.iter(qn('w:t')) if 'non obligatoires' in (node.text or ''))
                    node.text = node.text.replace('non obligatoires', 'obligatoires')
                with self.assertRaisesRegex(ValueError, 'Footnote text changed or reordered'):
                    validate_footnotes(notes.root, document.element.body, notes.texts, 'fr')

    def test_actual_french_unit_changes_only_the_declared_note_presentation(self):
        with patch.object(adapt_ikhlas, 'note_display_text', side_effect=lambda row: row['text']):
            original, = adapt_ikhlas.generate(ROOT, self.catalog, self.declaration)
        actual, = adapt_ikhlas.generate(ROOT, self.catalog, self.declaration)
        evidence = actual['provenance'].pop('sourceNotePresentation')
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['id'], self.note['id'])
        self.assertEqual(evidence[0]['nativeWordBreaks'], 3)
        self.assertTrue(evidence[0]['exactSourceReconstruction'])
        restored = 0
        for section in actual['sections']:
            for block in section['blocks']:
                for span in block.get('spans', []):
                    for index, note in enumerate(span.get('noteTexts', [])):
                        if note == adapt_ikhlas.note_display_text(self.note):
                            span['noteTexts'][index] = self.note['text']
                            restored += 1
        self.assertEqual(restored, 1)
        self.assertEqual(actual, original)


if __name__ == '__main__':
    unittest.main()
