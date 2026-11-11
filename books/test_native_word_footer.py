from pathlib import Path
from io import BytesIO
from unittest.mock import patch
import hashlib,json,os,tempfile,unittest,zipfile
from lxml import etree
from native_word_footer import prepare,verify_rendered_footer,W,q

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
    def test_word_contents_uses_existing_native_digit_policy(self):
        from finalize_word import word_page_digits
        self.assertEqual(word_page_digits('bn'),'0123456789');self.assertEqual(word_page_digits('hi'),'0123456789')
        self.assertEqual(word_page_digits('fa'),'۰۱۲۳۴۵۶۷۸۹');self.assertEqual(word_page_digits('ar'),'٠١٢٣٤٥٦٧٨٩')
    def test_rtl_font_changes_invalidate_only_matching_scope(self):
        from published_library import scope_settings
        conf={'languages':{'ar':{'font':'Arabic'},'ru':{'font':'Latin'}},'fonts':{'Arabic':{'sha256':'a'},'Latin':{'sha256':'l'},'DigitsArabic':{'sha256':'first'}}}
        path=self.root/'books/config.json';path.write_text(json.dumps(conf),encoding='utf8');ar=scope_settings(self.root,('ar','tadabbur-extended'),[]);ru=scope_settings(self.root,('ru','tadabbur-extended'),[])
        conf['fonts']['DigitsArabic']['sha256']='second';path.write_text(json.dumps(conf),encoding='utf8')
        self.assertNotEqual(ar,scope_settings(self.root,('ar','tadabbur-extended'),[]));self.assertEqual(ru,scope_settings(self.root,('ru','tadabbur-extended'),[]))
    def test_other_languages_are_untouched(self):
        before=self.file.read_bytes();self.assertIsNone(prepare(self.file,self.root,'fil'));self.assertEqual(before,self.file.read_bytes())

