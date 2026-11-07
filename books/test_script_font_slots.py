from copy import deepcopy
from lxml import etree
import unittest
from script_font_slots import repair_parts,q,W

class ScriptFontTests(unittest.TestCase):
    def setUp(self):
        self.conf={'languages':{k:{'font':k}for k in ['th','bn','hi','ar','ur','fa']},'fonts':{**{k:{'family':'Native '+k}for k in ['th','bn','hi','ar','ur','fa']},'Arabic':{'family':'Canonical Arabic'},'Latin':{'family':'Pinned Latin'}}}
    def parts(self,text):return {'word/document.xml':f'<w:document xmlns:w="{W}"><w:r><w:rPr><w:rFonts w:ascii="Pinned Latin" w:asciiTheme="minorHAnsi"/></w:rPr><w:t>{text}</w:t></w:r><w:bookmarkStart w:id="7"/><w:footnoteReference w:id="3"/></w:document>'.encode(),'image.bin':b'unchanged'}
    def test_all_six_native_scripts_get_pinned_slots_and_complex_hint(self):
        for lang,text in [('th','บทใคร่ครวญ'),('bn','কুরআন'),('hi','क़ुरआन'),('ar','الإخلاص'),('ur','اخلاص'),('fa','اخلاص')]:
            parts=self.parts(text);repair_parts(parts,self.conf,lang);root=etree.fromstring(parts['word/document.xml']);fonts=root.find('.//'+q('rFonts'))
            for slot in ['ascii','hAnsi','eastAsia','cs']:self.assertEqual(fonts.get(q(slot)),'Native '+lang)
            self.assertEqual(fonts.get(q('hint')),'cs');self.assertEqual(root.find('.//'+q('cs')).get(q('val')),'1');self.assertEqual(root.find('.//'+q('t')).text,text);self.assertNotIn(q('asciiTheme'),fonts.attrib)
            self.assertEqual(parts['image.bin'],b'unchanged');self.assertEqual(root.find(q('bookmarkStart')).get(q('id')),'7');self.assertEqual(root.find(q('footnoteReference')).get(q('id')),'3')
    def test_unaffected_locale_is_byte_identical(self):
        parts=self.parts('Text');before=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'fil'),{});self.assertEqual(parts,before)
    def test_repair_is_idempotent(self):
        parts=self.parts('บทใคร่ครวญ');repair_parts(parts,self.conf,'th');before=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'th'),{});self.assertEqual(parts,before)
    def test_canonical_arabic_face_is_retained_in_rtl_book(self):
        parts=self.parts('قُلْ');parts['word/document.xml']=parts['word/document.xml'].replace(b'Pinned Latin',b'Canonical Arabic');repair_parts(parts,self.conf,'ur');root=etree.fromstring(parts['word/document.xml']);self.assertEqual(root.find('.//'+q('rFonts')).get(q('cs')),'Canonical Arabic')

    def test_mixed_font_slots_preserve_arabic_and_unrelated_runs(self):
        parts=self.parts('قُلْ');parts['word/document.xml']=parts['word/document.xml'].replace(b'w:ascii="Pinned Latin"',b'w:ascii="Pinned Latin" w:cs="Canonical Arabic"')
        parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:bookmarkStart',b'<w:r><w:rPr><w:rFonts w:ascii="Pinned Latin" w:cs="Canonical Arabic"/></w:rPr><w:t>English</w:t></w:r><w:bookmarkStart')
        repair_parts(parts,self.conf,'ur');root=etree.fromstring(parts['word/document.xml']);runs=root.findall('.//'+q('r'))
        self.assertEqual(runs[0].find('.//'+q('rFonts')).get(q('cs')),'Canonical Arabic')
        self.assertEqual(runs[1].find('.//'+q('rFonts')).get(q('ascii')),'Pinned Latin')
        self.assertEqual(runs[1].find('.//'+q('rFonts')).get(q('cs')),'Canonical Arabic')

if __name__=='__main__':unittest.main()
