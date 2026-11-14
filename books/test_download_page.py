from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import copy,json,os,subprocess,tempfile,unittest,zipfile
import install_assets
from download_page import publish_bundles,REPO,write_catalog,source_file
from download_tables import release_url,COPY,COLLECTIONS
from published_library import sha
from locale_copy import locale
from bibliography import native_text
from download_tables import native_download_text

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.out=self.root/'out';self.out.mkdir();(self.root/'books').mkdir()
        (self.root/'books/merge_public_books.py').write_text('version 1')
        self.releases={};self.commands=[];self.corrupt=False
    def tearDown(self):self.temp.cleanup()
    def execute(self,args,root):
        self.commands.append([str(x)for x in args])
        if args[:3]==['gh','release','create']:self.releases[args[3]]={'tag_name':args[3],'draft':True,'prerelease':False,'assets':[]}
        elif args[:3]==['gh','release','upload']:
            tag=args[3];file=Path(args[4]);self.releases[tag]['assets'].append({'name':file.name,'size':file.stat().st_size,'state':'uploaded','digest':'sha256:'+('0'*64 if self.corrupt else sha(file.read_bytes())),'browser_download_url':release_url(REPO,tag,file.name)})
        elif args[:3]==['gh','release','edit']:self.releases[args[3]]['draft']=False
        elif args[:2]==['gh','api']:
            if '/releases?per_page=' in args[2]:return json.dumps(list(self.releases.values()))
            release=self.releases[args[2].rsplit('/',1)[-1]]
            if release['draft']:raise RuntimeError('GitHub does not resolve drafts by tag')
            return json.dumps(release)
        else:raise AssertionError('Unexpected command')
        return ''
    def ready(self,lang='ru',collection='tadabbur-extended'):
        name=f'Iman_Companion_{lang}_{collection}.docx';folder=self.out/(lang+'-'+collection);folder.mkdir(exist_ok=True)
        word=b'checked editable bytes';pdf=b'checked PDF bytes';(folder/name).write_bytes(word);(folder/Path(name).with_suffix('.pdf')).write_bytes(pdf)
        return {(lang,collection):{'language':lang,'collection':collection,'file':name,'sha256':sha(word),'pdfSha256':sha(pdf),'exportVerified':True,'previewOnly':False,'hadithEdition':'new-extended','download':release_url(REPO,'original',name),'pdfDownload':release_url(REPO,'original',Path(name).with_suffix('.pdf').name)}}
    def publish(self,ready,tag='test'):
        with patch('automatic_publication.ensure_main'):
            return publish_bundles(self.root,self.out,ready,'0'*40,REPO,tag,self.execute)
    def prepared_replacement(self,book):
        # Synthetic transport bytes only, never a real book or release approval.
        from preparation_queue import record
        def write(relative,value):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(value),encoding='utf8');return path
        language,collection=book['language'],book['collection'];commit='a'*40
        conf=json.loads((Path(__file__).parent/'config.json').read_bytes());conf.pop('audioRegistry',None);conf['fonts']={}
        write('books/config.json',conf)
        write('books/reviewed-books.json',{'schema':'iman-reviewed-books-v1','books':[
            {'language':language,'collection':collection,'state':'reviewed-current','automaticBuild':True,'automaticRelease':True,'edition':'new-adult'}]})
        source=write('materials/source.json',{'text':'Synthetic reviewed source fixture.'})
        write('materials/catalog.json',{'entries':[{'collection':collection,'language':language,'id':'fixture-new','status':'published','edition':'new-adult','json':'materials/source.json'}]})
        unit={'id':'fixture-new','readerTextSHA256':sha(b'Synthetic reader text.'),'sourceHashes':[sha(source.read_bytes())],
              'inputBindings':[{'path':'materials/source.json','sha256':sha(source.read_bytes())}]}
        unit_file=write('books/units/fixture.json',unit)
        manifest={'sourceCommit':commit,'previewOnly':False,'scope':{'language':language,'collection':collection},
                  'units':[{'language':language,'collection':collection,'id':unit['id'],'path':'books/units/fixture.json','sha256':sha(unit_file.read_bytes())}]}
        write('books/manifest.json',manifest)
        folder=self.out/(language+'-'+collection)
        pair={book['file']:b'new prepared A4 Word fixture',Path(book['file']).with_suffix('.pdf').name:b'new prepared A4 PDF fixture'}
        for name,raw in pair.items():(folder/name).write_bytes(raw)
        candidate=copy.deepcopy(book);candidate.update(sourceCommit=commit,preparationVerified=True,exportVerified=False,
            units=[{k:unit[k]for k in('id','readerTextSHA256','sourceHashes')}],
            sha256=sha(pair[book['file']]),pdfSha256=sha(pair[Path(book['file']).with_suffix('.pdf').name]))
        index={'sourceCommit':commit,'previewOnly':False,'books':[candidate]}
        relative=folder.relative_to(self.root)
        write(relative/'index.json',index);write(relative/'source-manifest.json',manifest)
        write(relative/(book['file']+'.reader-checks.json'),{'body':['Synthetic reader text.'],'footnotes':[]})
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'','GITHUB_RUN_ATTEMPT':'','GITHUB_REPOSITORY':''}):
            queued=record(self.root,index,folder,commit,[{'check':'actual-word-layout'},{'check':'final-visual-inspection'}])
        write('books/prepared-library.json',{'schema':'iman-book-preparation-queue-v1','entries':[queued]})
        return folder,pair
    def test_one_book_has_both_choices_and_exact_zip(self):
        ready=self.ready();links,errors=self.publish(ready);self.assertFalse(errors);self.assertEqual(links['ru']['docx'],ready[('ru','tadabbur-extended')]['download']);self.assertEqual(links['ru']['parts'],1)
        with zipfile.ZipFile(self.out/'public-bundles/ru/Iman_Companion_ru_all-books.zip')as archive:
            self.assertEqual(set(archive.namelist()),{'Iman_Companion_ru_tadabbur-extended.docx','Iman_Companion_ru_tadabbur-extended.pdf'});self.assertEqual(archive.read('Iman_Companion_ru_tadabbur-extended.docx'),b'checked editable bytes')
    def test_unchanged_reuses_verified_release(self):
        ready=self.ready();first,_=self.publish(ready);self.commands.clear();second,errors=self.publish(ready,'second');self.assertEqual(first,second);self.assertFalse(errors);self.assertFalse(any(c[1]=='release'for c in self.commands))
    def test_mixed_new_and_existing_bundles_keep_stable_locale_order(self):
        ru=self.ready();self.publish(ru);ready={**ru,**self.ready('en')};self.publish(ready,'new')
        path=self.root/'books/published-bundles.json';first=path.read_bytes()
        self.assertEqual(list(json.loads(first)['languages']),[l for l in COPY if l in {'en','ru'}])
        self.publish(ready,'unchanged');self.assertEqual(path.read_bytes(),first)
    def test_withdrawal_removes_only_matching_locale(self):
        ready={**self.ready(),**self.ready('vi')};self.publish(ready);links,errors=self.publish({k:v for k,v in ready.items()if k[0]!='ru'},'withdrawal');self.assertEqual(set(links),{'vi'});self.assertFalse(errors)
        data=json.loads((self.root/'books/published-bundles.json').read_bytes());self.assertEqual(set(data['languages']),{'vi'})
    def test_source_update_rebuilds_combined_choice(self):
        ready=self.ready();self.publish(ready);book=ready[('ru','tadabbur-extended')];file=self.out/'ru-tadabbur-extended'/book['file'];file.write_bytes(b'new checked book');book['sha256']=sha(file.read_bytes());links,errors=self.publish(ready,'updated');self.assertFalse(errors);self.assertIn('/updated-bundles/',links['ru']['zip'])
    def test_source_advance_during_upload_leaves_bundle_draft_private(self):
        with patch('automatic_publication.ensure_main',side_effect=ValueError('Newer main exists')):
            links,errors=publish_bundles(self.root,self.out,self.ready(),'0'*40,REPO,'test',self.execute)
        self.assertFalse(links);self.assertIn('Newer main',errors[0]['error'])
        self.assertTrue(self.releases['test-bundles']['draft'])
        self.assertFalse(any(c[:3]==['gh','release','edit'] for c in self.commands))
    def test_changed_local_book_is_not_packaged(self):
        ready=self.ready();(self.out/'ru-tadabbur-extended'/ready[('ru','tadabbur-extended')]['file']).write_bytes(b'changed after validation');links,errors=self.publish(ready);self.assertFalse(links);self.assertEqual(len(errors),1);self.assertFalse(self.releases)
    def test_old_verified_pair_uses_separate_cache_while_prepared_pair_stays_intact(self):
        ready=self.ready('ar','seerah');book=ready[('ar','seerah')]
        book['units']=[{'id':'fixture-old','title':'فصل سابق'}]
        originals={book['file']:b'checked editable bytes',Path(book['file']).with_suffix('.pdf').name:b'checked PDF bytes'}
        folder,prepared=self.prepared_replacement(book)
        def fetch(url,destination):destination.write_bytes(originals[url.rsplit('/',1)[-1]])
        with patch('download_page.download_archive',side_effect=fetch)as remote:
            links,errors=self.publish(ready)
            self.assertFalse(errors);self.assertEqual(links['ar']['docx'],book['download'])
            self.assertEqual(remote.call_count,2)
            with zipfile.ZipFile(self.out/'public-bundles/ar/Iman_Companion_ar_all-books.zip')as archive:
                self.assertEqual({name:archive.read(name)for name in archive.namelist()},originals)
            with patch('download_page.font_assets',return_value={}),patch('download_page.cover_asset',return_value='assets/fixture.webp')as cover:
                catalog=write_catalog(self.root,self.out,ready,links)
            self.assertEqual(catalog['languages']['ar']['books'][0]['pdfSha256'],book['pdfSha256'])
            pdf_cache=self.root/'books/.cache/download-pairs'/book['pdfSha256']/Path(book['file']).with_suffix('.pdf').name
            self.assertEqual(cover.call_args.args[1],pdf_cache)
            self.assertEqual(remote.call_count,2)
        self.assertEqual({name:(folder/name).read_bytes()for name in prepared},prepared)
        for name,raw in originals.items():self.assertEqual((self.root/'books/.cache/download-pairs'/sha(raw)/name).read_bytes(),raw)
    def test_mutating_either_prepared_file_still_rejects_local_collision(self):
        ready=self.ready('ar','seerah');book=ready[('ar','seerah')]
        for changed,requested in [('docx','pdf'),('pdf','docx')]:
            with self.subTest(changed=changed):
                folder,_=self.prepared_replacement(book)
                (folder/Path(book['file']).with_suffix('.'+changed).name).write_bytes(b'mutated after preparation')
                with patch('download_page.download_archive')as remote:
                    with self.assertRaisesRegex(ValueError,'Local checked book changed'):source_file(self.root,self.out,book,requested)
                    remote.assert_not_called()
    def test_local_preparation_marker_without_trusted_queue_is_rejected(self):
        ready=self.ready('ar','seerah');book=ready[('ar','seerah')];self.prepared_replacement(book)
        (self.root/'books/prepared-library.json').unlink()
        with patch('download_page.download_archive')as remote:
            with self.assertRaisesRegex(ValueError,'Local checked book changed'):source_file(self.root,self.out,book,'pdf')
            remote.assert_not_called()
    def test_wrong_released_bytes_are_rejected_without_changing_prepared_pair(self):
        ready=self.ready('ar','seerah');book=ready[('ar','seerah')];folder,prepared=self.prepared_replacement(book)
        with patch('download_page.download_archive',side_effect=lambda url,destination:destination.write_bytes(b'wrong published download')):
            with self.assertRaisesRegex(ValueError,'Downloaded book differs from its published hash'):source_file(self.root,self.out,book,'pdf')
        self.assertEqual({name:(folder/name).read_bytes()for name in prepared},prepared)
        cache=self.root/'books/.cache/download-pairs'/book['pdfSha256']
        self.assertEqual(list(cache.iterdir()),[])
    def test_authenticated_release_transport_fetches_both_exact_book_formats(self):
        book=self.ready()[('ru','tadabbur-extended')];folder=self.out/'ru-tadabbur-extended'
        payloads={101:(folder/book['file']).read_bytes(),102:(folder/Path(book['file']).with_suffix('.pdf')).read_bytes()}
        metadata={'tag_name':'original','assets':[
            {'id':101,'name':book['file'],'browser_download_url':book['download']},
            {'id':102,'name':Path(book['file']).with_suffix('.pdf').name,'browser_download_url':book['pdfDownload']}]}
        for file in folder.iterdir():file.unlink()
        def gh(command,**kwargs):
            if '/releases/tags/' in command[4]:return subprocess.CompletedProcess(command,0,json.dumps(metadata).encode(),b'')
            kwargs['stdout'].write(payloads[int(command[4].rsplit('/',1)[-1])])
            return subprocess.CompletedProcess(command,0,None,b'')
        token='fixture-token-not-in-command-arguments'
        with patch.dict(os.environ,{'GH_TOKEN':token},clear=True),patch.object(install_assets.subprocess,'run',side_effect=gh)as authenticated,patch.object(install_assets.urllib.request,'urlopen')as public:
            word=source_file(self.root,self.out,book,'docx');pdf=source_file(self.root,self.out,book,'pdf')
        self.assertEqual(word.read_bytes(),payloads[101]);self.assertEqual(pdf.read_bytes(),payloads[102])
        self.assertEqual(authenticated.call_count,4);public.assert_not_called()
        self.assertEqual([call.kwargs['timeout']for call in authenticated.call_args_list],[60,300,60,300])
        self.assertNotIn(token,repr(authenticated.call_args_list))
        self.assertEqual(set(word.parent.iterdir()),{word});self.assertEqual(set(pdf.parent.iterdir()),{pdf})
    def test_checked_local_and_hash_valid_cache_do_not_use_transport(self):
        book=self.ready()[('ru','tadabbur-extended')];local=self.out/'ru-tadabbur-extended'/Path(book['file']).with_suffix('.pdf')
        with patch('download_page.download_archive')as remote:
            self.assertEqual(source_file(self.root,self.out,book,'pdf'),local);remote.assert_not_called()
        cache=self.root/'books/.cache/download-pairs'/book['pdfSha256']/local.name
        cache.parent.mkdir(parents=True);cache.write_bytes(local.read_bytes());local.unlink()
        with patch('download_page.download_archive')as remote:
            self.assertEqual(source_file(self.root,self.out,book,'pdf'),cache);remote.assert_not_called()
    def test_corrupt_cache_is_replaced_only_by_verified_complete_bytes(self):
        book=self.ready()[('ru','tadabbur-extended')];local=self.out/'ru-tadabbur-extended'/Path(book['file']).with_suffix('.pdf')
        raw=local.read_bytes();local.unlink();cache=self.root/'books/.cache/download-pairs'/book['pdfSha256']/local.name
        cache.parent.mkdir(parents=True);cache.write_bytes(b'old corrupt cache')
        def fetch(url,destination):
            self.assertEqual(url,book['pdfDownload']);self.assertNotEqual(destination,cache)
            self.assertEqual(cache.read_bytes(),b'old corrupt cache');destination.write_bytes(raw)
        with patch('download_page.download_archive',side_effect=fetch)as remote:
            self.assertEqual(source_file(self.root,self.out,book,'pdf'),cache)
        remote.assert_called_once();self.assertEqual(cache.read_bytes(),raw);self.assertEqual(set(cache.parent.iterdir()),{cache})
    def test_transport_or_cache_install_failure_preserves_cache_and_prepared_pair(self):
        book=self.ready('ar','seerah')[('ar','seerah')];folder,prepared=self.prepared_replacement(book)
        cache=self.root/'books/.cache/download-pairs'/book['pdfSha256']/Path(book['file']).with_suffix('.pdf').name
        cache.parent.mkdir(parents=True);cache.write_bytes(b'old incomplete cache')
        def failed_transfer(url,destination):
            destination.write_bytes(b'partial network response')
            raise install_assets.AssetDownloadError('GitHub asset request failed (HTTP 504)')
        with patch('download_page.download_archive',side_effect=failed_transfer):
            with self.assertRaisesRegex(install_assets.AssetDownloadError,'HTTP 504'):source_file(self.root,self.out,book,'pdf')
        self.assertEqual(cache.read_bytes(),b'old incomplete cache');self.assertEqual(set(cache.parent.iterdir()),{cache})
        with patch('download_page.download_archive',side_effect=lambda url,destination:destination.write_bytes(b'checked PDF bytes')),patch('download_page.os.replace',side_effect=PermissionError('cache locked')):
            with self.assertRaisesRegex(PermissionError,'cache locked'):source_file(self.root,self.out,book,'pdf')
        self.assertEqual(cache.read_bytes(),b'old incomplete cache');self.assertEqual(set(cache.parent.iterdir()),{cache})
        self.assertEqual({name:(folder/name).read_bytes()for name in prepared},prepared)
    def test_oversized_download_is_rejected_before_payload_read_or_cache_install(self):
        book=self.ready()[('ru','tadabbur-extended')];local=self.out/'ru-tadabbur-extended'/Path(book['file']).with_suffix('.pdf');local.unlink()
        def oversized(url,destination):
            with destination.open('wb')as output:output.truncate(250_000_001)
        with patch('download_page.download_archive',side_effect=oversized),patch.object(Path,'read_bytes',side_effect=AssertionError('Oversized payload must not be read')):
            with self.assertRaisesRegex(ValueError,'Downloaded book differs from its published hash'):source_file(self.root,self.out,book,'pdf')
        self.assertEqual(list((self.root/'books/.cache/download-pairs'/book['pdfSha256']).iterdir()),[])
    def test_wrong_release_repository_scheme_basename_or_digest_never_reaches_transport(self):
        book=self.ready()[('ru','tadabbur-extended')];local=self.out/'ru-tadabbur-extended'/Path(book['file']).with_suffix('.pdf');local.unlink()
        for url in (book['pdfDownload'].replace('https://','http://'),book['pdfDownload'].replace(REPO,'other/repo'),book['pdfDownload']+'?changed=1',book['pdfDownload'].replace(local.name,'another.pdf')):
            with self.subTest(url=url),patch('download_page.download_archive')as remote:
                with self.assertRaisesRegex(ValueError,'Unexpected source release URL'):source_file(self.root,self.out,{**book,'pdfDownload':url},'pdf')
                remote.assert_not_called()
        with patch('download_page.download_archive')as remote:
            with self.assertRaisesRegex(ValueError,'Invalid source book digest'):source_file(self.root,self.out,{**book,'pdfSha256':'not-a-sha256'},'pdf')
            remote.assert_not_called()
    def test_changed_remote_hash_is_not_advertised(self):
        self.corrupt=True;links,errors=self.publish(self.ready());self.assertFalse(links);self.assertEqual(len(errors),1);self.assertTrue(self.releases['test-bundles']['draft'])
    def test_legacy_hadith_and_preview_never_enter_zip(self):
        for field,value in[('hadithEdition','legacy-short'),('previewOnly',True),('exportVerified',False)]:
            ready=self.ready(collection='hadith');ready[('ru','hadith')][field]=value
            with self.assertRaises(ValueError):self.publish(ready)
    def populated_catalog_fixture(self):
        conf=json.loads((Path(__file__).parent/'config.json').read_bytes())
        (self.root/'books/config.json').write_text(json.dumps(conf),encoding='utf8')
        ready=self.ready('en','hadith')
        ready[('en','hadith')].update(collectionLabel='Hadith',units=[{'id':'essential-01-001','title':'Hadith 1'}])
        return ready
    def test_populated_catalog_retry_keeps_exact_bytes_across_clock_changes(self):
        ready=self.populated_catalog_fixture()
        with patch('download_page.font_assets',return_value={}),patch('download_page.cover_asset',return_value='assets/fixture.webp'),patch('download_page.datetime')as clock:
            clock.now.return_value=datetime(2026,11,14,1,tzinfo=timezone.utc)
            first=write_catalog(self.root,self.out,ready,{})
            path=self.root/'docs/books/catalog.json';before=path.read_bytes()
            # Real numbered Hadith coverage has tuples in memory and lists on disk.
            self.assertEqual(json.loads(before)['languages']['en']['books'][0]['coverage']['includedNumbers']['essential-01-001'],[1,1])
            clock.now.return_value=datetime(2026,11,14,2,tzinfo=timezone.utc)
            second=write_catalog(self.root,self.out,ready,{})
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(second['updated'],first['updated'])
    def test_changed_pending_notice_updates_catalog_once_then_retries_stably(self):
        ready=self.populated_catalog_fixture()
        with patch('download_page.font_assets',return_value={}),patch('download_page.cover_asset',return_value='assets/fixture.webp'),patch('download_page.datetime')as clock:
            clock.now.return_value=datetime(2026,11,14,1,tzinfo=timezone.utc)
            first=write_catalog(self.root,self.out,ready,{})
            ready[('en','hadith')]['availability']={'state':'previous-published-edition','updatePending':True,'currentSourceVerified':False}
            clock.now.return_value=datetime(2026,11,14,2,tzinfo=timezone.utc)
            changed=write_catalog(self.root,self.out,ready,{})
            self.assertNotEqual(changed['updated'],first['updated'])
            self.assertTrue(changed['languages']['en']['books'][0]['availability']['updatePending'])
            path=self.root/'docs/books/catalog.json';before=path.read_bytes()
            clock.now.return_value=datetime(2026,11,14,3,tzinfo=timezone.utc)
            write_catalog(self.root,self.out,ready,{})
            self.assertEqual(path.read_bytes(),before)
    def test_all_twenty_native_empty_pages_have_no_fallback_book(self):
        fonts=self.root/'books/fonts';fonts.mkdir();(fonts/'pinned.ttf').write_bytes(b'font fixture')
        font={'files':{'Regular':'books/fonts/pinned.ttf','Bold':'books/fonts/pinned.ttf'},'sha256':{'Regular':sha(b'font fixture'),'Bold':sha(b'font fixture')}}
        config={'fonts':{'fixture':font},'languages':{l:{'font':'fixture','brand':locale(l)['nativeName'],'titles':{c:locale(l)['nativeName']for c in COLLECTIONS}}for l in COPY}}
        (self.root/'books/config.json').write_text(json.dumps(config),encoding='utf8')
        catalog=write_catalog(self.root,self.out,{},{});self.assertEqual(len(catalog['languages']),20)
        for lang,row in catalog['languages'].items():
            self.assertEqual(row['books'],[]);self.assertIsNone(row['bundle'])
            for text in[row['title'],row['included'],row['brand']]:native_text(text,lang)
            for text in row['downloads'].values():native_download_text(text,lang)
        self.assertEqual(write_catalog(self.root,self.out,{},{}),catalog)

if __name__=='__main__':unittest.main()
