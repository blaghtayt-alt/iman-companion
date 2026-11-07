from pathlib import Path
from unittest.mock import patch
import json,os,tempfile,unittest,zipfile
from lxml import etree
from native_word_footer import prepare,W,q

class NativeFooterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'books').mkdir()
        self.file=self.root/'fixture.docx';self.body=b'UNCHANGED BODY FIXTURE';self.other=b'UNCHANGED OTHER PART'
        self.definition={'family':'Test native digit face','sha256':{'Regular':'1'*64,'Bold':'2'*64}}
        (self.root/'books/config.json').write_text(json.dumps({'fonts':{'DigitsArabic':self.definition,'DigitsPersian':self.definition}}))
        self.write('<w:r><w:instrText> IF PAGE = 1 </w:instrText></w:r>')
    def tearDown(self):self.temp.cleanup()
    def write(self,runs):
        with zipfile.ZipFile(self.file,'w')as z:
            z.writestr('word/document.xml',self.body);z.writestr('other.bin',self.other);z.writestr('word/footer1.xml',f'<w:ftr xmlns:w="{W}"><w:p>{runs}</w:p></w:ftr>')
    def test_one_live_numeric_page_field_uses_all_native_font_slots(self):
        with patch('native_word_footer.verify')as check:receipt=prepare(self.file,self.root,'fa')
        self.assertEqual(check.call_count,2);self.assertFalse(receipt['wordGlobalOptionsChanged'])
        with zipfile.ZipFile(self.file)as z:
            self.assertEqual(z.read('word/document.xml'),self.body);self.assertEqual(z.read('other.bin'),self.other);root=etree.fromstring(z.read('word/footer1.xml'))
        self.assertEqual([n.text for n in root.iter(q('instrText'))],[' PAGE ']);self.assertEqual([n.text for n in root.iter(q('t'))],['۲'])
        for fonts in root.iter(q('rFonts')):self.assertEqual(set(fonts.values()),{'Test native digit face'});self.assertEqual(len(fonts.attrib),4)
    def test_empty_cover_footer_is_preserved(self):
        with zipfile.ZipFile(self.file,'a')as z:z.writestr('word/footer2.xml',f'<w:ftr xmlns:w="{W}"><w:p/></w:ftr>')
        with zipfile.ZipFile(self.file)as z:before=z.read('word/footer2.xml')
        with patch('native_word_footer.verify'):prepare(self.file,self.root,'ar')
        with zipfile.ZipFile(self.file)as z:self.assertEqual(z.read('word/footer2.xml'),before)
    def test_missing_live_footer_is_rejected(self):
        self.write('<w:r><w:t>2</w:t></w:r>')
        with patch('native_word_footer.verify'):
            with self.assertRaisesRegex(ValueError,'No live'):prepare(self.file,self.root,'ur')
    def test_footer_with_other_text_is_not_replaced(self):
        self.write('<w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:t>Keep this note</w:t></w:r>')
        before=self.file.read_bytes()
        with patch('native_word_footer.verify'):
            with self.assertRaisesRegex(ValueError,'non-page text'):prepare(self.file,self.root,'fa')
        self.assertEqual(before,self.file.read_bytes())
    def test_footer_with_another_field_is_not_replaced(self):
        self.write('<w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:instrText> DATE </w:instrText></w:r>')
        before=self.file.read_bytes()
        with patch('native_word_footer.verify'):
            with self.assertRaisesRegex(ValueError,'another field'):prepare(self.file,self.root,'fa')
        self.assertEqual(before,self.file.read_bytes())
    def test_failed_word_finalization_preserves_candidate_and_existing_receipt(self):
        from finalize_word import finalize
        old_receipt=self.file.with_name(self.file.name+'.word-layout.json');old_receipt.write_bytes(b'original receipt')
        before=self.file.read_bytes()
        def failed(staged,*args):staged.write_bytes(b'partial modified data');raise RuntimeError('Word unavailable')
        with patch('finalize_word._finalize_staged',side_effect=failed):
            with self.assertRaisesRegex(RuntimeError,'Word unavailable'):finalize(self.file,'fa',root=self.root)
        self.assertEqual(before,self.file.read_bytes());self.assertEqual(old_receipt.read_bytes(),b'original receipt')
    def test_newer_concurrent_candidate_is_not_overwritten(self):
        from finalize_word import finalize
        def staged_work(staged,*args):
            staged.write_bytes(b'verified candidate');staged.with_name(staged.name+'.word-layout.json').write_bytes(b'{}')
            self.file.write_bytes(b'newer user candidate');return {}
        with patch('finalize_word._finalize_staged',side_effect=staged_work),patch('finalize_word.verify'):
            with self.assertRaisesRegex(ValueError,'newer file'):finalize(self.file,'fa',root=self.root)
        self.assertEqual(self.file.read_bytes(),b'newer user candidate')
    def test_successful_finalization_installs_only_verified_staged_copy(self):
        from finalize_word import finalize
        def staged_work(staged,*args):
            staged.write_bytes(b'verified candidate');staged.with_name(staged.name+'.word-layout.json').write_bytes(b'verified receipt');return {'checked':True}
        with patch('finalize_word._finalize_staged',side_effect=staged_work),patch('finalize_word.verify'):
            receipt=finalize(self.file,'fa',root=self.root)
        self.assertTrue(receipt['checked']);self.assertEqual(self.file.read_bytes(),b'verified candidate');self.assertEqual(self.file.with_name(self.file.name+'.word-layout.json').read_bytes(),b'verified receipt')
    def test_receipt_install_failure_restores_original_candidate(self):
        from finalize_word import finalize
        original=self.file.read_bytes();old_receipt=self.file.with_name(self.file.name+'.word-layout.json');old_receipt.write_bytes(b'old receipt');real_replace=os.replace
        def staged_work(staged,*args):
            staged.write_bytes(b'verified candidate');staged.with_name(staged.name+'.word-layout.json').write_bytes(b'new receipt');return {'checked':True}
        def fail_receipt(source,target):
            if Path(source).name.endswith('.word-layout.json'):raise PermissionError('receipt locked')
            return real_replace(source,target)
        with patch('finalize_word._finalize_staged',side_effect=staged_work),patch('finalize_word.verify'),patch('finalize_word.os.replace',side_effect=fail_receipt):
            with self.assertRaisesRegex(PermissionError,'receipt locked'):finalize(self.file,'fa',root=self.root)
        self.assertEqual(self.file.read_bytes(),original);self.assertEqual(old_receipt.read_bytes(),b'old receipt')
    def test_rtl_font_changes_invalidate_only_matching_scope(self):
        from published_library import scope_settings
        conf={'languages':{'ar':{'font':'Arabic'},'ru':{'font':'Latin'}},'fonts':{'Arabic':{'sha256':'a'},'Latin':{'sha256':'l'},'DigitsArabic':{'sha256':'first'}}}
        path=self.root/'books/config.json';path.write_text(json.dumps(conf),encoding='utf8');ar=scope_settings(self.root,('ar','tadabbur-extended'),[]);ru=scope_settings(self.root,('ru','tadabbur-extended'),[])
        conf['fonts']['DigitsArabic']['sha256']='second';path.write_text(json.dumps(conf),encoding='utf8')
        self.assertNotEqual(ar,scope_settings(self.root,('ar','tadabbur-extended'),[]));self.assertEqual(ru,scope_settings(self.root,('ru','tadabbur-extended'),[]))
    def test_other_languages_are_untouched(self):
        before=self.file.read_bytes();self.assertIsNone(prepare(self.file,self.root,'fil'));self.assertEqual(before,self.file.read_bytes())

if __name__=='__main__':unittest.main()
