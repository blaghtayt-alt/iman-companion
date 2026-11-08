"""Synthetic metadata fixtures, never reader approvals or release evidence."""
from copy import deepcopy
from pathlib import Path
import json,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from published_library import catalog_fingerprint,current,scope_settings,sha
from automatic_publication import requires_qr_layout_update
from build_books import expected_page_layout


class EditionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=json.loads((ROOT/'books/config.json').read_bytes());self.config.pop('audioRegistry',None)
        self.write('books/config.json',self.config)
        self.write('materials/reader.json',{'fixture':'unchanged previously checked reading'})
        self.write('materials/conditions.json',{'fixture':'source conditions'})
        self.row={'collection':'articles','language':'en','id':'article-1','json':'materials/reader.json','status':'published'}
        self.catalog={'entries':[self.row]};self.write('materials/catalog.json',self.catalog)
        self.declared={'language':'en','collection':'articles','state':'reviewed-current','automaticBuild':True,'automaticRelease':True}
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[self.declared]})
        self.entry={'book':{'language':'en','collection':'articles'},'snapshot':{
            'catalogSHA256':catalog_fingerprint([self.row],None),'unitIds':['article-1'],
            'bindings':[self.binding('materials/reader.json')],
            'scopeSettingsSHA256':scope_settings(self.root,('en','articles'),['article-1'])}}
        self.record={'collection':'articles','language':'en','materialId':'article-1',
            'sourceFiles':[self.binding('materials/reader.json')],
            'sourceConditions':[self.binding('materials/conditions.json')],
            'existingWholeReview':{'handoffSHA256':'1'*64},'historicalPublication':{'commit':'2'*40}}
        self.write('materials/review-inventory.json',{'schema':'iman-existing-source-review-bindings-v1','records':[self.record]})

    def tearDown(self):self.tmp.cleanup()

    def write(self,path,value):
        file=self.root/path;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')

    def binding(self,path):return {'path':path,'sha256':sha((self.root/path).read_bytes())}

    def bind_scope(self):
        self.declared.update(scopePolicy='reviewed-source-edition-v1',sourceReviewBindings=[self.binding('materials/review-inventory.json')])
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[self.declared]})

    def test_same_members_keep_the_verified_pair_after_exact_inventory_binding(self):
        self.assertTrue(current(self.root,self.entry));before=deepcopy(self.entry)
        self.bind_scope();self.assertTrue(current(self.root,self.entry));self.assertEqual(self.entry,before)

    def test_unbound_upload_does_not_become_part_of_older_verified_edition(self):
        self.catalog['entries'].append({'collection':'articles','language':'en','id':'draft-2','json':'materials/unreviewed.json','status':'current-app-edition'})
        self.write('materials/catalog.json',self.catalog)
        self.assertFalse(current(self.root,self.entry))
        self.bind_scope();self.assertTrue(current(self.root,self.entry))
        self.assertEqual(self.entry['snapshot']['unitIds'],['article-1'])

    def test_changed_source_or_conditions_remain_rejected(self):
        self.bind_scope();self.write('materials/reader.json',{'fixture':'changed'})
        self.assertFalse(current(self.root,self.entry))
        self.write('materials/reader.json',{'fixture':'unchanged previously checked reading'})
        self.write('materials/conditions.json',{'fixture':'changed condition'})
        self.assertFalse(current(self.root,self.entry))

    def test_changed_member_identity_and_withdrawal_remain_rejected(self):
        self.bind_scope();self.row['status']='held';self.write('materials/catalog.json',self.catalog)
        self.assertFalse(current(self.root,self.entry))
        self.row['status']='published';self.row['title']='Changed included metadata';self.write('materials/catalog.json',self.catalog)
        self.assertFalse(current(self.root,self.entry))

    def test_prior_explicit_evidence_cannot_use_legacy_migration(self):
        self.bind_scope();self.entry['snapshot']['catalogEvidence']=[]
        self.assertFalse(current(self.root,self.entry))

    def test_layout_upgrade_queues_audio_books_without_rewriting_old_metadata(self):
        old={'audioPanels':[{'materialId':'lesson-1'}]};before=deepcopy(old)
        self.assertTrue(requires_qr_layout_update(old));self.assertEqual(old,before)
        old['pageLayout']=expected_page_layout();self.assertFalse(requires_qr_layout_update(old))
        self.assertFalse(requires_qr_layout_update({'audioPanels':[]}))


if __name__=='__main__':unittest.main()
