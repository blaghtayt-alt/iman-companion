"""Publish the public, exact-language library and both combined-download forms.

Inputs are remotely verified current book pairs from published_library.merge.
Personal selected-material editions are deliberately outside this schema.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,os,re,tempfile,zipfile
from install_assets import download_archive
from download_tables import COLLECTIONS,COPY,release_url,download_labels
from locale_copy import locale,NATIVE_DIGITS
from published_library import sha,read,inside,asset_names
from merge_public_books import merge_docx,merge_pdf
from temporary_test_labels import decorate_catalog_row

SCHEMA='iman-published-book-bundles-v1'
REPO='blaghtayt-alt/iman-companion'

def inventory(ready,language):
    rows=[ready[(language,c)]for c in COLLECTIONS if(language,c)in ready]
    for row in rows:
        if row.get('language')!=language or row.get('exportVerified')is not True or row.get('previewOnly')is not False:raise ValueError('Unverified public bundle constituent')
        asset_names(row)
    return rows

def fingerprint(root,books):
    # Bundle changes when a part changes, or when its merger is fixed.
    payload={'books':[{k:b[k]for k in('language','collection','sha256','pdfSha256')}for b in books],
      'merger':sha((root/'books/merge_public_books.py').read_bytes()),'version':1}
    return sha(json.dumps(payload,sort_keys=True,separators=(',',':')).encode())

def prepared_replacement(root,folder,book,name,digest):
    """Recognize a checked pending pair without treating it as released bytes."""
    from finalize_prepared import plan
    try:
        # The existing handoff validator binds both files to the current queue,
        # source inputs, settings and immutable preparation snapshot. A local
        # index or preparation flag alone must never bypass a changed-file error.
        handoff=plan(root,folder)
        return (handoff['language'],handoff['collection'])==(book['language'],book['collection']) and handoff['preparation'].get(name)==digest
    except (ValueError,OSError,KeyError,TypeError):return False

def source_file(root,out,book,extension):
    name=Path(book['file']).with_suffix('.'+extension).name;hashkey='sha256'if extension=='docx'else'pdfSha256';digest=book[hashkey]
    if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Invalid source book digest')
    path=out/(book['language']+'-'+book['collection'])/name
    if path.is_file():
        local_digest=sha(path.read_bytes())
        if local_digest==digest:return path
        if not prepared_replacement(root,path.parent,book,name,local_digest):raise ValueError('Local checked book changed')
        # A pending A4 replacement can share this filename with the retained
        # verified edition. Preserve the candidate and fetch the released hash
        # into its separate cache below; never publish or overwrite the candidate.
    cache=root/'books/.cache/download-pairs'/digest/name
    if cache.is_file()and sha(cache.read_bytes())==digest:return cache
    url=book['download'if extension=='docx'else'pdfDownload']
    prefix='https://github.com/'+REPO+'/releases/download/'
    if not url.startswith(prefix)or url.rsplit('/',1)[-1]!=name:raise ValueError('Unexpected source release URL')
    cache.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.download-',dir=cache.parent)as temporary:
        downloaded=Path(temporary)/name
        download_archive(url,downloaded)
        # Keep the public-book size/hash gate independent of the transport.
        # Do not read oversized files into memory or install partial downloads.
        if downloaded.stat().st_size>250_000_000 or sha(downloaded.read_bytes())!=digest:raise ValueError('Downloaded book differs from its published hash')
        os.replace(downloaded,cache)
    return cache

def combined_files(root,out,language,books):
    folder=out/'public-bundles'/language;folder.mkdir(parents=True,exist_ok=True)
    sources=[(source_file(root,out,b,'docx'),source_file(root,out,b,'pdf'))for b in books]
    zip_path=folder/f'Iman_Companion_{language}_all-books.zip'
    expected={}
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6)as archive:
        for pair in sources:
            for source in pair:
                if source.name in expected:raise ValueError('Duplicate bundle file')
                raw=source.read_bytes();expected[source.name]=sha(raw)
                info=zipfile.ZipInfo(source.name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,raw)
    with zipfile.ZipFile(zip_path)as archive:
        if archive.testzip()or{n:sha(archive.read(n))for n in archive.namelist()}!=expected:raise ValueError('ZIP book inventory changed')
    assets=[zip_path];checks={'zipFiles':expected}
    if len(books)>1:
        word=folder/f'Iman_Companion_{language}_all-books.docx';pdf=word.with_suffix('.pdf')
        checks['word']=merge_docx([p[0]for p in sources],word)
        from font_integrity import verify
        verify(word,read(root/'books/config.json'),language)
        checks['pdf']=merge_pdf([p[1]for p in sources],pdf,[b['collectionLabel']for b in books]);assets.extend([word,pdf])
    else:checks['mergedEditionAliasesSingleBook']=True
    (folder/'verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return assets,checks

def verified_bundle(entry,books,repo,fetch):
    if entry.get('parts')!=[{k:b[k]for k in('language','collection','sha256','pdfSha256')}for b in books]:raise ValueError('Combined inventory is not the current complete language library')
    release=fetch(entry['releaseTag'])
    if release.get('tag_name')!=entry['releaseTag']or release.get('draft')is not False or release.get('prerelease')is not False:raise ValueError('Bundle release is not public')
    for asset in entry['assets']:
        expected=release_url(repo,entry['releaseTag'],asset['name']);rows=[a for a in release.get('assets',[])if a.get('name')==asset['name']]
        if len(rows)!=1:raise ValueError('Missing bundle release asset')
        actual=rows[0]
        if actual.get('state')!='uploaded'or actual.get('size')!=asset['bytes']or actual.get('digest')!='sha256:'+asset['sha256']or actual.get('browser_download_url')!=expected:raise ValueError('Bundle release asset hash/size changed')
    language=books[0]['language'];base=f'Iman_Companion_{language}_all-books.'
    names={a['name']for a in entry['assets']}
    expected={base+'zip'}|({base+'pdf',base+'docx'}if len(books)>1 else set())
    if names!=expected:raise ValueError('Unexpected files in combined edition')
    return {'zip':release_url(repo,entry['releaseTag'],base+'zip'),
      'docx':release_url(repo,entry['releaseTag'],base+'docx')if len(books)>1 else books[0]['download'],
      'pdf':release_url(repo,entry['releaseTag'],base+'pdf')if len(books)>1 else books[0]['pdfDownload'],'parts':len(books)}

def publish_bundles(root,out,ready,commit,repo,tag,execute):
    if repo!=REPO:raise ValueError('Unexpected download repository')
    path=root/'books/published-bundles.json';previous=read(path)if path.exists()else{'schema':SCHEMA,'languages':{}}
    if previous.get('schema')!=SCHEMA:raise ValueError('Invalid existing bundles manifest')
    selected={};pending={};assets=[];errors=[];release_cache={}
    def fetch(t):
        if t not in release_cache:release_cache[t]=json.loads(execute(['gh','api',f'repos/{repo}/releases/tags/{t}'],root))
        return release_cache[t]
    def fetch_draft(t):
        # GitHub does not expose a draft through the releases/tags endpoint.
        # List releases under the authenticated token and match the exact tag.
        for page in range(1,101):
            rows=json.loads(execute(['gh','api',f'repos/{repo}/releases?per_page=100&page={page}'],root))
            matches=[r for r in rows if r.get('tag_name')==t and r.get('draft') is True]
            if len(matches)>1:raise ValueError('Duplicate draft bundle release')
            if matches:return matches[0]
            if len(rows)<100:break
        raise ValueError('Uploaded draft bundle release is missing')
    bundle_tag=tag+'-bundles'
    for language in COPY:
        books=inventory(ready,language)
        if not books:continue
        try:
            digest=fingerprint(root,books);old=previous['languages'].get(language)
            if old and old.get('fingerprint')==digest:
                verified_bundle(old,books,repo,fetch);selected[language]=old;continue
            files,checks=combined_files(root,out,language,books)
            pending[language]={'fingerprint':digest,'releaseTag':bundle_tag,'parts':[{k:b[k]for k in('language','collection','sha256','pdfSha256')}for b in books],
              'assets':[], 'verification':checks}
            pending[language]['assets']=[{'name':f.name,'bytes':f.stat().st_size,'sha256':sha(f.read_bytes())}for f in files];assets.extend(files)
        except Exception as error:errors.append({'language':language,'error':str(error)})
    if assets:
        try:
            execute(['gh','release','create',bundle_tag,'--repo',repo,'--target',commit,'--draft','--latest=false','--title','Combined language book downloads','--notes','The merged edition and ZIP include only the complete current published books in the selected language.'],root)
            for file in assets:execute(['gh','release','upload',bundle_tag,file,'--repo',repo],root)
            release=fetch_draft(bundle_tag)
            if release.get('draft')is not True:raise ValueError('Bundle draft was unexpectedly public')
            remote={a['name']:a for a in release.get('assets',[])}
            for file in assets:
                actual=remote.get(file.name,{})
                if actual.get('state')!='uploaded'or actual.get('size')!=file.stat().st_size or actual.get('digest')!='sha256:'+sha(file.read_bytes()):raise ValueError('Uploaded bundle differs from its checked bytes')
            from automatic_publication import ensure_main
            ensure_main(root,commit)  # A source update during upload keeps this draft private.
            execute(['gh','release','edit',bundle_tag,'--repo',repo,'--draft=false','--latest=false'],root)
            release_cache.pop(bundle_tag,None)
            for language,entry in pending.items():verified_bundle(entry,inventory(ready,language),repo,fetch);selected[language]=entry
        except Exception as error:errors.extend({'language':lang,'error':str(error)}for lang in pending)
    # Keep the published inventory in locale order even when a transaction
    # mixes reused releases with newly created bundles.
    selected={language:selected[language] for language in COPY if language in selected}
    links={}
    for language,entry in selected.items():links[language]=verified_bundle(entry,inventory(ready,language),repo,fetch)
    path.write_text(json.dumps({'schema':SCHEMA,'languages':selected},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return links,errors

def public_asset(root,raw,relative):
    path=root/'docs/books/assets'/relative
    if not path.is_file()or path.read_bytes()!=raw:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return 'assets/'+relative

def font_assets(root,conf,language):
    spec=conf['fonts'][conf['languages'][language]['font']];result={}
    for weight,key in[('Regular','regular'),('Bold','bold')]:
        raw=inside(root,spec['files'][weight]).read_bytes();digest=sha(raw)
        if digest!=spec['sha256'][weight]:raise ValueError('UI font differs from the pinned book font')
        result[key]=public_asset(root,raw,'fonts/'+digest+'.ttf')
    return result

def cover_asset(root,pdf,digest):
    relative='covers/'+digest+'.webp';target=root/'docs/books/assets'/relative
    if not target.is_file():
        import pypdfium2 as pdfium
        document=pdfium.PdfDocument(pdf)
        try:
            page=document[0]
            try:
                bitmap=page.render(scale=432/page.get_width())
                try:
                    image=bitmap.to_pil();target.parent.mkdir(parents=True,exist_ok=True);image.save(target,'WEBP',quality=88,method=6)
                finally:bitmap.close()
            finally:page.close()
        finally:document.close()
    return 'assets/'+relative

def write_catalog(root,out,ready,bundles):
    conf=read(root/'books/config.json');languages={}
    from book_content_coverage import download_coverage
    coverage=download_coverage(root,ready,conf=conf)
    for language,labels in COPY.items():
        lc=conf['languages'][language]
        row={'language':language,'name':locale(language)['nativeName'],'brand':lc['brand'],'title':labels[0],
          'included':labels[4],'downloads':download_labels(language),
          'digits':NATIVE_DIGITS.get(language,'0123456789'),'font':font_assets(root,conf,language),'books':[],'bundle':bundles.get(language)}
        for book in inventory(ready,language):
            pdf=source_file(root,out,book,'pdf')
            title=book['collectionLabel'] if book.get('editionScope') else lc['titles'][book['collection']]
            content_scope=coverage[(language,book['collection'])]
            unit_labels=content_scope['presentation']['unitLabels']
            row['books'].append({'language':language,'collection':book['collection'],'title':title,
              'cover':cover_asset(root,pdf,book['pdfSha256']),'docx':book['download'],'pdf':book['pdfDownload'],
              'sha256':book['sha256'],'pdfSha256':book['pdfSha256'],'units':len(book['units']),'pages':book.get('pages'),
              'audio':len(book.get('audioPanels',[])),'coverage':content_scope,
              'contents':[{'id':u['id'],'title':u['title'],**({'numberLabel':unit_labels[str(u['id'])]} if str(u['id']) in unit_labels else {})}for u in book['units']]})
            if book.get('availability'):
                from preparation_copy import LIMITED
                row['books'][-1].update({'availability':book['availability'],'statusLabel':LIMITED[language]})
        decorate_catalog_row(row, inventory(ready,language))
        languages[language]=row
    catalog={'schema':'iman-book-downloads-v1','languages':languages};path=root/'docs/books/catalog.json'
    previous=read(path)if path.exists()else{}
    if {k:v for k,v in previous.items()if k!='updated'}==catalog:catalog['updated']=previous['updated']
    else:catalog['updated']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # Regenerate all native tables from the same verified book and bundle inventory.
    from download_tables import render_ready,merge_readme
    table,pages=render_ready(conf,ready,REPO,bundles=bundles,coverage=coverage)
    readme=root/'README.md'
    if readme.exists():readme.write_text(merge_readme(readme.read_text(encoding='utf8'),table),encoding='utf8')
    for language,body in pages.items():
        page=root/'books/downloads'/language/'README.md';page.parent.mkdir(parents=True,exist_ok=True);page.write_text(body,encoding='utf8')
    for language in languages:
        page=root/'books/downloads'/language/'README.md'
        if not page.exists():continue
        original=page.read_text(encoding='utf8');marker='<!-- IMAN-DOWNLOAD-INTERFACE -->'
        link=f'[{COPY[language][0]}](https://blaghtayt-alt.github.io/iman-companion/books/?lang={language})'
        if marker not in original:
            heading,rest=original.split('\n',1);page.write_text(heading+'\n\n'+marker+'\n'+link+'\n'+rest,encoding='utf8')
    return catalog

def publish(root,out,ready,commit,repo,tag,execute):
    links,errors=publish_bundles(root,out,ready,commit,repo,tag,execute)
    catalog=write_catalog(root,out,ready,links)
    return {'languages':len(catalog['languages']),'bookPairs':sum(len(r['books'])for r in catalog['languages'].values()),'combinedLanguages':len(links),'failedBundles':errors}

def managed_paths(root):
    return ['books/published-bundles.json']+[p.relative_to(root).as_posix()for p in sorted((root/'docs/books').rglob('*'))if p.is_file()]
