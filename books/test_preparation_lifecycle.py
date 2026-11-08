"""Lifecycle fixtures only: no fixture represents a real approval or book."""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import json,sys,unittest
from datetime import datetime,timedelta,timezone
from test_source_publisher import SourcePublishingTests
from publish_approved_material import apply,bytes_json
from material_publication_intake import process
from published_library import capture,current,limited_continuity,merge,read,sha,SCHEMA
from book_edition_scope import select
from build_books import canonical_key
from material_order import validate_group,validate_publication
from reviewed_coverage import validate as validate_coverage
from preparation_queue import record as capture_prepared,update,load,still_prepared,artifact_available,summaries,complete
import automatic_publication as auto
import preparation_queue as queue

def record(root,index,folder,commit,holds):
    # Explicit transport fixtures, never actual rendered-book evidence.
    name=index['books'][0]['file'];(folder/name).write_bytes(b'fixture-word');(folder/Path(name).with_suffix('.pdf')).write_bytes(b'fixture-pdf')
    return capture_prepared(root,index,folder,commit,holds)

class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'GITHUB_RUN_ID':'','GITHUB_RUN_ATTEMPT':'','GITHUB_REPOSITORY':''})
        self.env.start();self.addCleanup(self.env.stop)
        self.fixture=SourcePublishingTests();self.fixture.setUp();self.root=self.fixture.root
        conf=read(Path(__file__).parent/'config.json');conf.pop('audioRegistry',None)
        self.fixture.write('books/config.json',conf);self.commit='a'*40
    def tearDown(self):self.fixture.tearDown()
    def write(self,path,value):return self.fixture.write(path,value)
    def first(self,number=1):
        file,data=self.fixture.handoff(number);receipt=apply(self.root,file)
        return receipt,data
    def checked(self):
        manifest=self.fixture.index();unit=read(self.root/manifest['units'][0]['path'])
        # The source fixture subprocess indexes with its fixed immutable commit.
        self.commit=manifest['sourceCommit']
        book={'language':'fil','collection':'articles','file':'Iman_Companion_fil_articles.docx','units':[unit],
          'sha256':sha(b'fixture-word'),'pdfSha256':sha(b'fixture-pdf'),'exportVerified':True,'preparationVerified':True,'previewOnly':False}
        index={'sourceCommit':self.commit,'previewOnly':False,'books':[book]}
        return capture(self.root,index)['entries'][0],index
    def remote(self,entry,tag='fixture-checked'):
        from published_library import asset_names,release_url
        return {'tag_name':tag,'draft':False,'prerelease':False,'assets':[{'name':name,'state':'uploaded','size':1,'digest':'sha256:'+entry['book'][hashkey],'browser_download_url':release_url('example/fixture',tag,name)} for name,hashkey in asset_names(entry['book'])]}
    def test_supplemental_font_pin_change_rebuilds_queued_scope_without_new_approval(self):
        self.first();published,index=self.checked();folder=self.root/'font-cache';folder.mkdir()
        row=record(self.root,index,folder,self.commit,[{'check':'actual-word-layout'}])
        update(self.root,[row],[])
        bindings=published['snapshot']['bindings']
        preserved={b['path']:(self.root/b['path']).read_bytes() for b in bindings}
        for path in ('materials/catalog.json','books/reviewed-books.json'):
            preserved[path]=(self.root/path).read_bytes()
        self.assertTrue(still_prepared(self.root,row))
        with patch.object(auto,'run') as run:
            unchanged=auto.build(self.root,self.root/'font-unchanged',self.commit,'example/fixture','fixture-tag')
        run.assert_not_called();self.assertEqual(len(unchanged['unchanged']),1)
        conf=read(self.root/'books/config.json');conf['fonts']['Japanese']['sha256']['Regular']='f'*64
        self.write('books/config.json',conf)
        self.assertFalse(still_prepared(self.root,row))
        # The existing verified snapshot contract remains unchanged.
        self.assertTrue(current(self.root,published))
        with patch.object(auto,'run',side_effect=RuntimeError('Fixture rebuild requested')) as run:
            rebuilt=auto.build(self.root,self.root/'font-rebuild',self.commit,'example/fixture','fixture-tag')
        run.assert_called_once();self.assertEqual(str(run.call_args.args[0][1]),'books/index_units.py')
        self.assertFalse(rebuilt['unchanged']);self.assertEqual(len(rebuilt['failed']),1)
        self.assertFalse(rebuilt['built']);self.assertFalse(rebuilt['prepared'])
        pending=load(self.root)['entries'][0]
        self.assertEqual(pending['state'],'superseded-source-awaiting-preparation')
        self.assertFalse(pending['releaseVerified'])
        for path,raw in preserved.items():self.assertEqual((self.root/path).read_bytes(),raw,path)

    def test_all_configured_supplemental_font_definitions_invalidate_preparation(self):
        self.first();_,index=self.checked();folder=self.root/'font-definitions';folder.mkdir()
        row=record(self.root,index,folder,self.commit,[]);original=read(self.root/'books/config.json')
        for name in ('Japanese','SymbolsLTR','SymbolsRTL'):
            for setting in ('pin','path','family'):
                with self.subTest(font=name,setting=setting):
                    conf=deepcopy(original);definition=conf['fonts'][name]
                    if setting=='pin':definition['sha256']['Regular']='f'*64
                    elif setting=='path':definition['files']['Regular']='books/assets/fonts/fixture-changed.ttf'
                    else:definition['family']='Fixture changed family'
                    self.write('books/config.json',conf)
                    self.assertNotEqual(queue.signature(self.root,('fil','articles')),row['inputFingerprint'])
                    self.assertFalse(still_prepared(self.root,row))
        self.write('books/config.json',original);self.assertTrue(still_prepared(self.root,row))

    def test_fallback_pin_changes_affect_all_dependent_locales_only(self):
        self.first();original=read(self.root/'books/config.json')
        declared=queue.declaration(self.root,('fil','articles'),for_release=False)
        members=queue.catalog_members(self.root,('fil','articles'),for_release=False)
        # Reuse the same fixture source selection solely to isolate each locale's
        # cache settings. These synthetic selections do not create approvals.
        with patch.object(queue,'declaration',return_value=declared),patch.object(queue,'catalog_members',return_value=members):
            languages=('th','fil','vi','en','ar')
            before={language:queue.signature(self.root,(language,'articles')) for language in languages}
            conf=deepcopy(original);conf['fonts']['Japanese']['sha256']['Regular']='f'*64
            self.write('books/config.json',conf)
            after={language:queue.signature(self.root,(language,'articles')) for language in languages}
        for language in ('th','fil','vi'):self.assertNotEqual(before[language],after[language],language)
        for language in ('en','ar'):self.assertEqual(before[language],after[language],language)

    def test_missing_required_fallback_font_rejects_cached_preparation(self):
        self.first();_,index=self.checked();folder=self.root/'missing-fallback';folder.mkdir()
        row=record(self.root,index,folder,self.commit,[]);original=read(self.root/'books/config.json')
        for missing in ('absent','empty','null'):
            with self.subTest(definition=missing):
                conf=deepcopy(original)
                if missing=='absent':conf['fonts'].pop('Japanese')
                else:conf['fonts']['Japanese']={} if missing=='empty' else None
                self.write('books/config.json',conf)
                with self.assertRaisesRegex(ValueError,'required preparation fallback font: Japanese'):
                    queue.signature(self.root,('fil','articles'))
                self.assertFalse(still_prepared(self.root,row))

    def test_optional_symbol_font_presence_is_bound_without_requiring_it(self):
        self.first();_,index=self.checked();original=read(self.root/'books/config.json')
        conf=deepcopy(original)
        for name in ('SymbolsLTR','SymbolsRTL'):conf['fonts'].pop(name)
        self.write('books/config.json',conf);folder=self.root/'optional-symbols';folder.mkdir()
        row=record(self.root,index,folder,self.commit,[]);self.assertTrue(still_prepared(self.root,row))
        for name in ('SymbolsLTR','SymbolsRTL'):
            with self.subTest(font=name):
                changed=deepcopy(conf);changed['fonts'][name]=original['fonts'][name]
                self.write('books/config.json',changed);self.assertFalse(still_prepared(self.root,row))

    def test_first_typed_article_creates_build_only_scope_without_historical_allowlist(self):
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[]})
        receipt,_=self.first(8);self.assertTrue(receipt['preparationScopeCreated']);self.assertFalse(receipt['sourceApprovalCreated'])
        declaration=read(self.root/'books/reviewed-books.json')['books'][0]
        self.assertTrue(declaration['automaticBuild']);self.assertFalse(declaration['automaticRelease']);self.assertEqual(declaration['sourceReviewBindings'],[])
        catalog=read(self.root/'materials/catalog.json');catalog['entries'].append({'collection':'articles','language':'fil','id':99,'json':'unknown-raw.json'})
        self.write('materials/catalog.json',catalog);self.assertEqual(len(select(self.root,catalog,declaration)[0]),1)
        self.assertEqual([r['id'] for r in self.fixture.index()['units']],['article008'])
        self.first(2);manifest=self.fixture.index()
        self.assertEqual([u['order'] for u in sorted([read(self.root/r['path']) for r in manifest['units']],key=canonical_key)],[2,8])
    def test_first_hadith_creates_its_own_collection(self):
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[]})
        file,data=self.fixture.handoff(2);unit=read(self.root/data['readerUnit']['path'])
        material={'collection':'essential-hadith','language':'fil','id':'essential002'}
        unit.update({'collection':'hadith','id':'essential002','hadithEdition':'new-extended','catalogBindings':[material]})
        unit['sections'][0]['blocks'][0]['citations']=[{'type':'hadith','book':'bukhari','number':'5027'}]
        reader=self.write(data['readerUnit']['path'],unit);data['readerUnit']['sha256']=sha(reader.read_bytes())
        data['catalogEntry'].update(material);data['approval']['material']=material;self.write('handoff.json',data)
        receipt=apply(self.root,file);self.assertEqual(receipt['material']['collection'],'essential-hadith')
        declared=read(self.root/'books/reviewed-books.json')['books'][0];self.assertEqual(declared['collection'],'hadith');self.assertFalse(declared['automaticRelease'])
    def test_source_push_intake_is_real_entrypoint_idempotent_and_raw_uploads_are_ignored(self):
        self.write('materials/raw-unreviewed.json',{'fixture':'not an approval'})
        self.assertFalse(process(self.root)['accepted'])
        file,_=self.fixture.handoff();self.write('materials/book-publication-intake/one.json',read(file))
        result=process(self.root);self.assertEqual(len(result['accepted']),1);self.assertFalse(result['errors'])
        before=(self.root/'materials/catalog.json').read_bytes();again=process(self.root)
        self.assertFalse(again['accepted']);self.assertEqual(len(again['unchanged']),1);self.assertEqual(before,(self.root/'materials/catalog.json').read_bytes())
    def test_multiple_intakes_use_same_source_transaction_base_and_conflicts_apply_neither(self):
        for n in [2,1]:file,_=self.fixture.handoff(n);self.write(f'materials/book-publication-intake/{n}.json',read(file))
        result=process(self.root);self.assertEqual(len(result['accepted']),2);self.assertFalse(result['errors'])
        self.assertEqual({r['id'] for r in read(self.root/'materials/catalog.json')['entries']},{1,2})
        for n,text in [(1,'Unang pagbabago.'),(2,'Ikalawang pagbabago.')]:
            file,_=self.fixture.handoff(3,text);self.write(f'materials/book-publication-intake/conflict{n}.json',read(file))
        result=process(self.root);self.assertEqual(len(result['errors']),2);self.assertNotIn(3,{r['id'] for r in read(self.root/'materials/catalog.json')['entries']})
    def test_held_and_unreviewed_intakes_never_register(self):
        for mode in ['held','unreviewed']:
            file,data=self.fixture.handoff()
            if mode=='held':data['catalogEntry']['status']='held'
            else:data['approval']['decision']='pending'
            self.write('materials/book-publication-intake/one.json',data)
            result=process(self.root);self.assertEqual(len(result['errors']),1);self.assertFalse(result['accepted'])
            self.assertFalse(read(self.root/'materials/catalog.json')['entries'])
    def test_missing_catalog_pin_is_rejected(self):
        file,data=self.fixture.handoff();data.pop('expectedCatalogSHA256');self.write('handoff.json',data)
        with self.assertRaisesRegex(ValueError,'Catalogue advanced'):apply(self.root,file)
    def test_current_edition_with_unknown_raw_rows_is_not_marked_limited(self):
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[]})
        self.first();declarations=read(self.root/'books/reviewed-books.json');declarations['books'][0]['automaticRelease']=True
        self.write('books/reviewed-books.json',declarations);old,_=self.checked()
        catalog=read(self.root/'materials/catalog.json');catalog['entries'].append({'collection':'articles','language':'fil','id':99,'json':'unknown-raw.json'})
        self.write('materials/catalog.json',catalog)
        self.assertTrue(current(self.root,old));self.assertFalse(limited_continuity(self.root,old))
    def test_additive_pending_replacement_preserves_exact_old_links_and_truthful_members(self):
        self.first();old,index=self.checked();old['releaseTag']='fixture-checked';remote=self.remote(old)
        self.first(2);self.assertFalse(current(self.root,old));self.assertTrue(limited_continuity(self.root,old))
        library,ready,stale=merge(self.root,{'schema':SCHEMA,'entries':[old]},[],'example/fixture',lambda _:remote)
        kept=ready[('fil','articles')];self.assertFalse(stale);self.assertEqual(kept['units'][0]['id'],'article001');self.assertEqual(len(kept['units']),1)
        self.assertFalse(kept['availability']['newMaterialsIncluded']);self.assertEqual(kept['sha256'],old['book']['sha256'])
        manifest=self.fixture.index();units=[read(self.root/r['path']) for r in manifest['units']]
        new=deepcopy(index);new['books'][0]['units']=units
        replacement=capture(self.root,new)['entries'][0];replacement['releaseTag']='fixture-new';replacement_remote=self.remote(replacement,'fixture-new')
        _,switched,_=merge(self.root,library,[replacement],'example/fixture',lambda tag:replacement_remote if tag=='fixture-new' else remote)
        self.assertEqual(len(switched[('fil','articles')]['units']),2);self.assertNotIn('availability',switched[('fil','articles')])
    def test_changed_held_removed_old_member_or_audio_never_uses_additive_continuity(self):
        self.first();old,_=self.checked();self.first(2)
        catalog=read(self.root/'materials/catalog.json');original=deepcopy(catalog)
        for change in ['held','removed','metadata']:
            edited=deepcopy(original)
            if change=='held':edited['entries'][0]['status']='held'
            elif change=='removed':edited['entries'].pop(0)
            else:edited['entries'][0]['title']='Changed approved member metadata'
            self.write('materials/catalog.json',edited);self.assertFalse(limited_continuity(self.root,old),change)
        self.write('materials/catalog.json',original)
        path=self.root/old['snapshot']['bindings'][0]['path'];path.write_bytes(b'Changed source or approval')
        self.assertFalse(limited_continuity(self.root,old))
    def test_new_historical_binding_file_preserves_old_edition_but_changed_revoked_old_evidence_does_not(self):
        self.first();catalog=read(self.root/'materials/catalog.json');source=catalog['entries'][0]['json']
        self.write('history-note.json',{'fixture':'Historical review identity only; no real approval'})
        def evidence(path,number,source):
            data={'schema':'iman-existing-source-review-bindings-v1','records':[{'collection':'articles','language':'fil','materialId':number,
              'sourceFiles':[{'path':source,'sha256':sha((self.root/source).read_bytes())}],
              'sourceConditions':[{'path':'history-note.json','sha256':sha((self.root/'history-note.json').read_bytes())}],
              'existingWholeReview':{'handoffSHA256':'1'*64},'historicalPublication':{'commit':'2'*40}}]}
            self.write(path,data);return {'path':path,'sha256':sha((self.root/path).read_bytes())}
        first=evidence('inventory-one.json',1,source)
        declarations=read(self.root/'books/reviewed-books.json');declared=declarations['books'][0];declared.update({'scopePolicy':'reviewed-source-edition-v1','sourceReviewBindings':[first]});self.write('books/reviewed-books.json',declarations)
        old,_=self.checked();legacy=deepcopy(old);legacy['snapshot'].pop('catalogEvidence')
        self.write('materials/historical-two.json',{'fixture':'Second reviewed historical source only'})
        second=evidence('inventory-two.json',2,'materials/historical-two.json')
        catalog['entries'].append({'collection':'articles','language':'fil','id':2,'json':'materials/historical-two.json'});self.write('materials/catalog.json',catalog)
        declared['sourceReviewBindings'].append(second);self.write('books/reviewed-books.json',declarations)
        self.assertTrue(limited_continuity(self.root,old));self.assertTrue(limited_continuity(self.root,legacy))
        self.write(second['path'],{'fixture':'New unrelated binding broke after preparation'})
        self.assertTrue(limited_continuity(self.root,old));self.assertTrue(limited_continuity(self.root,legacy))
        declared['sourceReviewBindings']=[second];self.write('books/reviewed-books.json',declarations)
        self.assertFalse(limited_continuity(self.root,old));self.assertFalse(limited_continuity(self.root,legacy))
        declared['sourceReviewBindings']=[first,second];self.write('books/reviewed-books.json',declarations);self.write(first['path'],{'fixture':'Changed old review evidence'})
        self.assertFalse(limited_continuity(self.root,old));self.assertFalse(limited_continuity(self.root,legacy))
    def test_pending_preparation_is_not_a_failed_build_or_a_release_snapshot(self):
        self.first();_,index=self.checked();folder=self.root/'out'/'fil-articles';folder.mkdir(parents=True)
        row=record(self.root,index,folder,self.commit,[{'check':'actual-word-layout'}]);update(self.root,[row],[])
        self.assertTrue(still_prepared(self.root,row));self.assertFalse(row['releaseVerified'])
        self.assertNotEqual(read(folder/'prepared-snapshot.json')['schema'],SCHEMA)
        self.assertFalse((folder/'library-snapshot.json').exists())
        self.write('unrelated-metadata.json',{'fixture':'metadata-only concurrent commit'})
        self.assertTrue(still_prepared(self.root,row))
        self.first(2);self.assertFalse(still_prepared(self.root,row));update(self.root,[],[])
        self.assertEqual(load(self.root)['entries'][0]['state'],'superseded-source-awaiting-preparation')
    def test_controller_prepares_build_only_and_unchanged_retry_does_no_renderer_work(self):
        self.first();_,index=self.checked();index['books'][0]['exportVerified']=False
        declaration=read(self.root/'books/reviewed-books.json');declaration['books'][0]['automaticRelease']=False;self.write('books/reviewed-books.json',declaration)
        out=self.root/'controller';folder=out/'fil-articles';folder.mkdir(parents=True);self.write('controller/fil-articles/index.json',index)
        (folder/index['books'][0]['file']).write_bytes(b'fixture-word');(folder/Path(index['books'][0]['file']).with_suffix('.pdf')).write_bytes(b'fixture-pdf')
        with patch.object(auto,'run',return_value=''),patch.object(auto,'check_contents',return_value={'fixture':True}):
            result=auto.build(self.root,out,self.commit,'example/fixture','fixture-tag')
        self.assertFalse(result['failed']);self.assertEqual(len(result['prepared']),1);self.assertFalse(result['built'])
        self.assertIn('actual-word-layout',{r['check'] for r in result['prepared'][0]['pendingChecks']})
        with patch.object(auto,'run',side_effect=AssertionError('Unchanged queue must not invoke the renderer')):
            again=auto.build(self.root,self.root/'retry',self.commit,'example/fixture','fixture-tag2')
        self.assertEqual(len(again['unchanged']),1);self.assertFalse(again['prepared']);self.assertFalse(again['failed'])
        self.assertEqual(len(again['preparedAwaitingReleaseQC']),1)
        status=again['preparedAwaitingReleaseQC'][0]
        self.assertEqual(status['pendingChecks'],result['prepared'][0]['pendingChecks'])
        self.assertEqual(status['includedUnits'],1)
        self.assertFalse(status['releaseVerified'])
        self.assertNotIn('candidate',status)
        self.assertNotIn('localArtifacts',status)

    def test_controller_normalizes_word_boundaries_after_last_render_before_capture(self):
        self.first();_,index=self.checked();index['books'][0]['exportVerified']=False
        out=self.root/'normalized-controller';folder=out/'fil-articles';folder.mkdir(parents=True)
        self.write('normalized-controller/fil-articles/index.json',index)
        word=folder/index['books'][0]['file'];word.write_bytes(b'fixture-word')
        word.with_suffix('.pdf').write_bytes(b'fixture-pdf')
        normalized=b'fixture-word-normalized';commands=[];toc_attempts=0
        def execute(args,root):
            nonlocal toc_attempts
            args=[str(x) for x in args];commands.append(args);script=args[1]
            if script=='books/toc_sync.py' and '--write' not in args:
                toc_attempts+=1
                if toc_attempts==1:raise RuntimeError('Fixture contents need one final render')
            if script=='books/normalize_word_page_breaks.py':word.write_bytes(normalized)
            if script=='books/check_outputs.py':
                self.assertEqual(word.read_bytes(),normalized)
                index['books'][0]['sha256']=sha(word.read_bytes())
                self.write('normalized-controller/fil-articles/index.json',index)
            return ''
        with patch.object(auto,'run',side_effect=execute),patch.object(auto,'check_contents',return_value={'fixture':True}):
            result=auto.build(self.root,out,self.commit,'example/fixture','fixture-tag')
        self.assertFalse(result['failed']);self.assertEqual(len(result['prepared']),1);self.assertFalse(result['built'])
        scripts=[c[1] for c in commands];normalize=scripts.index('books/normalize_word_page_breaks.py')
        self.assertEqual(scripts.count('books/normalize_word_page_breaks.py'),1)
        renders=[i for i,s in enumerate(scripts) if s=='books/render_uno.py']
        self.assertEqual(len(renders),3);self.assertLess(max(renders),normalize)
        self.assertLess(scripts.index('books/restore_book_fonts.py'),normalize)
        self.assertLess(normalize,scripts.index('books/check_outputs.py'))
        queued=load(self.root)['entries'];self.assertEqual(len(queued),1)
        self.assertEqual(queued[0]['candidate']['book']['sha256'],sha(normalized))
        self.assertEqual(queued[0]['localArtifacts'][0]['sha256'],sha(normalized))
        self.assertFalse(queued[0]['releaseVerified'])
        self.assertTrue({'actual-word-layout','final-visual-inspection'}.issubset({r['check'] for r in queued[0]['pendingChecks']}))

    def test_word_boundary_normalization_failure_does_not_capture_preparation(self):
        self.first();_,index=self.checked();index['books'][0]['exportVerified']=False
        out=self.root/'failed-normalization';folder=out/'fil-articles';folder.mkdir(parents=True)
        self.write('failed-normalization/fil-articles/index.json',index)
        word=folder/index['books'][0]['file'];word.write_bytes(b'fixture-word')
        word.with_suffix('.pdf').write_bytes(b'fixture-pdf');commands=[]
        def execute(args,root):
            args=[str(x) for x in args];commands.append(args)
            if args[1]=='books/normalize_word_page_breaks.py':raise RuntimeError('Fixture page-break normalization failed')
            return ''
        with patch.object(auto,'run',side_effect=execute),patch('preparation_queue.record') as capture,patch.object(auto,'check_contents') as contents:
            result=auto.build(self.root,out,self.commit,'example/fixture','fixture-tag')
        self.assertEqual(len(result['failed']),1)
        self.assertEqual(result['failed'][0]['language'],'fil');self.assertEqual(result['failed'][0]['collection'],'articles')
        self.assertIn('Fixture page-break normalization failed',result['failed'][0]['error'])
        self.assertFalse(result['prepared']);self.assertFalse(result['built'])
        capture.assert_not_called();contents.assert_not_called()
        self.assertNotIn('books/check_outputs.py',[c[1] for c in commands])
        self.assertFalse((folder/'prepared-snapshot.json').exists());self.assertFalse(load(self.root)['entries'])

    def test_queue_summary_keeps_artifact_location_and_only_completed_scope_is_removed(self):
        self.first();_,index=self.checked();folder=self.root/'pending';folder.mkdir()
        row=record(self.root,index,folder,self.commit,[{'check':'actual-word-layout','reason':'Fixture pending check'}])
        row['artifact']={'runURL':'https://github.com/example/fixture/actions/runs/123','name':'fixture-artifact'}
        other=deepcopy(row);other['language']='ar';other['collection']='seerah'
        self.write('books/prepared-library.json',{'schema':'iman-book-preparation-queue-v1','entries':[row,other]})
        before=summaries(self.root)
        self.assertEqual(before[0]['artifact'],row['artifact'])
        complete(self.root,[('fil','articles')])
        self.assertEqual(load(self.root)['entries'],[other])
    def test_release_capture_does_not_accept_build_only_scope(self):
        self.first();_,index=self.checked();declared=read(self.root/'books/reviewed-books.json');declared['books'][0]['automaticRelease']=False;self.write('books/reviewed-books.json',declared)
        self.assertEqual(capture(self.root,index,preparation=True)['schema'],'iman-prepared-book-snapshots-v1')
        with self.assertRaises(ValueError):capture(self.root,index)
    def test_expired_or_deleted_artifact_requeues_even_without_source_change(self):
        self.first();_,index=self.checked();folder=self.root/'artifact';folder.mkdir()
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'example/fixture'}):
            row=record(self.root,index,folder,self.commit,[{'check':'actual-word-layout'}])
        self.assertEqual(row['artifact']['retentionDays'],90)
        with patch('preparation_queue.artifact_available',return_value=True):self.assertTrue(still_prepared(self.root,row))
        with patch('preparation_queue.artifact_available',return_value=False):self.assertFalse(still_prepared(self.root,row))
        artifact=deepcopy(row['artifact']);artifact['expiresAt']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with patch('preparation_queue.urlopen',side_effect=AssertionError('Expired records must not make a network request')):self.assertFalse(artifact_available(artifact))
        from io import StringIO
        for data,expected in [({'artifacts':[]},False),({'artifacts':[{'name':artifact['name'],'expired':False,'size_in_bytes':100}]},True),({'artifacts':[{'name':artifact['name'],'expired':True,'size_in_bytes':100}]},False)]:
            artifact['expiresAt']=row['artifact']['expiresAt']
            with patch('preparation_queue.urlopen',return_value=StringIO(json.dumps(data))):self.assertEqual(artifact_available(artifact),expected)
    def test_render_failure_preserves_old_verified_limited_edition(self):
        self.first();old,_=self.checked();old['releaseTag']='fixture-checked';self.first(2)
        self.write('books/published-library.json',{'schema':SCHEMA,'entries':[old]})
        with patch.object(auto,'run',side_effect=RuntimeError('Fixture render failed')):
            report=auto.build(self.root,self.root/'failed-render',self.commit,'example/fixture','fixture-tag')
        self.assertEqual(len(report['failed']),1);self.assertFalse(report['prepared'])
        remote=self.remote(old);_,ready,stale=merge(self.root,{'schema':SCHEMA,'entries':[old]},[],'example/fixture',lambda _:remote)
        self.assertFalse(stale);self.assertEqual(ready[('fil','articles')]['sha256'],old['book']['sha256'])
    def test_locale_isolation_and_other_collection_changes_do_not_requeue_prepared_book(self):
        self.first();_,index=self.checked();folder=self.root/'isolated';folder.mkdir();row=record(self.root,index,folder,self.commit,[])
        catalog=read(self.root/'materials/catalog.json');catalog['entries'].append({'collection':'seerah','language':'en','id':'new-seerah099','json':'unrelated.json'});self.write('materials/catalog.json',catalog)
        self.assertTrue(still_prepared(self.root,row));self.assertTrue(current(self.root,capture(self.root,index)['entries'][0]))
    def test_reader_metadata_cannot_be_rewritten_outside_exact_approval(self):
        self.write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[]});self.first()
        catalog=read(self.root/'materials/catalog.json');binding=catalog['entries'][0]['bookReaderUnit'];unit=read(self.root/binding['path']);unit['title']='Changed after approval'
        self.write(binding['path'],unit);binding['sha256']=sha((self.root/binding['path']).read_bytes());self.write('materials/catalog.json',catalog)
        with self.assertRaisesRegex(ValueError,'approved reader snapshot'):select(self.root,catalog,read(self.root/'books/reviewed-books.json')['books'][0])

