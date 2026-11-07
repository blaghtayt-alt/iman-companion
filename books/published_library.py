"""Keep current, remotely verified book pairs across independent scoped builds.

The owner uploads a checked production candidate before applying its new links.
This module never upgrades a review-only build or creates a source approval.
"""
from pathlib import Path
import argparse,copy,hashlib,json,re,subprocess
from download_tables import COLLECTIONS,COPY,render_ready,merge_readme,release_url

SCHEMA='iman-published-book-library-v1'
HEX=re.compile(r'^[a-f0-9]{64}$')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
def inside(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or path==root.resolve():raise ValueError('Library input escapes repository')
    return path
def scope_key(book):
    key=(book.get('language'),book.get('collection'))
    if key[0] not in COPY or key[1] not in COLLECTIONS:raise ValueError('Non-public book scope in library')
    return key
def scope_catalog(root,key):
    scoped_declaration=declaration(root,key)
    if scoped_declaration.get('scopePolicy') is not None:
        from book_edition_scope import select,scope_fingerprint
        rows,report=select(root,read(root/'materials/catalog.json'),scoped_declaration)
        return scope_fingerprint(rows,report)
    collections={'tadabbur-extended':'tadabbur','hadith':'essential-hadith','seerah':'seerah','articles':'articles'}
    edition=scoped_declaration.get('edition')
    retired={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
    def current(e):
        return (e.get('language')==key[0] and e.get('collection')==collections[key[1]]
            and (not edition or e.get('edition')==edition)
            and (key[1]!='tadabbur-extended' or e.get('mode')=='extended')
            and not e.get('archived') and e.get('current',True) is not False
            and not any(str(e.get(k,'')).lower() in retired for k in ['status','publicationStatus','translationStatus'])
            and not any('/source-archive/' in str(e.get(k,'')) for k in ['json','markdown']))
    rows=[e for e in read(root/'materials/catalog.json')['entries'] if current(e)]
    return sha(json.dumps(sorted(rows,key=lambda e:str(e['id'])),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
def declaration(root,key):
    data=read(root/'books/reviewed-books.json')
    if data.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid book declarations')
    rows=[e for e in data['books'] if (e.get('language'),e.get('collection'))==key]
    if len(rows)!=1 or rows[0].get('state')!='reviewed-current' or rows[0].get('automaticBuild') is not True or rows[0].get('automaticRelease') is not True:raise ValueError('Scope is not enabled for reviewed automatic publication')
    return rows[0]
def scope_settings(root,key,unit_ids):
    """Bind the settings and audio relevant to this book, not other scopes."""
    conf=read(root/'books/config.json');scoped=copy.deepcopy(conf);languages=scoped.get('languages',{});language=languages.get(key[0])
    if language is None:raise ValueError('Missing book language settings')
    scoped['languages']={key[0]:language}
    fonts=scoped.get('fonts',{});needed={n for n in (language.get('font'),'Arabic','Latin') if isinstance(n,str)}
    if fonts:scoped['fonts']={name:fonts[name] for name in sorted(needed) if name in fonts}
    setting=scoped.pop('audioRegistry',None);audio=[]
    if setting:
        raw=inside(root,setting['path']).read_bytes()
        if sha(raw)!=setting.get('sha256'):raise ValueError('Audio registry binding is stale')
        registry=json.loads(raw)
        if registry.get('schema')!='iman-material-audio-v1':raise ValueError('Invalid audio registry')
        audio=[row for row in registry.get('entries',[]) if row.get('language')==key[0] and row.get('collection')==key[1] and row.get('materialId') in unit_ids]
        audio.sort(key=lambda r:(r.get('materialId',''),r.get('sourceSHA256',''),r.get('audioSHA256','')))
    return sha(json.dumps({'config':scoped,'audio':audio},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8'))
def capture(root,index):
    """Run immediately after final checks in each scoped build, before artifact upload."""
    if index.get('previewOnly') is not False or not re.fullmatch('[a-f0-9]{40}',index.get('sourceCommit','')):raise ValueError('Only production candidates have library snapshots')
    manifest=read(root/'books/manifest.json')
    if manifest.get('sourceCommit')!=index['sourceCommit'] or manifest.get('previewOnly') is not False:raise ValueError('Candidate does not match its production source manifest')
    result=[]
    for book in index['books']:
        key=scope_key(book);declaration(root,key)
        if book.get('exportVerified') is not True or book.get('previewOnly') is not False:raise ValueError('Candidate has not passed final export checks')
        bindings={}
        units=[]
        for row in manifest['units']:
            if (row.get('language'),row.get('collection'))!=key:continue
            unit=read(inside(root,row['path']))
            if sha(inside(root,row['path']).read_bytes())!=row['sha256']:raise ValueError('Normalized unit changed after indexing')
            units.append((unit['id'],unit['readerTextSHA256'],unit['sourceHashes']))
            for binding in unit['inputBindings']:
                if sha(inside(root,binding['path']).read_bytes())!=binding['sha256']:raise ValueError('Current unit input changed')
                if binding['path'] in bindings and bindings[binding['path']]!=binding['sha256']:raise ValueError('Conflicting unit input hashes')
                bindings[binding['path']]=binding['sha256']
        if not units or sorted(units)!=sorted((u['id'],u['readerTextSHA256'],u['sourceHashes']) for u in book['units']):raise ValueError('Library snapshot omits or changes a checked unit')
        unit_ids=sorted(u[0] for u in units)
        snapshot={'catalogSHA256':scope_catalog(root,key),'scopeSettingsSHA256':scope_settings(root,key,unit_ids),'unitIds':unit_ids,'bindings':[{'path':p,'sha256':h} for p,h in sorted(bindings.items())]}
        result.append({'book':book,'snapshot':snapshot})
    if len({scope_key(e['book']) for e in result})!=len(result):raise ValueError('Duplicate scoped candidate')
    return {'schema':SCHEMA,'entries':result}
def current(root,entry):
    try:
        key=scope_key(entry['book']);declaration(root,key);snapshot=entry['snapshot']
        return snapshot['catalogSHA256']==scope_catalog(root,key) and bool(snapshot['bindings']) and bool(snapshot['unitIds']) and snapshot['scopeSettingsSHA256']==scope_settings(root,key,snapshot['unitIds']) and all(HEX.fullmatch(b['sha256']) and sha(inside(root,b['path']).read_bytes())==b['sha256'] for b in snapshot['bindings'])
    except (ValueError,OSError,KeyError):return False
def asset_names(book):
    key=scope_key(book);expected=f'Iman_Companion_{key[0]}_{key[1]}.docx'
    if book.get('file')!=expected:raise ValueError('Unexpected public book asset name')
    if key[1]=='hadith' and book.get('hadithEdition')!='new-extended':raise ValueError('Legacy short Hadith cannot enter current library')
    return [(expected,'sha256'),(Path(expected).with_suffix('.pdf').name,'pdfSha256')]
def verify_pair(entry,repo,release):
    book=entry['book'];tag=entry['releaseTag'];scope_key(book)
    if book.get('exportVerified') is not True or book.get('previewOnly') is not False:raise ValueError('Review-only pair cannot be published')
    if release.get('tag_name')!=tag or release.get('draft') is not False or release.get('prerelease') is not False:raise ValueError('Book release is not publicly published')
    assets=release.get('assets',[])
    for name,hashkey in asset_names(book):
        rows=[a for a in assets if a.get('name')==name]
        if len(rows)!=1 or not HEX.fullmatch(book.get(hashkey,'')):raise ValueError('Book pair is missing an exact asset hash')
        asset=rows[0]
        if asset.get('state')!='uploaded' or asset.get('size',0)<=0 or asset.get('digest')!='sha256:'+book[hashkey] or asset.get('browser_download_url')!=release_url(repo,tag,name):raise ValueError('Published release asset differs from the checked book')
    return {**book,'download':release_url(repo,tag,book['file']),'pdfDownload':release_url(repo,tag,Path(book['file']).with_suffix('.pdf').name)}
def merge(root,existing,candidates,repo,release_fetch):
    if existing.get('schema')!=SCHEMA:raise ValueError('Invalid existing public library')
    selected={};stale=[];seen=set();incoming=set()
    for entry in existing['entries']:
        key=scope_key(entry['book'])
        if key in seen:raise ValueError('Duplicate existing library scope')
        seen.add(key)
        if current(root,entry):selected[key]=entry
        else:stale.append(key)
    for entry in candidates:
        key=scope_key(entry['book'])
        if key in incoming:raise ValueError('Duplicate incoming library scope')
        incoming.add(key)
        if not current(root,entry):raise ValueError('New book snapshot is stale; rebuild before publishing links')
        selected[key]=entry
    releases={};ready={}
    for key,entry in sorted(selected.items()):
        tag=entry['releaseTag']
        if not re.fullmatch('[A-Za-z0-9._-]{1,120}',tag):raise ValueError('Invalid book release tag')
        if tag not in releases:releases[tag]=release_fetch(tag)
        ready[key]=verify_pair(entry,repo,releases[tag])
    return {'schema':SCHEMA,'entries':[selected[k] for k in sorted(selected)]},ready,stale
def stage(root,library,ready,repo):
    table,pages=render_ready(read(root/'books/config.json'),ready,repo)
    target=root/'books/published-library.json';target.write_text(json.dumps(library,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    readme=root/'README.md';readme.write_text(merge_readme(readme.read_text(encoding='utf8'),table),encoding='utf8')
    for lang,body in pages.items():
        path=root/'books/downloads'/lang/'README.md';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body,encoding='utf8')
    return len(ready)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);sub=ap.add_subparsers(dest='action',required=True)
    cap=sub.add_parser('capture');cap.add_argument('--folder',type=Path,required=True)
    pub=sub.add_parser('publish-links');pub.add_argument('--candidate',type=Path,action='append',default=[]);pub.add_argument('--repo',required=True);pub.add_argument('--tag',required=True)
    args=ap.parse_args();root=args.root.resolve()
    if args.action=='capture':
        data=capture(root,read(args.folder/'index.json'));(args.folder/'library-snapshot.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return
    if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',args.repo):raise ValueError('Invalid repository')
    entries=[];seen=set()
    for folder in args.candidate:
        data=read(folder/'library-snapshot.json')
        if data.get('schema')!=SCHEMA:raise ValueError('Invalid candidate library schema')
        for entry in data['entries']:
            book=entry['book'];key=scope_key(book)
            if key in seen:raise ValueError('Duplicate incoming library scope')
            seen.add(key)
            for name,hashkey in asset_names(book):
                file=inside(folder,name)
                if sha(file.read_bytes())!=book.get(hashkey):raise ValueError('Local pair changed after export checks')
            entries.append({**entry,'releaseTag':args.tag})
    file=root/'books/published-library.json';existing=read(file) if file.exists() else {'schema':SCHEMA,'entries':[]}
    def fetch(tag):
        proc=subprocess.run(['gh','api',f'repos/{args.repo}/releases/tags/{tag}'],check=True,capture_output=True,text=True)
        return json.loads(proc.stdout)
    library,ready,stale=merge(root,existing,entries,args.repo,fetch)
    print(json.dumps({'verifiedBookPairs':stage(root,library,ready,args.repo),'staleScopesRemoved':stale,'nativePages':20}))
if __name__=='__main__':main()
