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

class V4EditionTests(unittest.TestCase):
    """Synthetic selector tests, never evidence of real editorial approval."""
    def setUp(self):
        from book_edition_scope import V4_POLICY,V4_SURAS,V4_SOURCE
        import hashlib
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.rows=[];pins=[]
        for n,(slug,anchor) in V4_SURAS.items():
            path=f'materials/tadabbur/{slug}/reader-en.json'
            f=self.root/path;f.parent.mkdir(parents=True,exist_ok=True)
            revision,counts,intro_count=V4_SOURCE[n]
            paragraph={'kind':'paragraph','role':'meaning','text':'Synthetic fixture text'}
            source={'language':'en','surah':n,'edition':'owner-final-'+slug,
                    'entries':{f'{n}:{i}':{'sourceSha256':revision,'blocks':[{'kind':'translation','role':'current-ayah','text':'Synthetic fixture translation'}]+[paragraph.copy() for _ in range(count-1)]} for i,count in enumerate(counts,1)}}
            if intro_count:source['introduction']={'sourceSha256':revision,'blocks':[paragraph.copy() for _ in range(intro_count)]}
            raw=json.dumps(source).encode()
            f.write_bytes(raw)
            pins.append({'surah':n,'path':path,'releaseAnchor':anchor,'gitBlobSHA1':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()})
            self.rows.append({'collection':'tadabbur','language':'en','id':f'{n}:extended','mode':'extended','surah':n,'json':path})
        self.decl={'collection':'tadabbur-extended','language':'en','scopePolicy':V4_POLICY,'selectedV4Readers':pins}
    def test_v4_pins_do_not_approve_and_no_legacy_fallback(self):
        legacy={**self.rows[0],'json':'materials/tadabbur/ar/001.json'}
        unrelated={**self.rows[0],'id':'2:extended','surah':2}
        rows,report=select(self.root,{'entries':[legacy,unrelated,self.rows[1]]},self.decl)
        self.assertEqual(rows,[])
        self.assertEqual([m['reason'] for m in report['missingV4Readers']],['v4-source-not-registered-for-books','missing-whole-material-approval'])
    def test_v4_hold_and_changed_bytes(self):
        rows,report=select(self.root,{'entries':[{**self.rows[0],'status':'held'},self.rows[1]]},self.decl)
        self.assertEqual(rows,[])
        self.assertEqual(report['missingV4Readers'][0]['reason'],'held-or-unavailable')
        (self.root/self.rows[1]['json']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'differs from verified release'):
            select(self.root,{'entries':self.rows},self.decl)
    def test_v4_japanese_is_omitted_not_replaced(self):
        rows,report=select(self.root,{'entries':[]},{**self.decl,'language':'ja','selectedV4Readers':[]})
        self.assertEqual(rows,[])
        self.assertEqual([m['reason'] for m in report['missingV4Readers']],['no-registered-v4-git-reader']*2)
    def test_v4_invalid_approval_does_not_fall_back(self):
        row={**self.rows[0],'bookReaderUnit':{'schema':'invalid'}}
        with self.assertRaisesRegex(ValueError,'Invalid declared publisher'):
            select(self.root,{'entries':[row]},self.decl)
    def test_v4_source_revision_and_full_normalized_coverage(self):
        from book_edition_scope import validate_v4_source_structure,validate_v4_unit_coverage
        reader=json.loads((self.root/self.rows[1]['json']).read_bytes())
        expected=validate_v4_source_structure(reader,112,'en')
        self.assertEqual(expected,['112:1','112:2','112:3','112:4'])
        altered=copy.deepcopy(reader)
        altered['entries']['112:1']['sourceSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source revision'):validate_v4_source_structure(altered,112,'en')
        altered=copy.deepcopy(reader);altered['introduction']['blocks'].pop()
        with self.assertRaisesRegex(ValueError,'introduction coverage'):validate_v4_source_structure(altered,112,'en')
        unit={'sections':[{'blocks':reader['introduction']['blocks']}]+[
            {'ayahKey':ident,'blocks':[{'kind':'ayah','text':'Synthetic fixture ayah'},reader['entries'][ident]['blocks'][0]]} for ident in expected]}
        validate_v4_unit_coverage(unit,reader,112,'en')
        altered=copy.deepcopy(unit);altered['sections'].pop()
        with self.assertRaisesRegex(ValueError,'every ayah'):validate_v4_unit_coverage(altered,reader,112,'en')
        altered=copy.deepcopy(unit);altered['sections'].pop(0)
        with self.assertRaisesRegex(ValueError,'introduction text'):validate_v4_unit_coverage(altered,reader,112,'en')
        altered=copy.deepcopy(unit);altered['sections'][1]['blocks'][1]['text']='Changed translation'
        with self.assertRaisesRegex(ValueError,'translation differs'):validate_v4_unit_coverage(altered,reader,112,'en')
    def test_v4_old_snapshot_cannot_use_retention(self):
        from published_library import limited_continuity,previous_edition_available
        entry={'book':{'language':'en','collection':'tadabbur-extended'}}
        with patch('published_library.current',return_value=False),patch('published_library.declaration',return_value=self.decl):
            self.assertFalse(limited_continuity(self.root,entry))
            self.assertFalse(previous_edition_available(self.root,entry))

if __name__=='__main__':unittest.main()
