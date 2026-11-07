import unittest
from pathlib import Path
import json
from book_references import reference,project_block

class ReferenceTests(unittest.TestCase):
    def setUp(self):self.names={'ar':['الفاتحة','البقرة']};self.quran={'1:1':'ا','1:2':'ب','2:1':'ت','2:2':'ث','2:3':'ج'}
    def test_original_books_share_one_binding_and_preserve_grade(self):
        value=reference('البخاري: ١٣٥٨؛ مسلم: ٢٦٥٨، حديث حسن','ar',self.names,self.quran)
        self.assertEqual([(c['book'],c['number']) for c in value['citations']],[('bukhari','1358'),('muslim','2658')])
        self.assertIn('حديث حسن',value['citations'][0]['qualification']['text'])
    def test_no_website_record_id_is_a_hadith_narration(self):
        self.assertIsNone(reference('https://hadeethenc.com/en/browse/hadith/5449','en',self.names,self.quran))
        self.assertIsNone(reference('HEC5449','en',self.names,self.quran))
    def test_explicit_quran_numbers_are_beside_ayah_not_book_footnote(self):
        self.assertEqual(reference('البقرة: ١–٣','ar',self.names,self.quran),{'verseKeys':['2:1','2:2','2:3']})
        self.assertIsNone(reference('ابن كثير، تفسير البقرة: ١','ar',self.names,self.quran))
    def test_inline_reference_only_moves_furniture_and_preserves_all_words(self):
        block={'kind':'paragraph','text':'نص الحديث [مسلم: ٨٠٩]، وقيده محفوظ.','spans':[{'text':'نص الحديث ','role':'hadith'},{'text':'[مسلم: ٨٠٩]، وقيده محفوظ.','role':'body'}]}
        value,moves=project_block(block,'ar',self.names,self.quran)
        self.assertEqual(value['text'],'نص الحديث ، وقيده محفوظ.');self.assertEqual(len(moves),1)
        self.assertEqual(value['spans'][1]['citations'],[{'type':'hadith','book':'muslim','number':'809'}])
    def test_already_moved_bibliography_anchor_is_restored_at_exact_position(self):
        original='نص [مسلم: ٨٠٩] ثم كلام.';start=original.index('[');end=original.index(']')+1
        block={'kind':'paragraph','text':original[:start]+original[end:],'bibliographyPresentation':{'originalText':original,'removedRanges':[[start,end]]}}
        value,moves=project_block(block,'ar',self.names,self.quran)
        self.assertEqual(value['text'],block['text']);self.assertTrue(value['spans'][1]['citations'])
        block['text']+='تغيير'
        with self.assertRaises(ValueError):project_block(block,'ar',self.names,self.quran)
    def test_square_bracket_meaning_note_is_not_deleted_as_reference(self):
        block={'text':'كلام [تنبيه مهم لمعنى اللفظ] ثم كلام.'}
        value,moves=project_block(block,'ar',self.names,self.quran)
        self.assertEqual(value,block);self.assertEqual(moves,[])
    def real_inputs(self):
        root=Path(__file__).resolve().parents[1];config=json.loads((root/'books/config.json').read_bytes())
        return root,json.loads((root/config['surahNames']['path']).read_bytes()),json.loads((root/config['quranText']['path']).read_bytes())
    def test_real_fatiha_intro_original_bibliography_and_span_print_one_identity(self):
        root,names,quran=self.real_inputs();source=json.loads((root/'materials/tadabbur/ar/extended/001.json').read_bytes())['entries']['intro']['blocks'][0]
        value,moves=project_block(source,'ar',names,quran)
        keys=[v for s in value['spans'] if not s.get('explicitSourceReferencePlaced') for v in s.get('verseKeys',[])]
        self.assertEqual(keys.count('51:56'),1);self.assertEqual(keys.count('20:115'),1)
        self.assertEqual(value['text'],source['text']);self.assertTrue(moves)
    def test_real_nas_original_named_reference_disambiguates_fuzzy_parallel(self):
        root,names,quran=self.real_inputs();source=json.loads((root/'materials/tadabbur/ar/extended/114.json').read_bytes())['entries']['114:5']['blocks'][1]
        value,moves=project_block(source,'ar',names,quran);keys=[v for s in value['spans'] if not s.get('explicitSourceReferencePlaced') for v in s.get('verseKeys',[])]
        self.assertEqual(keys.count('7:200'),1);self.assertEqual(keys.count('7:201'),1);self.assertNotIn('41:36',keys)
        self.assertTrue(any('41:36' in m.get('originalAdjacentSpanVerseKeys',[]) for m in moves))

if __name__=='__main__':unittest.main()
