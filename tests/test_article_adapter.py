import hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from adapt_ar_articles import generate

def dump(p,data):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
class ArticleAdapterChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        full=json.loads((ROOT/'books/source-projections/ar-articles.json').read_bytes());self.article=next(x for x in full['articles'] if x['number']==20);projection={**full,'articles':[self.article]};path=self.root/'books/source-projections/ar-articles.json';dump(path,projection)
        fullcat=json.loads((ROOT/'materials/catalog.json').read_bytes());entry=next(x for x in fullcat['entries'] if x.get('id')==self.article['id'] and x.get('collection')=='articles');self.catalog={'languages':{'ar':'Arabic'},'entries':[entry,{'collection':'seerah','language':'ar','id':'unfinished','status':'draft'}]}
        fullindex=json.loads((ROOT/'materials/articles/prepared-ar/index.json').read_bytes());item=next(x for x in fullindex['articles'] if x['id']==self.article['id']);index={'language':'ar','articles':[item]}
        dump(self.root/'materials/catalog.json',self.catalog);dump(self.root/'materials/articles/prepared-ar/index.json',index);dest=self.root/entry['markdown'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/entry['markdown'],dest);(self.root/'books/units/current').mkdir(parents=True)
        self.declaration={'language':'ar','collection':'articles','adapter':'arabic-articles-v1','state':'reviewed-current','automaticBuild':True,'automaticRelease':False,'projection':'books/source-projections/ar-articles.json','projectionSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'materialIndex':'materials/articles/prepared-ar/index.json'}
        dump(self.root/'books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[self.declaration]})
    def tearDown(self):self.temp.cleanup()
    def test_exact_current_source_and_reference_bindings(self):
        units=generate(self.root,self.catalog,self.declaration);self.assertEqual(len(units),1);u=units[0];self.assertEqual(u['id'],self.article['id']);self.assertEqual(u['provenance']['readingSHA256'],self.article['readingSHA256'])
        blocks=[b for s in u['sections'] for b in s['blocks']]
        self.assertEqual([b['text'] for b in blocks if b['kind']!='note'],[p['text'] for p in self.article['paragraphs']])
        note_texts=[t for b in blocks for span in b.get('spans',[]) for t in span.get('noteTexts',[])]+[b['text'] for b in blocks if b['kind']=='note']
        for ref in self.article['references']:
            text=''.join(s['text'] for s in ref['segments']) if ref['segments'] else ref['text']
            self.assertTrue(any(text.strip() in note for note in note_texts),text)
    def test_changed_source_or_review_projection_is_held(self):
        path=self.root/self.catalog['entries'][0]['markdown'];path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'source bytes changed'):generate(self.root,self.catalog,self.declaration)
        path.write_bytes(path.read_bytes()[:-1]);path=self.root/self.declaration['projection'];path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'projection changed'):generate(self.root,self.catalog,self.declaration)
    def test_scope_does_not_enable_unreviewed_seerah(self):
        cmd=[sys.executable,str(ROOT/'books/index_units.py'),'--root',str(self.root),'--commit','fixture']
        good=subprocess.run(cmd+['--language','ar','--collection','articles'],capture_output=True,text=True);self.assertEqual(good.returncode,0,good.stderr)
        bad=subprocess.run(cmd+['--language','ar','--collection','seerah'],capture_output=True,text=True);self.assertNotEqual(bad.returncode,0);self.assertIn('Production indexing held',bad.stderr)
    def test_reviewed_article_cannot_hide_new_current_article(self):
        catalog=deepcopy(self.catalog);fake=deepcopy(catalog['entries'][0]);fake['id']='new-current';catalog['entries'].append(fake)
        with self.assertRaisesRegex(ValueError,'coverage changed'):generate(self.root,catalog,self.declaration)
    def test_add_revision_order_and_withdrawal_use_only_current_bindings(self):
        projection_path=self.root/self.declaration['projection'];projection=json.loads(projection_path.read_bytes())
        index_path=self.root/self.declaration['materialIndex'];index=json.loads(index_path.read_bytes())
        original=self.catalog['entries'][0];original_index=index['articles'][0];original_projection=projection['articles'][0]
        def add(ident,number):
            entry=deepcopy(original);entry['id']=ident;entry['number']=number;entry['markdown']=f'materials/articles/prepared-ar/fixture-{number}.md'
            item=deepcopy(original_index);item['id']=ident;item['number']=number;item['path']=f'fixture-{number}.md'
            reviewed=deepcopy(original_projection);reviewed['id']=ident;reviewed['number']=number
            target=self.root/entry['markdown'];shutil.copyfile(self.root/original['markdown'],target)
            self.catalog['entries'].append(entry);index['articles'].append(item);projection['articles'].append(reviewed)
            return entry,item,reviewed
        early,early_index,_=add('fixture-early',3);late,late_index,_=add('fixture-late',30)
        def refresh():
            dump(projection_path,projection);dump(index_path,index);dump(self.root/'materials/catalog.json',self.catalog)
            self.declaration['projectionSHA256']=hashlib.sha256(projection_path.read_bytes()).hexdigest()
            dump(self.root/'books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[self.declaration]})
        refresh();units=generate(self.root,self.catalog,self.declaration)
        self.assertEqual([x['number'] for x in units],[3,20,30])
        self.assertEqual([x['id'] for x in units],['fixture-early',self.article['id'],'fixture-late'])
        # A replaced revision is explicitly retired in both current indexes;
        # the reviewed projection may retain the prior record as history.
        early['status']='superseded';early_index['status']='superseded'
        replacement=deepcopy(early);replacement['id']='fixture-revised';replacement.pop('status');replacement_index=deepcopy(early_index);replacement_index['id']='fixture-revised';replacement_index.pop('status')
        replacement_projection=deepcopy(next(a for a in projection['articles'] if a['id']=='fixture-early'));replacement_projection['id']='fixture-revised'
        self.catalog['entries'].append(replacement);index['articles'].append(replacement_index);projection['articles'].append(replacement_projection)
        late['status']='withdrawn';late_index['status']='withdrawn';refresh()
        units=generate(self.root,self.catalog,self.declaration)
        self.assertEqual([x['id'] for x in units],['fixture-revised',self.article['id']])
        cmd=[sys.executable,str(ROOT/'books/index_units.py'),'--root',str(self.root),'--commit','fixture','--language','ar','--collection','articles']
        result=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
        manifest=json.loads((self.root/'books/manifest.json').read_bytes());self.assertEqual({u['id'] for u in manifest['units']},{'fixture-revised',self.article['id']})
    def test_two_current_articles_cannot_share_an_order_position(self):
        catalog=deepcopy(self.catalog);other=deepcopy(catalog['entries'][0]);other['id']='duplicate-position';catalog['entries'].append(other)
        p=self.root/self.declaration['projection'];projection=json.loads(p.read_bytes());record=deepcopy(projection['articles'][0]);record['id']='duplicate-position';projection['articles'].append(record);dump(p,projection);self.declaration['projectionSHA256']=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'order is missing or ambiguous'):generate(self.root,catalog,self.declaration)
if __name__=='__main__':unittest.main()
