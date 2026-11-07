"""Publication lifecycle fixtures. Fixture bytes are not real books or releases."""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import json,tempfile,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'books'))
import automatic_publication as auto
from published_library import capture,scope_key,SCHEMA,sha,release_url

class PublicationChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.out=self.root/'candidate-output';self.out.mkdir()
        self.commit='a'*40;self.repo='example/fixture';self.tag='books-fixture-2';self.commands=[];self.remote={}
        self.config=json.loads((ROOT/'books/config.json').read_bytes());self.config.pop('audioRegistry',None)
        self.write('books/config.json',self.config);self.write('materials/catalog.json',{'entries':[]});self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[]});(self.root/'README.md').write_text('# Fixture\n',encoding='utf8')
    def tearDown(self):self.temp.cleanup()
    def write(self,name,data):
        file=self.root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    def entry(self,language,tag):
        collection='articles';ident='article-1';source='materials/'+language+'-article.txt';data=('fixture-'+language).encode();path=self.root/source;path.write_bytes(data)
        catalog=auto.read(self.root/'materials/catalog.json');catalog['entries'].append({'collection':collection,'language':language,'id':ident,'status':'published'});self.write('materials/catalog.json',catalog)
        declarations=auto.read(self.root/'books/reviewed-books.json');declarations['books'].append({'language':language,'collection':collection,'state':'reviewed-current','automaticBuild':True,'automaticRelease':True});self.write('books/reviewed-books.json',declarations)
        unit={'id':ident,'readerTextSHA256':sha(data),'sourceHashes':['b'*64],'inputBindings':[{'path':source,'sha256':sha(data)}]};unit_path='books/units/'+language+'.json';self.write(unit_path,unit)
        manifest={'sourceCommit':self.commit,'previewOnly':False,'units':[{'language':language,'collection':collection,'path':unit_path,'sha256':sha((self.root/unit_path).read_bytes())}]};self.write('books/manifest.json',manifest)
        word=b'word-fixture-'+language.encode();pdf=b'pdf-fixture-'+language.encode();name='Iman_Companion_'+language+'_articles.docx'
        book={'language':language,'collection':collection,'file':name,'sourceCommit':self.commit,'units':[unit],'exportVerified':True,'previewOnly':False,'sha256':sha(word),'pdfSha256':sha(pdf)}
        snapshot=capture(self.root,{'sourceCommit':self.commit,'previewOnly':False,'books':[book]});entry={**snapshot['entries'][0],'releaseTag':tag}
        self.remote[tag]={'tag_name':tag,'draft':False,'prerelease':False,'assets':[{'name':n,'state':'uploaded','size':len(body),'digest':'sha256:'+sha(body),'browser_download_url':release_url(self.repo,tag,n)}for n,body in [(name,word),(Path(name).with_suffix('.pdf').name,pdf)]]}
        folder=self.out/(language+'-articles');folder.mkdir();(folder/name).write_bytes(word);(folder/Path(name).with_suffix('.pdf')).write_bytes(pdf);(folder/'library-snapshot.json').write_text(json.dumps(snapshot),encoding='utf8')
        return entry,{'language':language,'collection':collection,'folder':folder.name}
    def execute(self,args,root):
        args=[str(x)for x in args];self.commands.append(args)
        if args[:2]==['gh','api']:return json.dumps(self.remote[args[2].split('/')[-1]])
        if args[:4]==['git','diff','--cached','--name-only']:
            return 'README.md\nbooks/published-library.json\n'if any(c[:2]==['git','add']for c in self.commands)else''
        return ''
    def report(self,built,failed=None):
        (self.out/'build-report.json').write_text(json.dumps({'sourceCommit':self.commit,'built':built,'unchanged':[],'failed':failed or[]}),encoding='utf8')
    def publish(self):
        # These lifecycle fixtures are deliberately not real font/PDF books.
        # The download page/bundle transport has its own real and fixture tests.
        with patch.object(auto,'ensure_main'),patch('download_page.publish',return_value={'failedBundles':[]}):return auto.publish(self.root,self.out,self.commit,self.repo,self.tag,execute=self.execute)
    def test_verified_new_pair_preserves_other_release_and_updates_all_native_pages(self):
        old,_=self.entry('ar','books-fixture-1');new,row=self.entry('en',self.tag);self.write('books/published-library.json',{'schema':SCHEMA,'entries':[old]});self.report([row]);result=self.publish()
        self.assertEqual(result['verifiedBookPairs'],2);self.assertEqual(len(list((self.root/'books/downloads').glob('*/README.md'))),20)
        text=(self.root/'README.md').read_text(encoding='utf8');self.assertIn('books-fixture-1',text);self.assertIn(self.tag,text)
        self.assertLess(next(i for i,c in enumerate(self.commands)if c[:3]==['gh','release','upload']),next(i for i,c in enumerate(self.commands)if c[:2]==['git','push']))
    def test_changed_local_pair_never_uploads(self):
        _,row=self.entry('en',self.tag);self.report([row]);(self.out/row['folder']/'Iman_Companion_en_articles.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed after final checks'):self.publish()
        self.assertEqual(self.commands,[])
    def test_remote_digest_mismatch_never_commits_links(self):
        _,row=self.entry('en',self.tag);self.report([row]);self.remote[self.tag]['assets'][0]['digest']='sha256:'+'0'*64
        with self.assertRaisesRegex(ValueError,'differs'):self.publish()
        self.assertFalse(any(c[:2]==['git','push']for c in self.commands));self.assertNotIn('releases/download',(self.root/'README.md').read_text())
    def test_withdrawal_removes_stale_link_without_replacement_build(self):
        old,_=self.entry('ar','books-fixture-1');self.write('books/published-library.json',{'schema':SCHEMA,'entries':[old]});catalog=auto.read(self.root/'materials/catalog.json');catalog['entries'][0]['status']='withdrawn';self.write('materials/catalog.json',catalog);self.report([]);result=self.publish()
        self.assertEqual(result['verifiedBookPairs'],0);self.assertEqual(result['staleScopesRemoved'],[('ar','articles')]);self.assertFalse(any(c[:3]==['gh','release','create']for c in self.commands))
    def test_one_failed_scope_does_not_prevent_working_pair_publication(self):
        _,row=self.entry('en',self.tag);self.report([row],[{'language':'ar','collection':'seerah','error':'source incomplete'}]);result=self.publish();self.assertEqual(result['newPairs'],1);self.assertEqual(len(result['failedScopes']),1)
    def test_newer_main_is_rejected(self):
        with patch.object(auto,'run',side_effect=[self.commit+'\n','c'*40+'\trefs/heads/main\n']):
            with self.assertRaisesRegex(ValueError,'Newer main'):auto.ensure_main(self.root,self.commit)
    def test_personal_or_undeclared_scopes_never_enter_publication(self):
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[{'language':'ja','collection':'combined','state':'reviewed-current','automaticBuild':True,'automaticRelease':True}]})
        with self.assertRaisesRegex(ValueError,'Non-public'):auto.scopes(self.root)
    def test_required_actual_word_layout_cannot_be_omitted(self):
        book={'file':'missing.docx'}
        with self.assertRaisesRegex(ValueError,'Actual Word layout receipt is required'):
            auto.require_word_layout({'requireActualWordLayout':True},self.out,book,'en')
        self.assertNotIn('independentWordLayoutVerification',book)
    def test_pdf_fallback_cannot_satisfy_required_word_layout(self):
        book={'file':'candidate.docx'};(self.out/'candidate.docx.word-layout.json').write_text('{}',encoding='utf8')
        with patch('word_layout_check.verify_pair',return_value={'word':None,'pdf':{}}):
            with self.assertRaisesRegex(ValueError,'receipt was not verified'):
                auto.require_word_layout({'requireActualWordLayout':True},self.out,book,'en')
        self.assertNotIn('independentWordLayoutVerification',book)
if __name__=='__main__':unittest.main()
