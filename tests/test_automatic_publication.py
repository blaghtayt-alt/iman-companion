"""Publication lifecycle fixtures. Fixture bytes are not real books or releases."""
from pathlib import Path
from copy import deepcopy
from contextlib import redirect_stderr,redirect_stdout
from io import StringIO
from unittest.mock import patch
import json,os,signal,subprocess,tempfile,sys,threading,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'books'))
import automatic_publication as auto
from published_library import capture,scope_key,SCHEMA,sha,release_url

class CommandRunnerChecks(unittest.TestCase):
    """Real owned processes, never renderer or publication approval fixtures."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.kill_fixture_processes)
    def kill_fixture_processes(self):
        for path in self.root.glob('*.pid'):
            try:os.kill(int(path.read_text()),signal.SIGKILL)
            except (ProcessLookupError,FileNotFoundError,ValueError):pass
    @staticmethod
    def running(pid):
        # A killed, adopted child can remain a zombie until the CI init reaps it.
        stat=Path('/proc')/str(pid)/'stat'
        if stat.is_file():
            try:
                if stat.read_text().rsplit(')',1)[1].split()[0]=='Z':return False
            except FileNotFoundError:return False
        try:os.kill(pid,0)
        except ProcessLookupError:return False
        return True
    def assert_stopped(self,pid):
        deadline=time.monotonic()+.75
        while self.running(pid) and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(self.running(pid),'Owned process survived command timeout: '+str(pid))
    def run_timeout_fixture(self,mode):
        script=self.root/'owned-process-tree.py'
        script.write_text('''from pathlib import Path
import os,signal,sys,time
root=Path(sys.argv[1]);mode=sys.argv[2]
(root/'parent.pid').write_text(str(os.getpid()))
if mode=='stubborn':signal.signal(signal.SIGTERM,signal.SIG_IGN)
child=os.fork()
if child==0:
    if mode in {'stubborn','redirected'}:signal.signal(signal.SIGTERM,signal.SIG_IGN)
    if mode=='redirected':
        null=os.open(os.devnull,os.O_RDWR)
        for fd in (0,1,2):os.dup2(null,fd)
        if null>2:os.close(null)
    (root/'child.pid').write_text(str(os.getpid()))
    while True:signal.pause()
while not (root/'child.pid').exists():time.sleep(.005)
print('unique child stdout',flush=True)
print('unique child stderr',file=sys.stderr,flush=True)
if mode=='orphan-pipes':
    (root/'parent-exited').write_text('parent exits before inherited pipes close')
    os._exit(0)
while True:signal.pause()
''',encoding='utf8')
        # A cleanup guard bounds the test even if group termination regresses.
        guard=threading.Timer(5,self.kill_fixture_processes);guard.daemon=True;guard.start()
        started=time.monotonic()
        try:
            with patch.object(auto,'COMMAND_TERMINATE_GRACE_SECONDS',.1),redirect_stderr(StringIO()):
                with self.assertRaises(auto.CommandTimeoutError) as caught:
                    auto.run([sys.executable,script,self.root,mode],self.root,timeout=1)
        finally:guard.cancel()
        self.assertLess(time.monotonic()-started,4)
        self.assertEqual(str(caught.exception).count('unique child stdout'),1)
        self.assertEqual(str(caught.exception).count('unique child stderr'),1)
        parent=int((self.root/'parent.pid').read_text());child=int((self.root/'child.pid').read_text())
        return parent,child
    def test_success_preserves_utf8_stdin_and_stdout_without_progress_prefix(self):
        script=self.root/'echo-json.py'
        script.write_text('import json,sys\nprint(json.dumps({"value":sys.stdin.read()},ensure_ascii=False))\nprint("child diagnostics",file=sys.stderr)\n',encoding='utf8')
        progress=StringIO();ambient_stdout=StringIO();payload='日本語 / العربية\nexact input\n'
        with redirect_stderr(progress),redirect_stdout(ambient_stdout):
            result=auto.run([sys.executable,script],self.root,timeout=2,input=payload)
        self.assertEqual(json.loads(result),{'value':payload})
        self.assertEqual(ambient_stdout.getvalue(),'')
        self.assertIn('[command:start]',progress.getvalue());self.assertIn('[command:end]',progress.getvalue())
        self.assertNotIn('[command:',result);self.assertNotIn('child diagnostics',result)
    def test_nonzero_command_preserves_both_diagnostic_streams(self):
        script=self.root/'failure.py'
        script.write_text('import sys\nprint("stdout evidence")\nprint("stderr evidence",file=sys.stderr)\nsys.exit(7)\n',encoding='utf8')
        with redirect_stderr(StringIO()),self.assertRaises(RuntimeError) as caught:
            auto.run([sys.executable,script],self.root,timeout=2)
        self.assertNotIsInstance(caught.exception,auto.CommandTimeoutError)
        self.assertIn('stdout evidence',str(caught.exception));self.assertIn('stderr evidence',str(caught.exception))
    @unittest.skipUnless(os.name=='posix' and hasattr(os,'fork'),'Owned POSIX process group fixture')
    def test_timeout_kills_descendant_holding_pipes_after_parent_exits(self):
        parent,child=self.run_timeout_fixture('orphan-pipes')
        self.assertTrue((self.root/'parent-exited').is_file())
        self.assert_stopped(parent);self.assert_stopped(child)
    @unittest.skipUnless(os.name=='posix' and hasattr(os,'fork'),'Owned POSIX process group fixture')
    def test_timeout_escalates_stubborn_tree_without_killing_unrelated_process(self):
        survivor=subprocess.Popen([sys.executable,'-c','import signal\nwhile True:signal.pause()'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            parent,child=self.run_timeout_fixture('stubborn')
            self.assert_stopped(parent);self.assert_stopped(child);self.assertIsNone(survivor.poll())
        finally:
            survivor.kill();survivor.wait(timeout=2)
    @unittest.skipUnless(os.name=='posix' and hasattr(os,'fork'),'Owned POSIX process group fixture')
    def test_timeout_kills_stubborn_descendant_even_when_its_pipes_are_redirected(self):
        parent,child=self.run_timeout_fixture('redirected')
        self.assert_stopped(parent);self.assert_stopped(child)

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
    def test_incomplete_checkpoint_cannot_start_publication(self):
        _,row=self.entry('en',self.tag);self.report([row])
        report=auto.read(self.out/'build-report.json');report['buildComplete']=False
        self.write('candidate-output/build-report.json',report)
        with self.assertRaisesRegex(ValueError,'incomplete|complete'):
            self.publish()
        self.assertEqual(self.commands,[])
        self.assertEqual((self.root/'README.md').read_text(),'# Fixture\n')
        self.assertFalse((self.root/'books/published-library.json').exists())
    def test_remote_digest_mismatch_never_commits_links(self):
        _,row=self.entry('en',self.tag);self.report([row]);self.remote[self.tag]['assets'][0]['digest']='sha256:'+'0'*64
        with self.assertRaisesRegex(ValueError,'differs'):self.publish()
        self.assertFalse(any(c[:2]==['git','push']for c in self.commands));self.assertNotIn('releases/download',(self.root/'README.md').read_text())
    def test_withdrawal_removes_stale_link_without_replacement_build(self):
        old,_=self.entry('ar','books-fixture-1');self.write('books/published-library.json',{'schema':SCHEMA,'entries':[old]});catalog=auto.read(self.root/'materials/catalog.json');catalog['entries'][0]['status']='withdrawn';self.write('materials/catalog.json',catalog);self.report([]);result=self.publish()
        self.assertEqual(result['verifiedBookPairs'],0);self.assertEqual(result['staleScopesRemoved'],[('ar','articles')]);self.assertFalse(any(c[:3]==['gh','release','create']for c in self.commands))
    def test_one_failed_scope_does_not_prevent_working_pair_publication(self):
        _,row=self.entry('en',self.tag);self.report([row],[{'language':'ar','collection':'seerah','error':'source incomplete'}]);result=self.publish();self.assertEqual(result['newPairs'],1);self.assertEqual(len(result['failedScopes']),1)
    def test_rejected_candidate_transfer_keeps_existing_verified_downloads_and_reports_failure(self):
        old,_=self.entry('ar','books-fixture-1');self.write('books/published-library.json',{'schema':SCHEMA,'entries':[old]});self.report([])
        report=auto.read(self.out/'build-report.json');report['finalizedIntakeErrors']=[{'error':'Fixture archive hash mismatch'}]
        (self.out/'build-report.json').write_text(json.dumps(report),encoding='utf8')
        result=self.publish()
        self.assertEqual(result['verifiedBookPairs'],1);self.assertEqual(result['newPairs'],0)
        self.assertEqual(result['finalizedIntakeErrors'],report['finalizedIntakeErrors'])
        self.assertFalse(any(c[:3]==['gh','release','create'] for c in self.commands))
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
    def test_connector_consumption_waits_for_successful_remote_pair_verification(self):
        _,row=self.entry('en',self.tag);self.report([row]);self.remote[self.tag]['assets'][0]['digest']='sha256:'+'0'*64
        with patch('connector_candidate_transfer.record_published') as consume:
            with self.assertRaisesRegex(ValueError,'differs'):self.publish()
            consume.assert_not_called()
    def test_connector_receipt_is_staged_with_the_normal_library_commit(self):
        _,row=self.entry('en',self.tag);self.report([row])
        relative='materials/book-finalization-intake-history/'+'a'*64+'.json'
        def consume(root,out,entries,repo):
            self.assertTrue(any(c[:2]==['gh','api'] for c in self.commands))
            self.assertEqual(repo,self.repo);self.assertEqual(len(entries),1)
            self.write(relative,{'fixture':'synthetic publication receipt'})
        with patch('connector_candidate_transfer.record_published',side_effect=consume):
            self.publish()
        add=next(c for c in self.commands if c[:2]==['git','add'])
        self.assertIn(relative,add);self.assertIn('books/published-library.json',add)
if __name__=='__main__':unittest.main()
