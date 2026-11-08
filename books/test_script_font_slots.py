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

    def test_word_joiner_fallback_repair_preserves_exact_range_text_and_faces(self):
        # A real Word proof rendered these endpoints as boxes even though all
        # four font slots were correct. Merely splitting with identical rPr
        # still failed; the control needs neutral script properties.
        value='٦\u2060–\u2060٧ ثم ٥٦٤١\u2060–\u2060٥٦٤٢'
        parts=self.parts(value)
        parts['word/document.xml']=parts['word/document.xml'].replace(b'</w:rPr>',b'<w:rtl w:val="1"/><w:cs w:val="1"/><w:color w:val="2563EB"/></w:rPr>')
        parts['word/footnotes.xml']=parts['word/document.xml']
        parts['word/fonts/pinned.odttf']=b'original embedded font bytes'
        for lang in ('ar',):
            with self.subTest(language=lang):
                changed=deepcopy(parts);repair_parts(changed,self.conf,lang)
                for name in ('word/document.xml','word/footnotes.xml'):
                    root=etree.fromstring(changed[name]);runs=root.findall('.//'+q('r'))
                    self.assertEqual(''.join(n.text or '' for n in root.iter(q('t'))),value)
                    controls=[r for r in runs if '\u2060' in ''.join(n.text or '' for n in r.findall(q('t')))]
                    self.assertEqual(len(controls),4)
                    for run in controls:
                        self.assertEqual(''.join(n.text or '' for n in run.findall(q('t'))),'\u2060')
                        pr=run.find(q('rPr'));fonts=pr.find(q('rFonts'))
                        self.assertIsNone(pr.find(q('cs')));self.assertNotIn(q('hint'),fonts.attrib)
                        self.assertEqual(pr.find(q('rtl')).get(q('val')),'0')
                        for slot in ('ascii','hAnsi','eastAsia','cs'):
                            self.assertEqual(fonts.get(q(slot)),'Native '+lang)
                        self.assertEqual(pr.find(q('color')).get(q('val')),'2563EB')
                self.assertEqual(changed['word/fonts/pinned.odttf'],parts['word/fonts/pinned.odttf'])
                once=deepcopy(changed)
                self.assertEqual(repair_parts(changed,self.conf,lang),{})
                self.assertEqual(changed,once)

    def test_control_split_preserves_fields_anchors_and_paragraph_boundaries(self):
        raw=f'''<w:document xmlns:w="{W}"><w:body>
          <w:p><w:bookmarkStart w:id="8" w:name="unit"/><w:r w:rsidR="12345678"><w:rPr><w:rFonts w:ascii="Pinned Latin"/></w:rPr><w:t xml:space="preserve"> ٧</w:t><w:tab/><w:t>\u2060٨</w:t><w:footnoteReference w:id="103"/><w:br/><w:fldChar w:fldCharType="begin"/><w:instrText xml:space="preserve"> REF unit </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>\u2060٩ </w:t><w:fldChar w:fldCharType="end"/></w:r><w:bookmarkEnd w:id="8"/></w:p>
          <w:p><w:r><w:t>الفقرة التالية</w:t></w:r></w:p>
        </w:body></w:document>'''
        parts={'word/document.xml':raw.encode()};before=etree.fromstring(parts['word/document.xml'])
        repair_parts(parts,self.conf,'ar');after=etree.fromstring(parts['word/document.xml'])
        for tag in ('bookmarkStart','bookmarkEnd','footnoteReference','tab','br','fldChar','instrText'):
            snapshot=lambda root:[(tuple(n.attrib.items()),n.text) for n in root.iter(q(tag))]
            self.assertEqual(snapshot(before),snapshot(after),tag)
        texts=lambda root:[''.join(t.text or '' for t in p.iter(q('t'))) for p in root.iter(q('p'))]
        self.assertEqual(texts(before),texts(after))
        self.assertEqual(texts(after),[' ٧\u2060٨\u2060٩ ','الفقرة التالية'])
        self.assertEqual(len(after.findall('.//'+q('footnoteReference'))),1)

    def test_arabic_joining_controls_are_not_split_or_rewritten(self):
        # ZWJ and ZWNJ affect letter shaping; this repair targets only the
        # demonstrated WORD JOINER fallback failure, not every Cf character.
        value='قُلْ\u200dسلام\u200cعليكم'
        parts=self.parts(value);repair_parts(parts,self.conf,'ar')
        root=etree.fromstring(parts['word/document.xml'])
        self.assertEqual(len(root.findall('.//'+q('r'))),1)
        self.assertEqual(root.find('.//'+q('t')).text,value)

    def test_actual_hadith_bullet_and_em_dash_failures_keep_arabic_styling(self):
        for value in ('   •   المراجع','الأربعون القلبية — محمد صالح المنجد','يعني عرفة — فأخرج من صلبه كل ذرية'):
            with self.subTest(text=value):
                parts=self.parts(value)
                parts['word/document.xml']=parts['word/document.xml'].replace(b'</w:rPr>',b'<w:b/><w:bCs/><w:rtl w:val="true"/><w:cs w:val="1"/><w:color w:val="2563EB"/></w:rPr>')
                repair_parts(parts,self.conf,'ar');root=etree.fromstring(parts['word/document.xml'])
                self.assertEqual(''.join(n.text or '' for n in root.iter(q('t'))),value)
                for run in root.findall('.//'+q('r')):
                    text=''.join(n.text or '' for n in run.findall(q('t')));pr=run.find(q('rPr'))
                    self.assertIsNotNone(pr.find(q('b')));self.assertIsNotNone(pr.find(q('bCs')))
                    self.assertEqual(pr.find(q('color')).get(q('val')),'2563EB')
                    if text in {'•','—'}:
                        self.assertIsNone(pr.find(q('cs')))
                        self.assertNotIn(q('hint'),pr.find(q('rFonts')).attrib)
                        self.assertEqual(pr.find(q('rtl')).get(q('val')),'0')
                    else:
                        self.assertNotIn('•',text);self.assertNotIn('—',text)
                        self.assertEqual(pr.find(q('cs')).get(q('val')),'1')
                        self.assertEqual(pr.find(q('rtl')).get(q('val')),'true')
                once=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'ar'),{});self.assertEqual(parts,once)

    def test_neutral_fallback_change_is_limited_to_verified_arabic_locale(self):
        for lang in ('th','bn','hi','ur','fa'):
            with self.subTest(language=lang):
                parts=self.parts('قُلْ — \u2060٧ •');repair_parts(parts,self.conf,lang)
                root=etree.fromstring(parts['word/document.xml'])
                self.assertEqual(len(root.findall('.//'+q('r'))),1)

if __name__=='__main__':unittest.main()
