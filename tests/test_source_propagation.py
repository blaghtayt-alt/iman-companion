"""Repair regressions. Fixtures grant no real approval, Word QC or release."""
from pathlib import Path
from unittest.mock import patch
import hashlib,json,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from test_source_publisher import SourcePublishingTests
from material_publication_intake import process
from book_content_coverage import discover_readers
from locale_copy import COPY
from source_update_status import public_projection,audit
from automation_checkpoint import commit_files
from historical_book_fixture import pinned_fixture,copy_projection_fixture


def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for v in value.values():yield from strings(v)
    elif isinstance(value,list):
        for v in value:yield from strings(v)


class SourcePropagation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest=json.loads((ROOT/'books/regressions/source-propagation-fixture-20261114.json').read_bytes())
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.snapshot=Path(cls.temp.name)
        for binding in manifest['files']:
            target=cls.snapshot/binding['path'];target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(pinned_fixture(ROOT,binding['path'],binding['sha256'],manifest['commit']))

    def test_exact_user_fatiha_and_all_changed_languages_are_recorded(self):
        contract=json.loads((ROOT/'books/regressions/source-propagation-20261114.json').read_bytes())
        self.assertEqual(set(contract['fatiha']),set(COPY))
        for language,record in contract['fatiha'].items():
            with self.subTest(language=language):
                body='\n'.join(strings(json.loads((self.snapshot/record['path']).read_bytes())))
                self.assertIn(record['after'],body)
                self.assertNotIn(record['before'],body)
        arabic=contract['fatiha']['ar']
        self.assertIn('وحضور هذه المعاني في الاستفتاح يجعل التلاوة استعانة ورجاء يعيهما القلب، فلا تبقى عبارة تجري على اللسان وحده.',arabic['after'])
        self.assertEqual(len(contract['changedMaterialFiles']),283)
        self.assertFalse(contract['sourceApprovalCreated'])

    def test_review_271_329_and_exact_finite_305_correction_are_preserved(self):
        review=json.loads((ROOT/'docs/automation/source-reconciliation-20261114.json').read_bytes())
        self.assertEqual(set(map(int,review['positions'])),set(range(271,330))-{283,288,311,316})
        fix=review['appliedFiniteCorrection']
        source=json.loads((self.snapshot/fix['source']).read_bytes())['entries'][fix['entry']]['blocks'][fix['block']]
        self.assertIn(fix['after'],source['text']);self.assertNotIn(fix['before'],source['text'])
        self.assertTrue(any(fix['after'] in r.get('text','') for r in source['sourceRuns']))
        self.assertIn(fix['after'],(self.snapshot/fix['source']).with_suffix('.md').read_text())
        self.assertIn(fix['after'],'\n'.join(review['positions']['305']['after']))

    def test_omitted_readers_in_all_affected_collections_remain_visible(self):
        found=discover_readers(self.snapshot,list(COPY))
        keys={(r['language'],r['collection'],str(r['id'])) for r in found['readers']}
        expected={(lang,'tadabbur','34:extended') for lang in ['de','en','fa','fil','fr','id','ja','ms','pt-BR','ru','tr','uz','vi','zh-CN']}
        expected|={(lang,'tadabbur','35:extended') for lang in ['bn','en','fr','hi','ur']}
        expected|={(lang,'tadabbur','18:extended') for lang in ['en','th','tr']}
        expected|={(lang,'articles','prepared-ar-79fa38429519de69') for lang in ['fa','pt-BR','ur']}
        expected|={(lang,'seerah','new-seerah001') for lang in ['fr','tr','ur']}
        expected|={(lang,'essential-hadith',ident) for lang,ident in [('en','essential-01-006'),('fr','essential-01-005'),('th','essential-01-005'),('zh-CN','essential-01-005')]}
        self.assertEqual(len(expected),32)
        self.assertTrue(expected.issubset(keys),expected-keys)

    def test_status_accepts_current_then_pending_and_rejects_different_bytes(self):
        # Presentation fixtures only: they create no source/release approval.
        catalog={'languages':{language:{'books':[{'collection':'tadabbur-extended','sha256':'1'*64,'pdfSha256':'2'*64}]} for language in COPY}}
        report={'scopes':[{'language':language,'collection':'tadabbur-extended','state':'current','updatePending':False,'publishedHashes':{'docx':'1'*64,'pdf':'2'*64}} for language in COPY]}
        public=public_projection(report,catalog)
        self.assertTrue(all(not b['updatePending'] for l in public['languages'].values() for b in l['books'].values()))
        for row in report['scopes']:row.update(state='source-registration-blocked',updatePending=True)
        public=public_projection(report,catalog)
        self.assertTrue(all(b['updatePending'] for l in public['languages'].values() for b in l['books'].values()))
        for locale in catalog['languages'].values():
            for b in locale['books']:b['sha256']='0'*64
        public=public_projection(report,catalog)
        self.assertTrue(all(b['updatePending'] for l in public['languages'].values() for b in l['books'].values()))
        self.assertTrue(all(b['state']=='status-unverified' for l in public['languages'].values() for b in l['books'].values()))

    def test_discovered_reader_can_be_registered_without_permanent_pending_test(self):
        from publish_approved_material import apply
        from book_edition_scope import typed_basis
        fixture=SourcePublishingTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        _,handoff=fixture.handoff()
        source='materials/articles/current/fil/001.json'
        fixture.write(source,{'language':'fil','id':1,'text':'Nilalamang sinuri.','fixture':'No real approval'})
        binding={'path':source,'sha256':hashlib.sha256((fixture.root/source).read_bytes()).hexdigest()}
        unit=json.loads((fixture.root/handoff['readerUnit']['path']).read_bytes())
        unit.update(inputBindings=[binding],sourceHashes=[binding['sha256']])
        reader=fixture.write(handoff['readerUnit']['path'],unit)
        handoff['sourceBindings']=[binding];handoff['catalogEntry']['json']=source
        handoff['readerUnit']['sha256']=hashlib.sha256(reader.read_bytes()).hexdigest()
        file=fixture.write('handoff.json',handoff)
        self.assertEqual(len(discover_readers(fixture.root,['fil'])['readers']),1)
        receipt=apply(fixture.root,file);self.assertFalse(receipt['sourceApprovalCreated'])
        self.assertEqual(discover_readers(fixture.root,['fil'])['readers'],[])
        row=json.loads((fixture.root/'materials/catalog.json').read_bytes())['entries'][0]
        self.assertIsNotNone(typed_basis(fixture.root,row));self.assertEqual(len(fixture.index()['units']),1)
        fixture.write(source,{'language':'fil','id':1,'text':'Unreviewed later edit'})
        with self.assertRaisesRegex(ValueError,'Changed edition review/source input'):typed_basis(fixture.root,row)

    def test_historical_fixture_survives_new_catalog_and_removed_live_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=Path(temporary)/'repo';repo.mkdir();destination=Path(temporary)/'fixture'
            def git(*args):return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
            git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            path=repo/'materials/reader.json';path.parent.mkdir();raw=b'{"fixture":"Historical text, not approval"}\n';path.write_bytes(raw)
            catalog=repo/'materials/catalog.json';catalog.write_text('{"entries":[]}\n')
            git('add','.');git('commit','-m','Historical test inputs');commit=git('rev-parse','HEAD')
            binding={'path':'materials/reader.json','sha256':hashlib.sha256(raw).hexdigest()}
            inventory={'sourceCommit':commit,'records':[{'sourceFiles':[binding],'sourceConditions':[]}]}
            catalog.write_text('{"entries":[{"bookReaderUnit":{"path":"current-only-reader.json"}}]}\n');path.unlink()
            copy_projection_fixture(repo,destination,inventory,['materials/catalog.json'])
            self.assertEqual((destination/'materials/reader.json').read_bytes(),raw)
            self.assertEqual(json.loads((destination/'materials/catalog.json').read_bytes()),{'entries':[]})
            self.assertFalse(path.exists())
            self.assertIn('current-only-reader.json',catalog.read_text())
            with self.assertRaisesRegex(ValueError,'does not match its review pin'):
                pinned_fixture(repo,'materials/reader.json','0'*64,commit)

    def test_good_intake_survives_an_independent_bad_intake_and_retry(self):
        fixture=SourcePublishingTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        file,_=fixture.handoff(1);fixture.write('materials/book-publication-intake/a.json',json.loads(file.read_bytes()))
        file,bad=fixture.handoff(2);bad['approval']['decision']='pending'
        fixture.write('materials/book-publication-intake/b.json',bad)
        report=process(fixture.root)
        self.assertEqual(len(report['accepted']),1);self.assertEqual(len(report['errors']),1)
        before=(fixture.root/'materials/catalog.json').read_bytes()
        retry=process(fixture.root)
        self.assertEqual(len(retry['accepted']),0);self.assertEqual(len(retry['unchanged']),1)
        self.assertEqual(before,(fixture.root/'materials/catalog.json').read_bytes())
        self.assertFalse(report['sourceApprovalCreated'])

    def test_workflow_keeps_intake_before_validation_and_failed_run_status(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/build-word-books.yml').read_text())
        jobs=workflow['jobs'];self.assertEqual(jobs['validate']['needs'],'intake')
        self.assertEqual(jobs['publish']['needs'],['intake','validate'])
        self.assertEqual(jobs['source-coverage']['needs'],'intake')
        self.assertIn('always()',jobs['source-status']['if'])
        self.assertIn('needs.intake.outputs.commit',jobs['publish']['env']['SOURCE_COMMIT'])
        health=(ROOT/'.github/workflows/check-book-downloads.yml').read_text()
        self.assertIn('if: always()\n        run: python tools/check_live_book_bytes.py',health)


class CollisionSafeCheckpoint(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'first';self.remote=Path(self.temp.name)/'remote.git'
        subprocess.run(['git','init','--bare',str(self.remote)],check=True,capture_output=True)
        subprocess.run(['git','clone',str(self.remote),str(self.root)],check=True,capture_output=True)
        self.git('checkout','-b','main');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        (self.root/'README.md').write_text('Original unrelated content\n');self.git('add','.');self.git('commit','-m','Fixture base');self.git('push','origin','main')
        self.head=self.git('rev-parse','HEAD')
        path=self.root/'docs/books/update-status.json';path.parent.mkdir(parents=True);path.write_text('{}\n')
    def git(self,*args):return subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True,text=True).stdout.strip()
    def test_retry_is_idempotent_and_unrelated_files_are_not_staged(self):
        (self.root/'README.md').write_text('User edit, preserve without including\n')
        new=commit_files(self.root,self.head,['docs/books/update-status.json'],'Fixture checkpoint')
        self.assertNotEqual(new,self.head)
        self.assertEqual(self.git('show','HEAD:README.md'),'Original unrelated content')
        self.assertEqual(commit_files(self.root,new,['docs/books/update-status.json'],'Retry'),new)
    def test_concurrent_writer_is_rejected_without_overwrite(self):
        other=Path(self.temp.name)/'other'
        subprocess.run(['git','clone','--branch','main',str(self.remote),str(other)],check=True,capture_output=True)
        def git(*args):return subprocess.run(['git',*args],cwd=other,check=True,capture_output=True,text=True).stdout.strip()
        git('config','user.name','Other fixture');git('config','user.email','other@example.invalid')
        (other/'unrelated.txt').write_text('Concurrent writer\n');git('add','.');git('commit','-m','Concurrent fixture');git('push','origin','main')
        with self.assertRaisesRegex(ValueError,'Main advanced'):
            commit_files(self.root,self.head,['docs/books/update-status.json'],'Must not push')
        self.assertEqual(self.git('rev-parse','HEAD'),self.head)
        self.assertEqual(git('show','HEAD:unrelated.txt'),'Concurrent writer')


if __name__=='__main__':unittest.main()
