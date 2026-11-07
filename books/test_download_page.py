from pathlib import Path
import copy,json,tempfile,unittest,zipfile
from download_page import publish_bundles,REPO,write_catalog
from download_tables import release_url,COPY,COLLECTIONS
from published_library import sha
from locale_copy import locale
from bibliography import native_text

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
        return publish_bundles(self.root,self.out,ready,'0'*40,REPO,tag,self.execute)
    def test_one_book_has_both_choices_and_exact_zip(self):
        ready=self.ready();links,errors=self.publish(ready);self.assertFalse(errors);self.assertEqual(links['ru']['docx'],ready[('ru','tadabbur-extended')]['download']);self.assertEqual(links['ru']['parts'],1)
        with zipfile.ZipFile(self.out/'public-bundles/ru/Iman_Companion_ru_all-books.zip')as archive:
            self.assertEqual(set(archive.namelist()),{'Iman_Companion_ru_tadabbur-extended.docx','Iman_Companion_ru_tadabbur-extended.pdf'});self.assertEqual(archive.read('Iman_Companion_ru_tadabbur-extended.docx'),b'checked editable bytes')
    def test_unchanged_reuses_verified_release(self):
        ready=self.ready();first,_=self.publish(ready);self.commands.clear();second,errors=self.publish(ready,'second');self.assertEqual(first,second);self.assertFalse(errors);self.assertFalse(any(c[1]=='release'for c in self.commands))
    def test_withdrawal_removes_only_matching_locale(self):
        ready={**self.ready(),**self.ready('vi')};self.publish(ready);links,errors=self.publish({k:v for k,v in ready.items()if k[0]!='ru'},'withdrawal');self.assertEqual(set(links),{'vi'});self.assertFalse(errors)
        data=json.loads((self.root/'books/published-bundles.json').read_bytes());self.assertEqual(set(data['languages']),{'vi'})
    def test_source_update_rebuilds_combined_choice(self):
        ready=self.ready();self.publish(ready);book=ready[('ru','tadabbur-extended')];file=self.out/'ru-tadabbur-extended'/book['file'];file.write_bytes(b'new checked book');book['sha256']=sha(file.read_bytes());links,errors=self.publish(ready,'updated');self.assertFalse(errors);self.assertIn('/updated-bundles/',links['ru']['zip'])
    def test_changed_local_book_is_not_packaged(self):
        ready=self.ready();(self.out/'ru-tadabbur-extended'/ready[('ru','tadabbur-extended')]['file']).write_bytes(b'changed after validation');links,errors=self.publish(ready);self.assertFalse(links);self.assertEqual(len(errors),1);self.assertFalse(self.releases)
    def test_changed_remote_hash_is_not_advertised(self):
        self.corrupt=True;links,errors=self.publish(self.ready());self.assertFalse(links);self.assertEqual(len(errors),1);self.assertTrue(self.releases['test-bundles']['draft'])
    def test_legacy_hadith_and_preview_never_enter_zip(self):
        for field,value in[('hadithEdition','legacy-short'),('previewOnly',True),('exportVerified',False)]:
            ready=self.ready(collection='hadith');ready[('ru','hadith')][field]=value
            with self.assertRaises(ValueError):self.publish(ready)
    def test_all_twenty_native_empty_pages_have_no_fallback_book(self):
        fonts=self.root/'books/fonts';fonts.mkdir();(fonts/'pinned.ttf').write_bytes(b'font fixture')
        font={'files':{'Regular':'books/fonts/pinned.ttf','Bold':'books/fonts/pinned.ttf'},'sha256':{'Regular':sha(b'font fixture'),'Bold':sha(b'font fixture')}}
        config={'fonts':{'fixture':font},'languages':{l:{'font':'fixture','brand':locale(l)['nativeName'],'titles':{c:locale(l)['nativeName']for c in COLLECTIONS}}for l in COPY}}
        (self.root/'books/config.json').write_text(json.dumps(config),encoding='utf8')
        catalog=write_catalog(self.root,self.out,{},{});self.assertEqual(len(catalog['languages']),20)
        for lang,row in catalog['languages'].items():
            self.assertEqual(row['books'],[]);self.assertIsNone(row['bundle'])
            for text in[row['title'],row['included'],row['brand'],*row['downloads'].values()]:native_text(text,lang)
        self.assertEqual(write_catalog(self.root,self.out,{},{}),catalog)

if __name__=='__main__':unittest.main()
