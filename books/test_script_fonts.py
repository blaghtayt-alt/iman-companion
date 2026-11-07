import unittest
from docx import Document
from docx.oxml.ns import qn
from build_books import add_text

class ScriptFonts(unittest.TestCase):
    def test_arabic_brackets_and_salawat_use_embedded_arabic_font_in_translations(self):
        text='Teksto ﴿sipì﴾ at ﷺ.';doc=Document();p=doc.add_paragraph();add_text(p,text,'fil','Iman Book Inter','Iman Book Naskh')
        self.assertEqual(p.text,text)
        for run in p.runs:
            if any(c in run.text for c in'﴿﴾'):
                self.assertEqual(run._r.rPr.rFonts.get(qn('w:ascii')),'Iman Book Symbols LTR')
                self.assertEqual(run._r.rPr.find(qn('w:rtl')).get(qn('w:val')),'0')
            elif 'ﷺ'in run.text:self.assertEqual(run._r.rPr.rFonts.get(qn('w:ascii')),'Iman Book Symbols RTL')
            elif run.text.strip():self.assertEqual(run._r.rPr.rFonts.get(qn('w:ascii')),'Iman Book Inter')
    def test_rtl_native_body_font_is_preserved(self):
        doc=Document();p=doc.add_paragraph();add_text(p,'﴿آية﴾ ﷺ','fa','Iman Book Persian','Iman Book Naskh')
        for r in p.runs:self.assertEqual(r._r.rPr.rFonts.get(qn('w:cs')),'Iman Book Symbols RTL'if any(c in r.text for c in'﴿﴾ﷺ')else'Iman Book Persian')
    def test_split_semantic_spans_keep_the_quote_direction(self):
        from book_typography import quotation_mirrors,span_mirrors
        for text,lang,want in[('﴿Sabihin mo﴾','fil',True),('﴿ข้อความ﴾','th',True),('﴿经文﴾','zh-CN',True),('﴿الآية﴾','fil',False),('﴿آیه﴾','fa',False),('﴾Already correct﴿','fil',False)]:
            parts=[{'text':text[0]},{'text':text[1:-1]},{'text':text[-1]}];maps=span_mirrors(parts,quotation_mirrors(text,lang));doc=Document();p=doc.add_paragraph()
            for part,mapping in zip(parts,maps):add_text(p,part['text'],lang,'Iman Book Inter','Iman Book Naskh',ornament_mirrors=mapping)
            self.assertEqual(p.text,text);self.assertEqual(p.runs[0]._r.rPr.rFonts.get(qn('w:ascii')),'Iman Book Symbols LTR'if want else'Iman Book Symbols RTL')
if __name__=='__main__':unittest.main()
