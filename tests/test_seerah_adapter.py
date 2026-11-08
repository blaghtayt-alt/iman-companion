import hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'books'))
from adapt_ar_seerah import generate
from material_audio import audio_for_unit
from check_outputs import require_complete_references
def dump(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
class NewSeerahChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.declaration=next(d for d in json.loads((ROOT/'books/reviewed-books.json').read_bytes())['books'] if d['language']=='ar' and d['collection']=='seerah')
        catalog=json.loads((ROOT/'materials/catalog.json').read_bytes());self.catalog={'languages':{'ar':'Arabic'},'entries':[e for e in catalog['entries'] if e.get('collection')=='seerah' and e.get('language')=='ar']};dump(self.root/'materials/catalog.json',self.catalog)
        declaration_path=self.root/'books/reviewed-books.json';dump(declaration_path,{'schema':'iman-reviewed-books-v1','books':[self.declaration]});projection=self.root/self.declaration['projection'];projection.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/self.declaration['projection'],projection)
        index_path=self.declaration['materialIndex'];raw=subprocess.check_output(['git','show','HEAD:'+index_path],cwd=ROOT);index=json.loads(raw);dest=self.root/index_path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        for chapter in index['chapters']:
            rel=(Path(index_path).parent/chapter['readingPath']).as_posix();dest=self.root/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(subprocess.check_output(['git','show','HEAD:'+rel],cwd=ROOT))
        (self.root/'books/units/current').mkdir(parents=True)
    def tearDown(self):self.temp.cleanup()
    def test_exact_current_edition_and_real_audio_binding(self):
        units=generate(self.root,self.catalog,self.declaration);self.assertEqual([u['id'] for u in units],['new-seerah001','new-seerah002','new-seerah003'])
        spans=[span for unit in units for section in unit['sections'] for block in section['blocks'] for span in block['spans']]
        quran=[span for span in spans if span['role']=='quran'];hadith=[span for span in spans if span['role']=='hadith']
        self.assertEqual(len(quran),28);self.assertEqual(len(hadith),24)
        self.assertTrue(all(span.get('verseKeys') for span in quran));self.assertTrue(all(span.get('citations') or span.get('noteTexts') for span in hadith))
        self.assertTrue(all(unit['referenceReadiness']=={'unboundQuranSegments':0,'unboundHadithSegments':0} for unit in units))
        seed=json.loads((ROOT/'materials/audio/publish.json').read_bytes())
        registry={**seed,'entries':[{**record,'status':'published'} for record in seed['entries']]}
        for unit in units:self.assertEqual(audio_for_unit(unit,registry)['materialId'],unit['id'])
        changed=deepcopy(units[0]);changed['sourceHashes']=['f'*64];self.assertIsNone(audio_for_unit(changed,registry))
        registry['entries'][1]['status']='withdrawn';self.assertIsNone(audio_for_unit(units[1],registry))
    def test_real_unresolved_references_block_release(self):
        path=self.root/self.declaration['projection'];projection=json.loads(path.read_bytes())
        spans=[span for chapter in projection['chapters'] for paragraph in chapter['paragraphs'] for span in paragraph['segments']]
        next(span for span in spans if span['role']=='quran').pop('verseKeys')
        hadith=next(span for span in spans if span['role']=='hadith');hadith.pop('citations',None);hadith.pop('noteTexts',None)
        dump(path,projection);self.declaration['projectionSHA256']=hashlib.sha256(path.read_bytes()).hexdigest()
        units=generate(self.root,self.catalog,self.declaration)
        readiness={'units':len(units),'auditedUnits':len(units),**{key:sum(unit['referenceReadiness'][key] for unit in units) for key in ('unboundQuranSegments','unboundHadithSegments')}}
        self.assertEqual(readiness['unboundQuranSegments'],1);self.assertEqual(readiness['unboundHadithSegments'],1)
        book={'collection':'seerah','units':[{'id':u['id']} for u in units],'referenceReadiness':readiness}
        with self.assertRaisesRegex(ValueError,'source citations are incomplete'):require_complete_references(book)
        book['referenceReadiness']['unboundQuranSegments']=book['referenceReadiness']['unboundHadithSegments']=0;require_complete_references(book)
        book['referenceReadiness']['auditedUnits']=2
        with self.assertRaisesRegex(ValueError,'source citations are incomplete'):require_complete_references(book)
    def test_stale_reading_and_unreviewed_projection_are_rejected(self):
        file=self.root/'materials/seerah/new-adult/ar/01.md';file.write_bytes(file.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'reading bytes changed'):generate(self.root,self.catalog,self.declaration)
    def test_legacy_seerah_does_not_enter_new_edition_book(self):
        cmd=[sys.executable,str(ROOT/'books/index_units.py'),'--root',str(self.root),'--commit','fixture','--language','ar','--collection','seerah'];p=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
        manifest=json.loads((self.root/'books/manifest.json').read_bytes());self.assertEqual({x['id'] for x in manifest['units']},{'new-seerah001','new-seerah002','new-seerah003'})
if __name__=='__main__':unittest.main()
