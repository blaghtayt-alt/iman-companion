"""Literal numeric citations must keep their brackets in the number's run."""
from io import BytesIO
from pathlib import Path
import hashlib, json, os, sys, unittest, zipfile
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from build_books import add_text, Footnotes
from book_typography import SYMBOL_LTR, SYMBOL_RTL
from script_font_slots import repair_parts


class NumericReferenceRuns(unittest.TestCase):
    def paragraph(self, text, language='ar', **kwargs):
        doc = Document()
        p = doc.add_paragraph()
        add_text(p, text, language, 'Iman Book Arabic', 'Iman Book Naskh', **kwargs)
        return doc, p

    def test_reviewed_arabic_marker_is_one_ltr_run(self):
        # Article 14's literal [٣] was split between canonical PDF pages 186/187.
        doc, p = self.paragraph('[٣]')
        self.assertEqual([r.text for r in p.runs], ['[٣]'])
        self.assertEqual(p.runs[0]._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '0')
        self.assertEqual(p.text, '[٣]')
        output = BytesIO()
        doc.save(output)
        output.seek(0)
        self.assertEqual(Document(output).paragraphs[0].text, '[٣]')

    def test_supported_digits_and_numeric_groups_keep_literal_text(self):
        for language in ['ar', 'ur', 'fa', 'en']:
            for marker in ['[3]', '[٣]', '[۳]', '[١٢]', '[١،٢]', '[1, 2]', '[٢–٤]', '[١:٢]']:
                with self.subTest(language=language, marker=marker):
                    _, p = self.paragraph(marker, language)
                    self.assertEqual([r.text for r in p.runs], [marker])
                    self.assertEqual(p.runs[0]._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '0')
                    self.assertEqual(p.text, marker)

    def test_surrounding_reader_text_and_ornament_offsets_are_unchanged(self):
        text = 'قبل [١٢] ﴿نص﴾ بعد [٣] English'
        mirrors = {text.index('﴿'): True, text.index('﴾'): False}
        _, p = self.paragraph(text, ornament_mirrors=mirrors)
        self.assertEqual(p.text, text)
        self.assertNotIn('\u2060', p.text)
        self.assertEqual([r.text for r in p.runs if r.text in {'[١٢]', '[٣]'}], ['[١٢]', '[٣]'])
        self.assertEqual({r.text: r.font.name for r in p.runs if r.text in {'﴿', '﴾'}},
                         {'﴿': SYMBOL_LTR, '﴾': SYMBOL_RTL})

    def test_plain_numbers_and_arabic_bracketed_prose_keep_existing_behavior(self):
        _, p = self.paragraph('وقت ١٢:٣٤ [مرجع] نص')
        self.assertEqual(p.text, 'وقت ١٢:٣٤ [مرجع] نص')
        number = next(r for r in p.runs if r.text == '١٢:٣٤')
        self.assertEqual(number._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '0')
        for run in p.runs:
            if '[' in run.text or ']' in run.text:
                self.assertEqual(run._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '1')

    def test_source_footnote_remains_after_the_complete_marker(self):
        doc, p = self.paragraph('النص.[٣]')
        notes = Footnotes(doc, 'ar', 'Iman Book Arabic', 'Iman Book Naskh')
        notes.add(p, 'مرجع علمي محفوظ.')
        self.assertEqual(p.text, 'النص.[٣]')
        self.assertEqual(p.runs[-2].text, '[٣]')
        self.assertEqual(p.runs[-1]._r.find(qn('w:footnoteReference')).get(qn('w:id')), '1')
        self.assertEqual(notes.texts, ['مرجع علمي محفوظ.'])

    def test_font_restoration_preserves_atomic_marker_and_text(self):
        doc, p = self.paragraph('النص.[٣] بعده.')
        output = BytesIO()
        doc.save(output)
        output.seek(0)
        with zipfile.ZipFile(output) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        conf = json.loads((ROOT / 'books/config.json').read_bytes())
        repair_parts(parts, conf, 'ar')
        root = etree.fromstring(parts['word/document.xml'])
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        self.assertEqual(''.join(root.xpath('.//w:body//w:t/text()', namespaces=ns)), p.text)
        markers = root.xpath('.//w:r[w:t="[٣]"]', namespaces=ns)
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].find('w:rPr/w:rtl', ns).get(qn('w:val')), '0')
        fonts = markers[0].find('w:rPr/w:rFonts', ns)
        self.assertEqual({fonts.get(qn('w:' + slot)) for slot in ['ascii', 'hAnsi', 'eastAsia', 'cs']},
                         {'Iman Book Naskh'})

    def test_complete_citation_selects_one_pinned_face(self):
        for marker in ['[15]','[١٥]','[۱۵]','[١،٢]','[1, 2]','[٢–٤]','[١:٢]']:
            with self.subTest(marker=marker):
                _,p=self.paragraph(marker)
                self.assertEqual([r.text for r in p.runs],[marker])
                run=p.runs[0];family=run.font.name
                self.assertEqual(family,'Iman Book Inter'if marker.isascii()else'Iman Book Naskh')

    @unittest.skipUnless(os.environ.get('IMAN_BOOK_FONT_PROOF')=='1','Actual glyph proof runs after pinned assets are installed')
    def test_installed_pinned_citation_faces_cover_every_literal_glyph(self):
        conf=json.loads((ROOT/'books/config.json').read_bytes())
        definitions={value['family']:value for value in conf['fonts'].values()}
        for marker in ['[15]','[١٥]','[۱۵]','[١،٢]','[1, 2]','[٢–٤]','[١:٢]']:
            _,p=self.paragraph(marker);definition=definitions[p.runs[0].font.name]
            for style,relative in definition['files'].items():
                with self.subTest(marker=marker,style=style):
                    file=ROOT/relative
                    self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),definition['sha256'][style])
                    with TTFont(file)as font:self.assertFalse(set(map(ord,marker))-set(font.getBestCmap()))

    def test_libreoffice_split_native_marker_keeps_the_full_face_after_restore(self):
        # LibreOffice saves brackets and native digits separately even when
        # authored in one run. The complete pinned face must survive that save.
        doc=Document();p=doc.add_paragraph()
        for text in ('[','١٥',']'):
            run=p.add_run(text);run.font.name='Iman Book Naskh'
        output=BytesIO();doc.save(output);output.seek(0)
        with zipfile.ZipFile(output)as archive:parts={n:archive.read(n)for n in archive.namelist()}
        conf=json.loads((ROOT/'books/config.json').read_bytes());repair_parts(parts,conf,'ar')
        root=etree.fromstring(parts['word/document.xml']);ns={'w':qn('w:p').split('}')[0][1:]}
        self.assertEqual(''.join(root.xpath('.//w:body//w:t/text()',namespaces=ns)),'[١٥]')
        digits=root.xpath('.//w:r[w:t="١٥"]',namespaces=ns)[0]
        fonts=digits.find('w:rPr/w:rFonts',ns)
        self.assertEqual({fonts.get(qn('w:'+slot))for slot in ['ascii','hAnsi','eastAsia','cs']},{'Iman Book Naskh'})


if __name__ == '__main__':
    unittest.main()
