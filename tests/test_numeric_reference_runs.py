"""Literal numeric citations must keep their brackets in the number's run."""
from io import BytesIO
from pathlib import Path
import hashlib, json, os, sys, unittest, zipfile
import tempfile
import subprocess
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from copy import deepcopy
from lxml import etree
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from build_books import add_text, Footnotes
from book_typography import SYMBOL_LTR, SYMBOL_RTL
from script_font_slots import repair_parts, _reader_content
from arabic_quote_direction import quote_ranges, coalesce_quotes
from reader_xml import body_text
from pdf_quote_direction import temporary_pdf_quote_direction, PdfQuoteRestorationError, RLE, PDF


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


class ArabicQuotationDirection(unittest.TestCase):
    QUOTE = '{وَإِذَا مَرِضْتُ فَهُوَ يَشْفِينِ }الشعراء: ٨٠'

    def split_paragraph(self, quote=None):
        doc = Document()
        paragraph = doc.add_paragraph()
        add_text(paragraph, 'Before [٣]\t\n', 'en', 'Iman Book Inter', 'Iman Book Naskh')
        # Model the renderer splitting punctuation, letters, digits and breaks.
        for character in quote or self.QUOTE:
            add_text(paragraph, character, 'en', 'Iman Book Inter', 'Iman Book Naskh')
        add_text(paragraph, '\nAfter 12:34 [١٢].', 'en', 'Iman Book Inter', 'Iman Book Naskh')
        return doc, paragraph

    def test_four_accepted_source_excerpts_are_coherent_without_text_edits(self):
        unit = json.loads((ROOT / 'books/units/current/en/hadith/essential-01-001.json').read_bytes())
        found = []
        for section, value in enumerate(unit['sections']):
            for block, item in enumerate(value['blocks']):
                ranges = quote_ranges(item['text'], 'en')
                if ranges:
                    found.append((section, block, len(ranges)))
                for left, right in ranges:
                    quotation = item['text'][left:right]
                    doc = Document()
                    p = doc.add_paragraph()
                    source = 'Before [٣]\n' + quotation + '\nAfter 12:34.'
                    add_text(p, source, 'en', 'Iman Book Inter', 'Iman Book Naskh')
                    self.assertEqual(p.text, source)
                    native = [run for run in p.runs if run.text == quotation]
                    self.assertEqual(len(native), 1)
                    self.assertEqual(native[0]._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '1')
                    fonts = native[0]._r.find('w:rPr/w:rFonts', p._p.nsmap)
                    self.assertEqual({fonts.get(qn('w:' + slot)) for slot in ('ascii', 'hAnsi', 'eastAsia', 'cs')}, {'Iman Book Naskh'})
                    for marker in ('[٣]', '12:34'):
                        run = next(run for run in p.runs if run.text == marker)
                        self.assertEqual(run._r.find('w:rPr/w:rtl', p._p.nsmap).get(qn('w:val')), '0')
        self.assertEqual(found, [(2, 249, 1), (2, 251, 3)])

    def test_unsafe_or_non_native_islands_keep_existing_tokenization(self):
        excluded = ['{نص English }البقرة: ٢٢٠', '{نص }Latin: ٢٢٠', '{نص }البقرة: 220',
                    '{نص [٣] }البقرة: ٢٢٠', '{نص\u202e }البقرة: ٢٢٠',
                    '{نص }البقرة: ٢٢٠suffix', '{نص }البقرة: ٢٢٠3', '{نص }البقرة: ٢٢٠a',
                    '{نص }البقرة ٢٢٠', '{نص }البقرة: ٢٢٠\u064e']
        for text in excluded:
            with self.subTest(text=text):
                self.assertEqual(quote_ranges(text, 'en'), [])
                doc = Document()
                p = doc.add_paragraph()
                add_text(p, text, 'en', 'Iman Book Inter', 'Iman Book Naskh')
                self.assertEqual(p.text, text)
                self.assertNotEqual([r.text for r in p.runs], [text])
        for language in ('ar', 'ur', 'fa', 'tr', 'ja'):
            self.assertEqual(quote_ranges(self.QUOTE, language), [])

    def test_renderer_split_runs_coalesce_with_exact_text_breaks_and_fields(self):
        quotation = '{نَصٌّ عَرَبِيٌّ \nحَتَّىٰ يَطْهُرْنَ }البقرة: ٢٢٢'
        _, p = self.split_paragraph(quotation)
        before = _reader_content(p._p)
        text = p.text
        self.assertEqual(coalesce_quotes(p._p, 'en', 'Iman Book Naskh'), 1)
        self.assertEqual(_reader_content(p._p), before)
        self.assertEqual(p.text, text)
        self.assertEqual([r.text for r in p.runs if r.text == quotation], [quotation])
        after = etree.tostring(p._p)
        self.assertEqual(coalesce_quotes(p._p, 'en', 'Iman Book Naskh'), 0)
        self.assertEqual(etree.tostring(p._p), after)

    def test_post_render_parts_keep_content_contract_and_unrelated_parts(self):
        doc, p = self.split_paragraph()
        # Compare serialized OOXML on both sides. python-docx overrides the
        # paragraph .text property with synthesized descendant text.
        content = _reader_content(etree.fromstring(etree.tostring(p._p)))
        output = BytesIO()
        doc.save(output)
        with zipfile.ZipFile(BytesIO(output.getvalue())) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        original = dict(parts)
        config = json.loads((ROOT / 'books/config.json').read_bytes())
        self.assertEqual(set(repair_parts(parts, config, 'en')), {'word/document.xml'})
        paragraph = etree.fromstring(parts['word/document.xml']).find('.//' + qn('w:p'))
        self.assertEqual(_reader_content(paragraph), content)
        for name, raw in original.items():
            if name != 'word/document.xml':
                self.assertEqual(parts[name], raw)
        self.assertEqual(repair_parts(parts, config, 'en'), {})

    def test_fields_references_bookmarks_and_links_inside_island_are_rejected(self):
        for tag in ('fldChar', 'footnoteReference', 'bookmarkStart', 'hyperlink', 'drawing'):
            with self.subTest(element=tag):
                doc, p = self.split_paragraph()
                target = next(run._r for run in p.runs if run.text == 'و')
                node = OxmlElement('w:' + tag)
                if tag in ('bookmarkStart', 'hyperlink'):
                    p._p.insert(p._p.index(target) + 1, node)
                else:
                    target.append(node)
                before = etree.tostring(p._p)
                with self.assertRaisesRegex(ValueError, 'Arabic quotation crosses'):
                    coalesce_quotes(p._p, 'en', 'Iman Book Naskh')
                self.assertEqual(etree.tostring(p._p), before)

    def test_incompatible_visual_formatting_is_rejected_without_rewriting(self):
        _, p = self.split_paragraph()
        run = next(run for run in p.runs if run.text == 'و')
        run.font.color.rgb = __import__('docx.shared', fromlist=['RGBColor']).RGBColor.from_string('FF0000')
        before = etree.tostring(p._p)
        with self.assertRaisesRegex(ValueError, 'incompatible non-font formatting'):
            coalesce_quotes(p._p, 'en', 'Iman Book Naskh')
        self.assertEqual(etree.tostring(p._p), before)

    def test_failure_in_one_of_multiple_spans_preserves_whole_paragraph(self):
        _, p = self.split_paragraph(self.QUOTE + ' / ' + self.QUOTE)
        # Matches are repaired from the end. The second quotation is safe,
        # but the first crosses a bookmark and must prevent every change.
        target = next(run._r for run in p.runs if run.text == 'و')
        bookmark = OxmlElement('w:bookmarkStart')
        bookmark.set(qn('w:id'), '42')
        bookmark.set(qn('w:name'), 'preserve_bookmark')
        p._p.insert(p._p.index(target) + 1, bookmark)
        before = etree.tostring(p._p)
        content = _reader_content(p._p)
        with self.assertRaisesRegex(ValueError, 'Arabic quotation crosses'):
            coalesce_quotes(p._p, 'en', 'Iman Book Naskh')
        self.assertEqual(etree.tostring(p._p), before)
        self.assertEqual(_reader_content(p._p), content)

    def test_identical_repeated_properties_are_compatible_but_conflicts_fail(self):
        _, p = self.split_paragraph()
        run = next(run for run in p.runs if run.text == 'و')
        properties = run._r.get_or_add_rPr()
        properties.append(deepcopy(properties.find(qn('w:b'))))
        original = p.text
        coalesce_quotes(p._p, 'en', 'Iman Book Naskh')
        self.assertEqual(p.text, original)
        _, p = self.split_paragraph()
        run = next(run for run in p.runs if run.text == 'و')
        properties = run._r.get_or_add_rPr()
        different = deepcopy(properties.find(qn('w:b')))
        different.set(qn('w:val'), '1')
        properties.append(different)
        with self.assertRaisesRegex(ValueError, 'conflicting repeated formatting'):
            coalesce_quotes(p._p, 'en', 'Iman Book Naskh')