class OrderingCoverageTests(unittest.TestCase):
    def test_repeated_local_lesson_numbers_sort_by_chapter_then_lesson(self):
        units=[{'collection':'hadith','id':'chapter2lesson1','chapter':2,'lesson':1,'order':1},
          {'collection':'hadith','id':'chapter1lesson2','chapter':1,'lesson':2,'order':2},
          {'collection':'hadith','id':'chapter1lesson1','chapter':1,'lesson':1,'order':1}]
        validate_group(units)
        self.assertEqual([u['id'] for u in sorted(units,key=canonical_key)],['chapter1lesson1','chapter1lesson2','chapter2lesson1'])
        for unit in units:validate_publication(unit,unit['id'])
    def test_ambiguous_filename_needs_source_hierarchy_or_explicit_global_sequence(self):
        unit={'id':'course2lesson1','order':1}
        with self.assertRaisesRegex(ValueError,'Ambiguous'):validate_publication(unit,unit['id'])
        unit['ordering']={'kind':'global-sequence','sequence':1};validate_publication(unit,unit['id'])
        with self.assertRaisesRegex(ValueError,'Mixed'):validate_group([{'collection':'hadith',**unit},{'collection':'hadith','id':'ch1l2','order':2,'chapter':1,'lesson':2}])
    def coverage(self):
        quran={'18:1':'ا','18:2':'ب','18:3':'ت'}
        unit={'order':18,'language':'fil','title':'Aralin · Mga piling talata','sections':[{'blocks':[{'text':'Panimula.'}]},{'ayahKey':'18:1','blocks':[{'text':'ا'}]},{'ayahKey':'18:3','blocks':[{'text':'ت'}]}]}
        coverage={'schema':'iman-reviewed-quran-coverage-v1','surah':18,'ayahKeys':['18:1','18:3'],'scopeLabel':'Mga piling talata','introduction':{'state':'included','readerTextSHA256':sha('Panimula.'.encode())}}
        unit['reviewedCoverage']=coverage
        return unit,quran,{'coverage':deepcopy(coverage)}
    def test_exact_reviewed_selected_ayahs_and_introduction_are_valid_without_inventing_ayahs(self):
        unit,quran,approval=self.coverage();validate_coverage(unit,quran,approval);self.assertEqual(len(unit['sections']),3)
    def test_selected_coverage_rejects_missing_review_intro_wrong_bounds_duplicates_and_order(self):
        unit,quran,approval=self.coverage()
        with self.assertRaisesRegex(ValueError,'actual whole-material review'):validate_coverage(unit,quran,{'coverage':{}})
        for mode in ['intro','bounds','duplicate','order','label','undeclared']:
            changed=deepcopy(unit)
            if mode=='intro':changed['sections'][0]['blocks'][0]['text']='Changed introduction.'
            elif mode=='bounds':changed['sections'][-1]['ayahKey']='18:4'
            elif mode=='duplicate':changed['sections'][-1]['ayahKey']='18:1'
            elif mode=='order':changed['sections'][1:]=reversed(changed['sections'][1:])
            elif mode=='label':changed['title']='Aralin'
            else:changed.pop('reviewedCoverage')
            with self.assertRaises(ValueError,msg=mode):validate_coverage(changed,quran,approval)
    def test_quran_insertion_uses_canonical_surah_order(self):
        units=[{'collection':'tadabbur-extended','id':f'{n}:extended','order':n} for n in [112,18,1,35]]
        self.assertEqual([u['order'] for u in sorted(units,key=canonical_key)],[1,18,35,112])
        with self.assertRaisesRegex(ValueError,'Conflicting canonical surah'):canonical_key({'collection':'tadabbur-extended','id':'18:extended','order':18,'surah':35})

if __name__=='__main__':unittest.main()