class RenderedNativeFooterTests(unittest.TestCase):
    """Real embedded TTF/PDF subsets; these are synthetic PDFs, not Word proofs."""

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'books').mkdir()
        original=Path(__file__).resolve().parents[1]
        conf=json.loads((original/'books/config.json').read_bytes())
        fonts={key:conf['fonts'][key] for key in ('DigitsArabic','DigitsPersian')}
        for definition in fonts.values():
            path=self.root/definition['files']['Regular'];path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((original/definition['files']['Regular']).read_bytes())
        (self.root/'books/config.json').write_text(json.dumps({'fonts':fonts}))
        self.fonts=fonts
        self.pdf=self.root/'synthetic-footer.pdf'

    def font_bytes(self,digits,*,language='ur',bad_digit=None):
        from fontTools import subset
        from fontTools.ttLib import TTFont
        key='DigitsArabic' if language=='ar' else 'DigitsPersian'
        font=TTFont(self.root/self.fonts[key]['files']['Regular'])
        try:
            start=0x660 if language=='ar' else 0x6f0
            selected=subset.Subsetter()
            selected.populate(unicodes=[code+n for code in (48,start) for n in digits])
            selected.subset(font)
            if bad_digit is not None:
                replacement=next(n for n in digits if n!=bad_digit)
                wrong=font.getBestCmap()[48+replacement]
                for table in font['cmap'].tables:
                    if table.isUnicode() and 48+bad_digit in table.cmap:table.cmap[48+bad_digit]=wrong
            output=BytesIO();font.save(output);return output.getvalue()
        finally:font.close()

    def make_pdf(self,*,fonts=None,pages=4,texts=None,positions=None,selected_fonts=None):
        from pypdf import PdfWriter
        from pypdf.generic import ArrayObject,DecodedStreamObject,DictionaryObject,NameObject,NumberObject
        fonts=fonts or [{'digits':[0,2,3,4]}]
        writer=PdfWriter();resources=DictionaryObject()
        for index,options in enumerate(fonts):
            raw=self.font_bytes(options['digits'],language=options.get('language','ur'),bad_digit=options.get('bad_digit'))
            name=NameObject('/'+options.get('name','FIXTUR'+str(index)+'+NativeDigits'))
            stream=DecodedStreamObject();stream.set_data(raw)
            descriptor=DictionaryObject({NameObject('/Type'):NameObject('/FontDescriptor'),
                NameObject('/FontName'):name,NameObject('/Flags'):NumberObject(4),
                NameObject('/FontBBox'):ArrayObject([NumberObject(n) for n in (-1000,-1000,2000,2000)]),
                NameObject('/ItalicAngle'):NumberObject(0),NameObject('/Ascent'):NumberObject(800),
                NameObject('/Descent'):NumberObject(-200),NameObject('/CapHeight'):NumberObject(700),
                NameObject('/StemV'):NumberObject(80),NameObject('/FontFile2'):writer._add_object(stream)})
            face=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/TrueType'),
                NameObject('/BaseFont'):name,NameObject('/FirstChar'):NumberObject(48),NameObject('/LastChar'):NumberObject(57),
                NameObject('/Widths'):ArrayObject([NumberObject(600) for _ in range(10)]),
                NameObject('/Encoding'):NameObject('/WinAnsiEncoding'),NameObject('/FontDescriptor'):writer._add_object(descriptor)})
            resources[NameObject('/F'+str(index))]=writer._add_object(face)
        for number in range(1,pages+1):
            page=writer.add_blank_page(width=595,height=842)
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):resources})
            if number==1:continue
            text=(texts or {}).get(number,str(number));x,y=(positions or {}).get(number,(290,20))
            face=(selected_fonts or {}).get(number,0)
            stream=DecodedStreamObject();stream.set_data(f'BT /F{face} 10 Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET\n'.encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
        with self.pdf.open('wb') as output:writer.write(output)
        return self.pdf

    def test_word_sized_subset_checks_exact_present_and_printed_digits(self):
        self.make_pdf()
        before=self.pdf.read_bytes();result=verify_rendered_footer(self.pdf,self.root,'ur')
        self.assertEqual(result['pagesChecked'],[2,3,4])
        self.assertFalse(result['allTenNativeGlyphOutlinesExact'])
        self.assertTrue(result['allPrintedNativeGlyphOutlinesExact'])
        self.assertTrue(result['allPrintedValuesMatchPhysicalPage'])
        self.assertEqual(result['nativeDigitSubsets'][0]['verifiedDigits'],[0,2,3,4])
        self.assertEqual(result['nativeDigitSubsets'][0]['printedDigits'],[2,3,4])
        self.assertEqual(self.pdf.read_bytes(),before)
        # Native production and candidate intake call this same deterministic
        # verifier; repeated checks must reproduce the exact recorded evidence.
        self.assertEqual(verify_rendered_footer(self.pdf,self.root,'ur'),result)

    def test_full_ten_receipt_keeps_original_fields_and_serialization(self):
        self.make_pdf(fonts=[{'digits':list(range(10))}],pages=12)
        result=verify_rendered_footer(self.pdf,self.root,'ur')
        expected={'proofSHA256':hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
                  'pagesChecked':list(range(2,13)),'allTenNativeGlyphOutlinesExact':True,
                  'allPrintedValuesMatchPhysicalPage':True}
        self.assertEqual(json.dumps(result),json.dumps(expected))

    def test_each_printed_font_has_its_own_exact_subset(self):
        self.make_pdf(fonts=[{'digits':[0,2]},{'digits':[0,3,4]}],selected_fonts={3:1,4:1})
        result=verify_rendered_footer(self.pdf,self.root,'ur')
        self.assertEqual([row['printedDigits'] for row in result['nativeDigitSubsets']],[[2],[3,4]])

    def test_missing_printed_mapping_cannot_borrow_from_another_font(self):
        self.make_pdf(fonts=[{'digits':[0,3,4]},{'digits':list(range(10))}])
        with self.assertRaisesRegex(ValueError,'Wrong native Word footer'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_wrong_printed_outline_is_rejected(self):
        self.make_pdf(fonts=[{'digits':[0,2,3,4],'bad_digit':2}])
        with self.assertRaisesRegex(ValueError,'lacks the pinned native numeral outlines'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_wrong_present_unused_outline_is_also_rejected(self):
        self.make_pdf(fonts=[{'digits':[0,2,3,4],'bad_digit':0}])
        with self.assertRaisesRegex(ValueError,'lacks the pinned native numeral outlines'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_another_native_script_font_is_not_the_pinned_persian_font(self):
        self.make_pdf(fonts=[{'digits':[0,2,3,4],'language':'ar'},{'digits':list(range(10))}])
        with self.assertRaisesRegex(ValueError,'Wrong native Word footer'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_arabic_subset_uses_its_own_pinned_outlines(self):
        self.make_pdf(fonts=[{'digits':[0,2,3,4],'language':'ar'}])
        self.assertTrue(verify_rendered_footer(self.pdf,self.root,'ar')['allPrintedNativeGlyphOutlinesExact'])

    def test_missing_or_wrong_physical_page_value_is_rejected(self):
        for text in ('','2'):
            with self.subTest(text=text):
                self.make_pdf(texts={3:text})
                with self.assertRaisesRegex(ValueError,'Wrong native Word footer'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_off_page_footer_is_rejected(self):
        for position in ((-20,20),(600,20),(290,-20)):
            with self.subTest(position=position):
                self.make_pdf(positions={3:position})
                with self.assertRaisesRegex(ValueError,'Native Word footer outside page'):verify_rendered_footer(self.pdf,self.root,'ur')

    def test_same_pdf_font_name_with_different_embedded_bytes_is_ambiguous(self):
        self.make_pdf(fonts=[{'digits':[0,2],'name':'SAMEAA+Digits'},
                             {'digits':[0,3,4],'name':'SAMEAA+Digits'}],selected_fonts={3:1,4:1})
        with self.assertRaisesRegex(ValueError,'Ambiguous Word PDF font identity'):verify_rendered_footer(self.pdf,self.root,'ur')


if __name__=='__main__':unittest.main()