class _FakeUnoParagraph:
    def __init__(self, owner, text):
        self.owner = owner
        self.data = text.encode('utf-16-le')
        self.styles = list(range(len(self.data) // 2))

    def supportsService(self, name):
        return name == 'com.sun.star.text.Paragraph'

    def getString(self):
        return self.data.decode('utf-16-le')

    def getText(self):
        return self.owner

    def getStart(self):
        return self


class _FakeUnoCursor:
    def __init__(self, paragraph):
        self.paragraph = paragraph
        self.start = self.end = 0

    def goRight(self, count, expand):
        if not 0 <= count <= 32767:
            raise ValueError('UNO cursor count exceeds signed short')
        self.paragraph.owner.steps.append(count)
        if self.end + count > len(self.paragraph.data) // 2:
            return False
        self.end += count
        if not expand:
            self.start = self.end
        return True

    def getString(self):
        return self.paragraph.data[self.start * 2:self.end * 2].decode('utf-16-le')

    def collapseToEnd(self):
        self.start = self.end


class _FakeUnoText:
    def __init__(self, texts):
        self.paragraphs = [_FakeUnoParagraph(self, text) for text in texts]
        self.steps = []
        self.edits = []

    def getString(self):
        return '\n'.join(p.getString() for p in self.paragraphs)

    def createEnumeration(self):
        owner = self
        class Enumeration:
            index = 0
            def hasMoreElements(self):
                return self.index < len(owner.paragraphs)
            def nextElement(self):
                value = owner.paragraphs[self.index]
                self.index += 1
                return value
        return Enumeration()

    def createTextCursorByRange(self, paragraph):
        return _FakeUnoCursor(paragraph)

    def insertString(self, cursor, value, absorb):
        if not absorb and cursor.start != cursor.end:
            raise AssertionError('Insertion must use a collapsed cursor')
        p, left, right = cursor.paragraph, cursor.start, cursor.end
        selected = cursor.getString()
        if absorb and (len(selected) != 1 or selected not in (RLE, PDF) or value):
            raise AssertionError('Cleanup may delete only one exact recorded control')
        encoded = value.encode('utf-16-le')
        p.data = p.data[:left * 2] + encoded + p.data[right * 2:]
        p.styles[left:right] = ['inserted-control'] * (len(encoded) // 2)
        self.edits.append((left, selected, value, absorb))


class _FakeUnoDocument:
    def __init__(self, texts):
        self.text = _FakeUnoText(texts)

    def getText(self):
        return self.text


class PdfQuotationDirection(unittest.TestCase):
    QUOTE = '{نَصٌّ عَرَبِيٌّ }البقرة: ٢٢٠'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.file = Path(self.temporary.name) / 'saved.docx'
        self.file.write_bytes(b'Unchanged saved DOCX fixture')

    def test_pdf_helper_and_matcher_import_without_lxml_or_site_packages(self):
        code = """import sys
class NoLxml:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'lxml' or fullname.startswith('lxml.'):
            raise ModuleNotFoundError('lxml is unavailable in the UNO interpreter')
sys.meta_path.insert(0, NoLxml())
sys.path.insert(0, sys.argv[1])
from arabic_quote_direction import quote_ranges
from pdf_quote_direction import control_insertions, temporary_pdf_quote_direction
text = '{نص }البقرة: ٢٢٠'
assert quote_ranges(text, 'en') == [(0, len(text))]
assert len(control_insertions(text)) == 2
assert 'lxml' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-S', '-c', code, str(ROOT / 'books')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_multiple_quotes_lines_and_existing_controls_restore_all_text_and_styles(self):
        multiline = '{نَصٌّ عَرَبِيٌّ\nحَتَّىٰ يَطْهُرْنَ }البقرة: ٢٢٢'
        source = 'Original ' + RLE + 'control' + PDF + ' ' + self.QUOTE + ' / ' + multiline
        doc = _FakeUnoDocument([source, 'Unaffected paragraph and field result'])
        before = doc.text.getString()
        styles = [list(p.styles) for p in doc.text.paragraphs]
        with temporary_pdf_quote_direction(doc, 'en', self.file) as result:
            self.assertEqual(result, {'paragraphs': 1, 'insertedControls': 6})
            self.assertEqual(doc.text.paragraphs[0].getString(),
                             source.replace(self.QUOTE, RLE + self.QUOTE + PDF).replace(
                                 multiline, RLE + '{نَصٌّ عَرَبِيٌّ' + PDF + '\n' + RLE + 'حَتَّىٰ يَطْهُرْنَ }البقرة: ٢٢٢' + PDF))
        self.assertEqual(doc.text.getString(), before)
        self.assertEqual([p.styles for p in doc.text.paragraphs], styles)
        self.assertEqual(self.file.read_bytes(), b'Unchanged saved DOCX fixture')

    def test_non_bmp_prefix_and_long_utf16_offsets_use_bounded_cursor_steps(self):
        prefix = '😀' + 'x' * 33000 + '\n'
        doc = _FakeUnoDocument([prefix + self.QUOTE])
        with temporary_pdf_quote_direction(doc, 'en', self.file):
            self.assertEqual(doc.text.getString(), prefix + RLE + self.QUOTE + PDF)
        self.assertEqual(doc.text.getString(), prefix + self.QUOTE)
        self.assertIn(32767, doc.text.steps)
        self.assertTrue(all(step <= 32767 for step in doc.text.steps))

    def test_scalar_counting_uno_cursor_uses_fresh_verified_non_bmp_fallback(self):
        prefix = '😀 English prefix '
        doc = _FakeUnoDocument([prefix + self.QUOTE + ' suffix'])
        class ScalarCursor(_FakeUnoCursor):
            def goRight(self, count, expand):
                if not 0 <= count <= 32767:
                    raise ValueError('UNO cursor count exceeds signed short')
                self.paragraph.owner.steps.append(count)
                suffix = self.paragraph.data[self.end * 2:].decode('utf-16-le')
                moved = suffix[:count]
                self.end += len(moved.encode('utf-16-le')) // 2
                if not expand:
                    self.start = self.end
                return len(moved) == count
        doc.text.createTextCursorByRange = ScalarCursor
        styles = list(doc.text.paragraphs[0].styles)
        with temporary_pdf_quote_direction(doc, 'en', self.file):
            self.assertEqual(doc.text.getString(), prefix + RLE + self.QUOTE + PDF + ' suffix')
        self.assertEqual(doc.text.getString(), prefix + self.QUOTE + ' suffix')
        self.assertEqual(doc.text.paragraphs[0].styles, styles)

    def test_adjacent_quotes_close_before_reopening_at_shared_boundary(self):
        doc = _FakeUnoDocument([self.QUOTE + self.QUOTE])
        with temporary_pdf_quote_direction(doc, 'en', self.file):
            self.assertEqual(doc.text.getString(), RLE + self.QUOTE + PDF + RLE + self.QUOTE + PDF)
        self.assertEqual(doc.text.getString(), self.QUOTE + self.QUOTE)

    def test_export_error_is_preserved_after_exact_cleanup(self):
        doc = _FakeUnoDocument([self.QUOTE])
        error = RuntimeError('PDF export failed')
        with self.assertRaises(RuntimeError) as raised:
            with temporary_pdf_quote_direction(doc, 'en', self.file):
                raise error
        self.assertIs(raised.exception, error)
        self.assertEqual(doc.text.getString(), self.QUOTE)

    def test_wrong_cursor_prefix_fails_before_inserting_any_control(self):
        doc = _FakeUnoDocument(['English prefix ' + self.QUOTE + ' suffix'])
        class WrongCursor(_FakeUnoCursor):
            def goRight(self, count, expand):
                return super().goRight(count + 1, expand)
        doc.text.createTextCursorByRange = WrongCursor
        original = doc.text.getString()
        with self.assertRaisesRegex(ValueError, 'cursor prefix does not match'):
            with temporary_pdf_quote_direction(doc, 'en', self.file):
                self.fail('Export must not start with a wrong cursor offset')
        self.assertEqual(doc.text.getString(), original)
        self.assertEqual(doc.text.edits, [])

    def test_ambiguous_cleanup_fails_closed_and_retains_export_error(self):
        doc = _FakeUnoDocument([self.QUOTE])
        error = RuntimeError('PDF export failed')
        with self.assertRaises(PdfQuoteRestorationError) as raised:
            with temporary_pdf_quote_direction(doc, 'en', self.file):
                # Simulate an unexpected mutation at the recorded opening.
                doc.text.paragraphs[0].data = ('X' + self.QUOTE + PDF).encode('utf-16-le')
                raise error
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(doc.text.getString(), 'X' + self.QUOTE + PDF)
        self.assertFalse(any(absorb for _, _, _, absorb in doc.text.edits))

    def test_saved_docx_write_is_rejected(self):
        doc = _FakeUnoDocument([self.QUOTE])
        with self.assertRaisesRegex(PdfQuoteRestorationError, 'Saved DOCX bytes changed'):
            with temporary_pdf_quote_direction(doc, 'en', self.file):
                self.file.write_bytes(b'Unexpected write')
        self.assertEqual(doc.text.getString(), self.QUOTE)

    def test_non_english_and_nonmatching_text_are_untouched(self):
        for language, source in [('ar', self.QUOTE), ('en', 'No quoted Arabic'), ('en', '{نص ' + RLE + '}البقرة: ٢٢٠')]:
            with self.subTest(language=language, source=source):
                doc = _FakeUnoDocument([source])
                with temporary_pdf_quote_direction(doc, language, self.file) as result:
                    self.assertEqual(result, {'paragraphs': 0, 'insertedControls': 0})
                self.assertEqual(doc.text.getString(), source)
                self.assertEqual(doc.text.edits, [])


if __name__ == '__main__':
    unittest.main()
