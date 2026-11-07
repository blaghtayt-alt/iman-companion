"""Selection contracts only. Fixture approvals are never publication evidence."""
from pathlib import Path
from unittest.mock import patch
import copy,json,tempfile,unittest
from book_edition_scope import select,sha,scope_fingerprint
from publish_approved_material import apply,bytes_json
from test_source_publisher import SourcePublishingTests
from build_books import canonical_key

class EditionTests(unittest.TestCase):
    def setUp(self):
        self.source=SourcePublishingTests();self.source.setUp();self.root=self.source.root
        self.row={'collection':'articles','language':'fil','id':112,'json':'materials/articles/fil/112.json'}
        self.source.write(self.row['json'],{'fixture':'Historical source fixture only'})
        self.source.write('review-note.json',{'fixture':'No actual approval'})
        self.record={'collection':'articles','language':'fil','materialId':112,'sourceFiles':[{'path':self.row['json'],'sha256':sha((self.root/self.row['json']).read_bytes())}],'sourceConditions':[{'path':'review-note.json','sha256':sha((self.root/'review-note.json').read_bytes())}],'existingWholeReview':{'handoffSHA256':'1'*64},'historicalPublication':{'commit':'2'*40}}
        self.inventory=self.source.write('inventory.json',{'schema':'iman-existing-source-review-bindings-v1','records':[self.record]})
        self.declaration={'language':'fil','collection':'articles','scopePolicy':'reviewed-source-edition-v1','sourceReviewBindings':[{'path':'inventory.json','sha256':sha(self.inventory.read_bytes())}]}
        self.unknown={'collection':'articles','language':'fil','id':18,'json':'legacy-unbound.json'}
        self.catalog={'entries':[self.unknown,self.row]}
    def tearDown(self):self.source.tearDown()
    def test_unknown_is_reported_without_approval_or_hold(self):
        before=copy.deepcopy(self.catalog);rows,report=select(self.root,self.catalog,self.declaration)
        self.assertEqual(rows,[self.row]);self.assertEqual(report['unknownLegacyRows'],[{**{k:self.unknown[k] for k in ('collection','language','id')},'reviewBinding':'UNKNOWN'}]);self.assertEqual(before,self.catalog)
        self.assertFalse(report['unknownRowsApproved']);self.assertFalse(report['unknownRowsHeld'])
    def test_existing_policy_still_requires_all_current_rows(self):
        rows,report=select(self.root,self.catalog,{'language':'fil','collection':'articles'})
        self.assertEqual(rows,self.catalog['entries']);self.assertIsNone(report)
    def test_later_actual_publisher_transaction_joins_automatically(self):
        self.source.write('materials/catalog.json',{'languages':['fil'],'scope':'current','entries':self.catalog['entries']})
        handoff,_=self.source.handoff(2);apply(self.root,handoff)
        current=json.loads((self.root/'materials/catalog.json').read_bytes());rows,report=select(self.root,current,self.declaration)
        self.assertEqual({r['id'] for r in rows},{112,2});self.assertEqual(len(report['unknownLegacyRows']),1)
        self.assertEqual([u['order'] for u in sorted([{'collection':'articles','order':112,'id':'112'},{'collection':'articles','order':2,'id':'2'}],key=canonical_key)],[2,112])
    def test_narrow_edition_is_named_on_download_surfaces(self):
        from download_tables import render_ready
        from download_page import write_catalog,REPO
        config=json.loads((Path(__file__).parent/'config.json').read_bytes())
        self.source.write('books/config.json',config)
        titles=['Reviewed Al-Ikhlas','Another approved reflection']
        book={'language':'en','collection':'tadabbur-extended','file':'Iman_Companion_en_tadabbur-extended.docx','sha256':'1'*64,'pdfSha256':'2'*64,'exportVerified':True,'previewOnly':False,'download':'https://github.com/example/fixture.docx','pdfDownload':'https://github.com/example/fixture.pdf','units':[{'id':'112:extended','title':titles[0]},{'id':'113:extended','title':titles[1]}],'collectionLabel':'Quran reflections · Reviewed Al-Ikhlas (+1)','editionScope':{'includedMaterialTitles':titles}}
        ready={('en','tadabbur-extended'):book};_,pages=render_ready(config,ready,REPO)
        self.assertIn(book['collectionLabel'],pages['en'])
        for title in titles:self.assertIn('- '+title,pages['en'])
        with patch('download_page.font_assets',return_value={}),patch('download_page.source_file',return_value=Path('fixture.pdf')),patch('download_page.cover_asset',return_value='fixture.webp'):
            catalog=write_catalog(self.root,self.root/'out',ready,{})
        self.assertEqual(catalog['languages']['en']['books'][0]['title'],book['collectionLabel'])
        self.assertEqual([x['title'] for x in catalog['languages']['en']['books'][0]['contents']],titles)
        self.assertIn(book['collectionLabel'],(self.root/'books/downloads/en/README.md').read_text(encoding='utf8'))
    def test_changed_reviewed_source_fails_instead_of_becoming_unknown(self):
        self.source.write(self.row['json'],{'fixture':'Changed after review'})
        with self.assertRaisesRegex(ValueError,'Changed edition'):select(self.root,self.catalog,self.declaration)
    def test_changed_source_condition_and_inventory_fail(self):
        self.source.write('review-note.json',{'fixture':'changed condition'})
        with self.assertRaisesRegex(ValueError,'Changed edition'):select(self.root,self.catalog,self.declaration)
        self.inventory.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'Changed edition'):select(self.root,self.catalog,self.declaration)
    def test_declared_but_invalid_typed_unit_does_not_fall_back(self):
        self.row['bookReaderUnit']={'schema':'iman-book-unit-v1','path':'missing.json','sha256':'0'*64}
        with self.assertRaises(OSError):select(self.root,self.catalog,self.declaration)
    def test_human_hold_stays_excluded(self):
        self.row['status']='held';rows,report=select(self.root,self.catalog,self.declaration)
        self.assertEqual(rows,[]);self.assertEqual(len(report['unknownLegacyRows']),1)
    def test_unknown_changes_do_not_retire_verified_narrow_edition(self):
        rows,report=select(self.root,self.catalog,self.declaration);before=scope_fingerprint(rows,report)
        self.unknown['title']='Changed unbound legacy title';rows,report=select(self.root,self.catalog,self.declaration)
        self.assertEqual(before,scope_fingerprint(rows,report))
    def test_added_approved_unit_changes_narrow_edition_fingerprint(self):
        rows,report=select(self.root,self.catalog,self.declaration);before=scope_fingerprint(rows,report)
        self.source.write('materials/catalog.json',{'languages':['fil'],'scope':'current','entries':self.catalog['entries']})
        handoff,_=self.source.handoff(35);apply(self.root,handoff)
        rows,report=select(self.root,json.loads((self.root/'materials/catalog.json').read_bytes()),self.declaration)
        self.assertNotEqual(before,scope_fingerprint(rows,report))

if __name__=='__main__':unittest.main()
