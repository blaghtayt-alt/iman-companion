"""Isolated local Git tests; all materials and review records are fixtures."""
from pathlib import Path
import json,subprocess,unittest
import test_source_publisher as source_fixtures
from source_publication_transaction import plan,commit_and_push
from published_library import sha

def git(root,*args):
    p=subprocess.run(['git',*map(str,args)],cwd=root,capture_output=True,text=True,encoding='utf8')
    if p.returncode:raise AssertionError(p.stderr)
    return p.stdout.strip()

class SourceTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=source_fixtures.SourcePublishingTests();self.fixture.setUp();self.root=self.fixture.root
        git(self.root,'init','-b','main');git(self.root,'config','user.name','Fixture');git(self.root,'config','user.email','fixture@example.invalid')
        git(self.root,'add','materials/catalog.json','books/assets/quran-arabic.json','books/reviewed-books.json')
        git(self.root,'commit','-m','Fixture baseline');self.head=git(self.root,'rev-parse','HEAD')
        self.remote=self.root/'fixture-remote.git';git(self.root,'init','--bare','-b','main',self.remote)
        git(self.root,'remote','add','origin',self.remote);git(self.root,'push','origin','main')
    def tearDown(self):self.fixture.tearDown()
    def handoff(self):
        file,data=self.fixture.handoff();data['expectedSourceBase']=[{'path':row['path'],'sha256':None} for row in data['sourceBindings']]
        file.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return file,data
    def test_source_review_and_normalized_unit_share_one_commit(self):
        handoff,data=self.handoff();head,files,receipt,guards=plan(self.root,handoff,self.head)
        self.assertEqual(head,self.head);self.assertFalse(receipt['sourceApprovalCreated'])
        self.assertIn(data['sourceBindings'][0]['path'],files);self.assertIn(data['approval']['reviewArtifacts'][0]['path'],files)
        self.assertIn(data['readerUnit']['path'],files);self.assertIn('materials/catalog.json',files)
        self.assertTrue(any(p.startswith('books/units/current/') for p in files))
        self.assertTrue(any(p.startswith('materials/book-publication-intake/') for p in files))
        self.assertTrue(any(p.startswith('materials/book-publication-intake-history/') for p in files))
        self.assertEqual(git(self.root,'diff','--cached','--name-only'),'')
        new=commit_and_push(self.root,head,files,'Publish reviewed fixture',git(self.root,'remote','get-url','origin'),guards)
        self.assertEqual(git(self.remote,'rev-parse','refs/heads/main'),new)
        self.assertEqual(git(self.root,'rev-parse','HEAD'),head)
        catalog=json.loads(git(self.remote,'show',new+':materials/catalog.json'))
        self.assertEqual(catalog['entries'][0]['bookReaderUnit']['path'],receipt['readerUnit']['path'])
        for path in files:self.assertEqual(git(self.remote,'cat-file','-e',new+':'+path),'')
        self.assertEqual(git(self.root,'diff','--cached','--name-only'),'')
        clone=self.root/'fixture-check';git(self.root,'-c','core.autocrlf=false','clone',self.remote,clone)
        from material_publication_intake import process
        before=(clone/'materials/catalog.json').read_bytes();report=process(clone)
        self.assertFalse(report['errors']);self.assertFalse(report['accepted']);self.assertEqual(len(report['unchanged']),1)
        self.assertEqual((clone/'materials/catalog.json').read_bytes(),before)
    def test_changed_catalog_or_review_is_rejected_before_any_publish(self):
        handoff,data=self.handoff();(self.root/'materials/catalog.json').write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'catalogue differs'):plan(self.root,handoff,self.head)
        self.assertEqual(git(self.remote,'rev-parse','main'),self.head)
        original=subprocess.run(['git','show','HEAD:materials/catalog.json'],cwd=self.root,capture_output=True,check=True).stdout
        (self.root/'materials/catalog.json').write_bytes(original)
        (self.root/data['approval']['reviewArtifacts'][0]['path']).write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'changed approved input'):plan(self.root,handoff,self.head)
        self.assertEqual(git(self.remote,'rev-parse','main'),self.head)
    def test_competing_remote_head_is_never_overwritten(self):
        handoff,_=self.handoff();head,files,_,guards=plan(self.root,handoff,self.head)
        git(self.root,'commit','--allow-empty','-m','Concurrent source');git(self.root,'push','origin','main')
        newer=git(self.remote,'rev-parse','main')
        with self.assertRaisesRegex(ValueError,'Remote main advanced'):commit_and_push(self.root,head,files,'Obsolete fixture',git(self.root,'remote','get-url','origin'),guards)
        self.assertEqual(git(self.remote,'rev-parse','main'),newer)
    def test_wrong_remote_is_rejected(self):
        handoff,_=self.handoff();head,files,_,guards=plan(self.root,handoff,self.head)
        with self.assertRaisesRegex(ValueError,'remote differs'):commit_and_push(self.root,head,files,'Fixture','not-the-fixture-remote',guards)
        self.assertEqual(git(self.remote,'rev-parse','main'),self.head)
    def test_local_source_change_after_planning_cannot_be_published(self):
        handoff,data=self.handoff();head,files,_,guards=plan(self.root,handoff,self.head)
        (self.root/data['sourceBindings'][0]['path']).write_text('{"newer":"fixture"}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'Local publication input changed'):commit_and_push(self.root,head,files,'Obsolete fixture',git(self.root,'remote','get-url','origin'),guards)
        self.assertEqual(git(self.remote,'rev-parse','main'),self.head)
    def test_draft_or_wrong_language_cannot_create_a_transaction(self):
        handoff,data=self.handoff();data['approval']['wholeMaterial']=False;handoff.write_text(json.dumps(data),encoding='utf8')
        with self.assertRaisesRegex(ValueError,'whole-material approval'):plan(self.root,handoff,self.head)
        self.assertEqual(git(self.remote,'rev-parse','main'),self.head)
    def test_newer_source_cannot_be_replaced_by_old_reviewed_input(self):
        handoff,data=self.handoff();source=data['sourceBindings'][0]['path']
        git(self.root,'add',source);git(self.root,'commit','-m','Newer source arrived')
        newhead=git(self.root,'rev-parse','HEAD')
        with self.assertRaisesRegex(ValueError,'Source advanced since review'):plan(self.root,handoff,newhead)
    def test_existing_review_record_is_never_overwritten(self):
        handoff,data=self.handoff();review=data['approval']['reviewArtifacts'][0]['path']
        git(self.root,'add',review);git(self.root,'commit','-m','Existing review record')
        newhead=git(self.root,'rev-parse','HEAD');(self.root/review).write_text('{"changed":"fixture"}',encoding='utf8')
        data['approval']['reviewArtifacts'][0]['sha256']=sha((self.root/review).read_bytes())
        handoff.write_text(json.dumps(data),encoding='utf8')
        with self.assertRaisesRegex(ValueError,'review or reader input cannot be replaced'):plan(self.root,handoff,newhead)

if __name__=='__main__':unittest.main()
