from pathlib import Path
import json,copy,unittest,io,zipfile,sys,os
from unittest.mock import patch
import test_source_publisher as fixtures
from publish_approved_material import apply,bytes_json
from published_library import read,sha
from approved_reader_audio import intake,validate_source,discover,intake_path
from material_audio import audio_for_unit
from publish_material_audio import reconcile_registry,select_current_sources

class AudioIntakeTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.SourcePublishingTests();self.fixture.setUp();self.root=self.fixture.root
    def tearDown(self):self.fixture.tearDown()
    def prepare(self,collection='articles',number=1):
        file,data=self.fixture.handoff(number);reader=self.root/data['readerUnit']['path'];unit=read(reader)
        catalog_collection={'tadabbur-extended':'tadabbur','hadith':'essential-hadith','seerah':'seerah','articles':'articles'}[collection]
        ident={'tadabbur-extended':'112:extended','hadith':f'essential{number:03d}','seerah':f'new-seerah{number:03d}','articles':f'article{number:03d}'}[collection]
        material={'collection':catalog_collection,'language':'fil','id':ident};unit.update(collection=collection,id=ident,catalogBindings=[material]);data['catalogEntry'].update(material);data['approval']['material']=material
        if collection=='tadabbur-extended':
            canonical=read(Path(__file__).parent/'assets/quran-arabic.json');self.fixture.write('books/assets/quran-arabic.json',canonical);unit['order']=112;data['canonicalOrder']=112;data['catalogEntry']['mode']='extended'
            unit['sections']=[{'ayahKey':k,'blocks':[{'kind':'ayah','verseKey':k,'text':canonical[k]},{'kind':'translation','text':'PAGSUBOK LAMANG — hindi salin.','translationCredit':{'language':'fil','text':'Pagsubok lamang'}},{'kind':'paragraph','text':'PAGSUBOK LAMANG.'}]}for k in['112:1','112:2','112:3','112:4']]
            unit['readerTextSHA256']=sha(''.join(b['text']for s in unit['sections']for b in s['blocks']).encode());data['approval']['readerTextSHA256']=unit['readerTextSHA256']
        if collection=='hadith':unit['hadithEdition']='new-extended';unit['sections'][0]['blocks'][0]['citations']=[{'type':'hadith','book':'bukhari','number':'5027'}]
        if collection=='seerah':data['catalogEntry']['edition']='new-adult'
        reader.write_bytes(bytes_json(unit));data['readerUnit']['sha256']=sha(reader.read_bytes());self.fixture.write('handoff.json',data);receipt=apply(self.root,file)
        unit_path=receipt['readerUnit']['path'];unit=read(self.root/unit_path);source=data['sourceBindings'][0]
        evidence='materials/reviews/fil/audio-fixture.json';self.fixture.write(evidence,{'fixture':'Synthetic test only: NOT a real recording review or approval'})
        approval={'schema':'iman-material-audio-approval-v1','approved':True,'decision':'approved-for-publication','approvalId':'TEST-AUDIO-FIXTURE-ONLY','reviewer':{'kind':'fixture'},'materialId':unit['id'],'collection':collection,'language':'fil','sourceSHA256':unit['sourceHashes'][0],'readingSHA256':source['sha256'],'readingSource':source,'audioSHA256':sha(b'NOT-A-REAL-RECORDING'),'audioBytes':20,'reviewScope':'Fixture only, not a real listening review','reviewArtifacts':[{'path':evidence,'sha256':sha((self.root/evidence).read_bytes())}]}
        approval_file='materials/audio/approvals/'+ident.replace(':','-')+'.json';self.fixture.write(approval_file,approval)
        handoff={'schema':'iman-approved-audio-intake-v1','approvalRecord':{'path':approval_file,'sha256':sha((self.root/approval_file).read_bytes())},'bookUnit':unit_path,'pack':{'url':'https://github.com/blaghtayt-alt/iman-companion/releases/download/fixture-only/NOT-A-REAL-PACK.zip','sha256':sha(b'fixture-pack'),'bytes':12,'member':'audio/fixture.opus'}}
        path=self.fixture.write('audio-handoff.json',handoff);return path,handoff,approval,unit
    def record(self):return read(self.root/'materials/audio/publish.json')['entries'][-1]
    def test_all_four_collections_enter_audio_pipeline_without_manual_qr(self):
        for collection in['articles','hadith','seerah','tadabbur-extended']:
            file,_,_,unit=self.prepare(collection);receipt=intake(self.root,file,True);record=self.record();validate_source(self.root,record);self.assertFalse(receipt['reviewOrListeningApprovalCreated']);self.assertTrue(receipt['qrIsGeneratedByBookBuilder']);self.assertEqual(record['collection'],collection)
            published={**record,'status':'published'};self.assertIsNotNone(audio_for_unit(unit,{'schema':'iman-material-audio-v1','playerBase':'https://blaghtayt-alt.github.io/iman-companion/listen/','entries':[published]}))
            self.assertIn(record['origin']['approvedReaderAudio']['path'],receipt['files']);self.assertIn(record['origin']['bookUnit'],receipt['files'])
            self.assertTrue(set(receipt['generatedFiles']).issubset(receipt['files']))
            for binding in receipt['requiredInputs']:self.assertEqual(sha((self.root/binding['path']).read_bytes()),binding['sha256'])
        self.assertEqual(len(read(self.root/'materials/audio/publish.json')['entries']),4)
    def test_cross_collection_collision_does_not_replace_existing_audio(self):
        file,_,_,_=self.prepare();intake(self.root,file,True)
        seed=read(self.root/'materials/audio/publish.json');seed['entries'][0]['collection']='hadith';self.fixture.write('materials/audio/publish.json',seed)
        before=(self.root/'materials/audio/publish.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'another collection'):intake(self.root,file,True)
        self.assertEqual(before,(self.root/'materials/audio/publish.json').read_bytes())
    def test_generated_audio_inputs_are_managed_by_book_publication(self):
        from automatic_publication import managed_paths
        file,_,_,_=self.prepare();intake(self.root,file,True)
        self.assertIn('materials/audio/publish.json',managed_paths(self.root))
    def test_discovery_rejects_both_cross_collection_intakes(self):
        for collection in ['articles','hadith']:
            unit={'id':'shared-test-id','language':'fil','collection':collection}
            unit_path='fixture-units/'+collection+'.json';self.fixture.write(unit_path,unit)
            self.fixture.write(intake_path(unit),{'bookUnit':unit_path})
        with patch('approved_reader_audio.intake') as invoke:
            report=discover(self.root)
        self.assertFalse(report['accepted']);self.assertEqual(len(report['errors']),2);invoke.assert_not_called()
    def test_existing_pack_without_explicit_approval_never_creates_record(self):
        file,data,approval,_=self.prepare();approval['approved']=False;self.fixture.write(data['approvalRecord']['path'],approval);data['approvalRecord']['sha256']=sha((self.root/data['approvalRecord']['path']).read_bytes());self.fixture.write('audio-handoff.json',data)
        with self.assertRaises(ValueError):intake(self.root,file,True)
        self.assertFalse((self.root/'materials/audio/publish.json').exists())
    def test_wrong_language_or_source_recording_is_rejected(self):
        file,data,approval,_=self.prepare();intake(self.root,file,True)
        for field,value in[('language','en'),('sourceSHA256','0'*64),('audioSHA256','0'*64)]:
            record=copy.deepcopy(self.record());record[field]=value
            with self.assertRaises(ValueError):validate_source(self.root,record)
    def test_changed_reading_removes_current_player_and_qr_eligibility(self):
        file,_,approval,_=self.prepare();intake(self.root,file,True);record={**self.record(),'status':'published'};self.fixture.write(approval['readingSource']['path'],{'text':'changed after recording approval'})
        selected,retired=select_current_sources(self.root,[record]);self.assertFalse(selected);self.assertEqual(len(retired),1)
        result=reconcile_registry(self.root,{'entries':[record]},[],[record]);self.assertEqual(result['entries'][0]['status'],'withdrawn-source-changed')
    def test_approval_withdrawal_and_material_hold_retire_record(self):
        file,data,_,_=self.prepare();intake(self.root,file,True);record={**self.record(),'status':'published'};catalog=read(self.root/'materials/catalog.json');catalog['entries'][0]['status']='held';self.fixture.write('materials/catalog.json',catalog)
        with self.assertRaisesRegex(ValueError,'held'):validate_source(self.root,record)
        result=reconcile_registry(self.root,{'entries':[record]},[],[record]);self.assertEqual(result['entries'][0]['status'],'withdrawn-source-changed')
    def test_replacement_keeps_original_approval_input_history(self):
        file,data,approval,_=self.prepare();intake(self.root,file,True);old=self.record();approval['audioSHA256']=sha(b'NEW FIXTURE ONLY');self.fixture.write(data['approvalRecord']['path'],approval);data['approvalRecord']['sha256']=sha((self.root/data['approvalRecord']['path']).read_bytes());self.fixture.write('audio-handoff.json',data);intake(self.root,file,True)
        self.assertNotEqual(old['audioUrl'],self.record()['audioUrl']);self.assertEqual(len(list((self.root/'materials/audio/intake-history').glob('*.json'))),1)
    def test_ci_discovery_stages_new_approved_voice_without_manual_seed_or_qr(self):
        file,handoff,_,unit=self.prepare();self.fixture.write(intake_path(unit),handoff)
        self.assertFalse((self.root/'materials/audio/publish.json').exists())
        result=discover(self.root);self.assertEqual(len(result['accepted']),1);self.assertFalse(result['errors']);validate_source(self.root,self.record())
        first=(self.root/'materials/audio/publish.json').read_bytes();self.assertFalse(discover(self.root)['errors']);self.assertEqual(first,(self.root/'materials/audio/publish.json').read_bytes())
    def test_bad_or_stale_intake_does_not_stage_an_unapproved_record(self):
        file,handoff,approval,unit=self.prepare();approval['approved']=False;self.fixture.write(handoff['approvalRecord']['path'],approval);handoff['approvalRecord']['sha256']=sha((self.root/handoff['approvalRecord']['path']).read_bytes());self.fixture.write(intake_path(unit),handoff)
        report=discover(self.root);self.assertFalse(report['accepted']);self.assertEqual(len(report['errors']),1);self.assertFalse((self.root/'materials/audio/publish.json').exists())
    def test_removing_current_intake_retires_player_and_qr(self):
        file,_,_,unit=self.prepare();intake(self.root,file,True);record={**self.record(),'status':'published'};(self.root/intake_path(unit)).unlink()
        selected,retired=select_current_sources(self.root,[record]);self.assertFalse(selected);self.assertEqual(len(retired),1);self.assertEqual(reconcile_registry(self.root,{'entries':[record]},[],[record])['entries'][0]['status'],'withdrawn-source-changed')
    def test_common_source_publisher_writes_actual_audio_intake_in_same_transaction(self):
        file,handoff,approval,unit=self.prepare();source_file=self.root/'handoff.json';source=read(source_file);source['expectedCatalogSHA256']=sha((self.root/'materials/catalog.json').read_bytes());source['approvedAudioIntake']={k:handoff[k]for k in['approvalRecord','pack']};self.fixture.write('handoff.json',source)
        receipt=apply(self.root,source_file);self.assertIn(intake_path(unit),receipt['generatedFiles']);self.assertIn(handoff['approvalRecord']['path'],receipt['files']);report=discover(self.root);self.assertEqual(len(report['accepted']),1);self.assertFalse(report['errors'])
    def test_actual_ci_publisher_discovers_uploads_and_enables_all_four_qr_routes(self):
        import publish_material_audio as publisher
        packs={};units=[]
        for number,collection in enumerate(['articles','hadith','seerah','tadabbur-extended'],1):
            _,handoff,_,unit=self.prepare(collection,number);buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w')as z:z.writestr('audio/fixture.opus',b'NOT-A-REAL-RECORDING');z.writestr('TEST-ONLY.txt',collection)
            raw=buffer.getvalue();url='https://github.com/blaghtayt-alt/iman-companion/releases/download/fixture-'+collection+'/NOT-A-REAL-PACK.zip';handoff['pack'].update(url=url,sha256=sha(raw),bytes=len(raw));packs[url]=raw;self.fixture.write(intake_path(unit),handoff);units.append(unit)
        self.assertFalse((self.root/'materials/audio/publish.json').exists());(self.root/'docs/listen').mkdir(parents=True);remote={'created':False,'assets':[]}
        def release(tag):return{'tag_name':tag,'assets':copy.deepcopy(remote['assets'])}if remote['created']else None
        def gh(*args):
            if args[:2]==('release','create'):remote['created']=True
            elif args[:2]==('release','upload'):
                f=Path(args[3]);raw=f.read_bytes();remote['assets'].append({'name':f.name,'digest':'sha256:'+sha(raw),'size':len(raw)})
            else:raise AssertionError(args)
            return ''
        with patch.object(publisher,'read_release',side_effect=release),patch.object(publisher,'gh',side_effect=gh),patch.object(publisher.urllib.request,'urlopen',side_effect=lambda url,**_:io.BytesIO(packs[url])),patch.object(sys,'argv',['publish_material_audio.py','--root',str(self.root)]),patch.dict(os.environ,{'GITHUB_SHA':'0'*40}),patch('sys.stdout',new_callable=io.StringIO):publisher.main()
        registry=read(self.root/'materials/audio/registry.json');self.assertEqual(len(registry['entries']),4);self.assertEqual(len(remote['assets']),4)
        for unit in units:self.assertIsNotNone(audio_for_unit(unit,registry))

if __name__=='__main__':unittest.main()
