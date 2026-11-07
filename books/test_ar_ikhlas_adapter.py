"""Source-preserving format checks on the real finite bound Arabic projection."""
from pathlib import Path
import hashlib,json,re,shutil,tempfile,unittest
from adapt_ar_ikhlas import generate

class ArabicIkhlasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=Path(__file__).resolve().parents[1]
        relative='materials/tadabbur/ikhlas-112/arabic-current-reader-binding.json';binding=json.loads((self.repo/relative).read_bytes());config=json.loads((self.repo/'books/config.json').read_bytes())
        for name in [relative,binding['sourceJSON']['path'],'books/config.json',config['quranText']['path'],config['surahNames']['path']]:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.repo/name,target)
        self.declaration={'language':'ar','collection':'tadabbur-extended','adapter':'arabic-current-ikhlas-v1','arabicReaderBinding':{'path':relative,'sha256':hashlib.sha256((self.root/relative).read_bytes()).hexdigest()}}
        self.catalog={'entries':[r for r in json.loads((self.repo/'materials/catalog.json').read_bytes())['entries']if(r.get('collection'),r.get('language'),r.get('id'))==('tadabbur','ar','112:extended')]}
    def tearDown(self):self.temp.cleanup()
    def unit(self):return generate(self.root,self.catalog,self.declaration)[0]
    def test_exact_four_current_sections_and_all_prose_quotes_preserved(self):
        unit=self.unit();source=json.loads((self.root/self.catalog['entries'][0]['json']).read_bytes())
        self.assertEqual([s['ayahKey']for s in unit['sections']],['112:1','112:2','112:3','112:4'])
        for section in unit['sections']:
            original=''.join(b['text']for b in source['entries'][section['ayahKey']]['blocks']if b['kind']=='paragraph')
            self.assertEqual(''.join(b['text']for b in section['blocks'][1:]),re.sub(r'\[[^\]]+\]','',original))
        self.assertTrue(unit['provenance']['excludedIntroduction']);self.assertTrue(unit['provenance']['excludedMixedMarkdown'])
    def test_main_ayahs_keep_the_source_words_with_explicit_canonical_numbering(self):
        unit=self.unit();source=json.loads((self.root/self.catalog['entries'][0]['json']).read_bytes())
        self.assertEqual(len(unit['provenance']['mainAyahPresentation']),4)
        for section,record in zip(unit['sections'],unit['provenance']['mainAyahPresentation']):
            original=source['entries'][section['ayahKey']]['blocks'][0]['text'];number=int(section['ayahKey'].split(':')[1])
            self.assertEqual(section['blocks'][0]['text'],original[1:-1]+' '+'١٢٣٤'[number-1])
            self.assertEqual(record['sourceTextSHA256'],hashlib.sha256(original.encode('utf8')).hexdigest())
    def test_reference_conditions_and_historical_book_note_are_preserved(self):
        unit=self.unit();spans=[s for section in unit['sections']for b in section['blocks']for s in b.get('spans',[])]
        citations=[c for s in spans for c in s.get('citations',[])];notes=[n for s in spans for n in s.get('noteTexts',[])]
        report=next(c for c in citations if c['book']=='tirmidhi'and c['number']=='3364')
        self.assertEqual(report['qualification']['text'],'حسّن بعض أهل العلم أصل الخبر')
        self.assertIn('ابن هشام، السيرة النبوية، خبر شعار المسلمين يوم بدر',notes)
        self.assertIn('البيهقي، الأسماء والصفات: 98',notes)
        self.assertEqual(unit['provenance']['sourceReferenceCount'],57)
    def test_source_change_or_foreign_catalogue_binding_is_rejected(self):
        path=self.root/self.catalog['entries'][0]['json'];original=path.read_bytes();path.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'current JSON changed'):self.unit()
        path.write_bytes(original);self.catalog['entries'][0]['json']='other.json'
        with self.assertRaisesRegex(ValueError,'catalogue identity changed'):self.unit()
    def test_unknown_semantic_runs_are_not_inferred(self):
        self.declaration['arabicReaderBinding']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'binding changed'):self.unit()

if __name__=='__main__':unittest.main()
