from pathlib import Path
import copy,json,subprocess,sys,tempfile,unittest
from publish_approved_material import apply,prepare,bytes_json
from published_library import sha

class SourcePublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.write('materials/catalog.json',{'languages':['fil'],'scope':'current','entries':[]})
        self.write('books/assets/quran-arabic.json',{})
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[{'language':'fil','collection':'articles','adapter':'published-reader-units-v1','state':'reviewed-current','automaticBuild':True,'automaticRelease':True}]})
    def tearDown(self):self.temp.cleanup()
    def write(self,path,value):
        file=self.root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(bytes_json(value));return file
    def handoff(self,number=1,text='Nilalamang sinuri.'):
        source=f'materials/articles/fil/{number:03}.json';review=f'materials/reviews/fil/{number:03}.json';reader=f'materials/book-readers/fil/{number:03}.json'
        self.write(source,{'fixture':'Test only; no real approval or publication','text':text})
        self.write(review,{'fixture':'Test reviewer receipt only; not a real model or human approval'})
        material={'collection':'articles','language':'fil','id':number};binding={'path':source,'sha256':sha((self.root/source).read_bytes())}
        unit={'schema':'iman-book-unit-v1','language':'fil','collection':'articles','id':f'article{number:03}','order':number,'complete':True,'reviewGate':'published-current','title':f'Aralin {number}','sourceHashes':[binding['sha256']], 'readerTextSHA256':sha(text.encode()),'sections':[{'blocks':[{'kind':'paragraph','text':text}]}],'inputBindings':[binding],'catalogBindings':[material]}
        file=self.write(reader,unit)
        data={'schema':'iman-approved-material-publication-v1','expectedCatalogSHA256':sha((self.root/'materials/catalog.json').read_bytes()),'catalogEntry':{**material,'json':source,'current':True},'sourceBindings':[binding],'canonicalOrder':number,'readerUnit':{'path':reader,'sha256':sha(file.read_bytes())},'approval':{'decision':'approved','approvalId':'TEST-FIXTURE-ONLY-'+str(number),'reviewer':{'kind':'fixture','id':'No real approval'},'wholeMaterial':True,'material':material,'readerTextSHA256':unit['readerTextSHA256'],'reviewArtifacts':[{'path':review,'sha256':sha((self.root/review).read_bytes())}]}}
        return self.write('handoff.json',data),data
    def index(self,success=True):
        result=subprocess.run([sys.executable,str(Path(__file__).parent/'index_units.py'),'--root',str(self.root),'--commit','0'*40,'--language','fil','--collection','articles'],capture_output=True,text=True,encoding='utf8')
        if success:self.assertEqual(result.returncode,0,result.stderr);return json.loads((self.root/'books/manifest.json').read_bytes())
        self.assertNotEqual(result.returncode,0);return result.stderr
    def test_two_new_approved_articles_flow_into_same_book_without_manual_manifest(self):
        first,_=self.handoff();receipt=apply(self.root,first);self.assertFalse(receipt['sourceApprovalCreated']);self.assertFalse(receipt['scopeReleaseHoldsChanged']);self.assertEqual(len(self.index()['units']),1)
        second,_=self.handoff(2);apply(self.root,second);manifest=self.index();self.assertEqual({u['id']for u in manifest['units']},{'article001','article002'})
    def test_source_correction_archives_old_snapshot_and_reindexes(self):
        file,_=self.handoff();apply(self.root,file);old=(self.root/'books/units/current/fil/articles/article001.json').read_bytes()
        file,_=self.handoff(text='Bagong nilalamang sinuri.');apply(self.root,file);self.assertEqual((self.root/'books/units/history'/(sha(old)+'.json')).read_bytes(),old);self.index()
    def test_withdrawn_material_excluded_without_breaking_remaining_article(self):
        for i in[1,2]:file,_=self.handoff(i);apply(self.root,file)
        path=self.root/'materials/catalog.json';catalog=json.loads(path.read_bytes());catalog['entries'][0]['current']=False;catalog['entries'][0]['status']='held';self.write('materials/catalog.json',catalog)
        self.assertEqual([u['id']for u in self.index()['units']],['article002'])
    def test_changed_source_is_rejected_before_any_registration(self):
        file,data=self.handoff();self.write(data['sourceBindings'][0]['path'],{'text':'changed after review'})
        with self.assertRaisesRegex(ValueError,'changed approved input'):apply(self.root,file)
        self.assertFalse((self.root/'books/units/current').exists())
    def test_missing_or_other_language_approval_is_not_created(self):
        for change in['missing','wrong-language','partial']:
            file,data=self.handoff()
            if change=='missing':data['approval']['decision']='pending'
            elif change=='wrong-language':data['approval']['material']['language']='en'
            else:data['approval']['wholeMaterial']=False
            self.write('handoff.json',data)
            with self.assertRaises(ValueError):apply(self.root,file)
    def test_catalogue_race_and_reader_text_changes_are_rejected(self):
        file,data=self.handoff();data['expectedCatalogSHA256']='0'*64;self.write('handoff.json',data)
        with self.assertRaisesRegex(ValueError,'Catalogue advanced'):prepare(self.root,file)
        file,data=self.handoff();data['approval']['readerTextSHA256']='0'*64;self.write('handoff.json',data)
        with self.assertRaisesRegex(ValueError,'exact approval'):prepare(self.root,file)
    def test_unreviewed_new_catalogue_item_does_not_silently_disappear(self):
        file,_=self.handoff();apply(self.root,file);path=self.root/'materials/catalog.json';catalog=json.loads(path.read_bytes());catalog['entries'].append({'collection':'articles','language':'fil','id':2,'json':'materials/articles/fil/002.json'});self.write('materials/catalog.json',catalog)
        self.assertIn('lack book reader units',self.index(False))
    def test_tampered_registered_reader_is_detected(self):
        file,_=self.handoff();apply(self.root,file);path=self.root/'books/units/current/fil/articles/article001.json';unit=json.loads(path.read_bytes());unit['title']='Binagong pamagat';path.write_bytes(bytes_json(unit));self.assertIn('approved catalogue binding',self.index(False))

if __name__=='__main__':unittest.main()
