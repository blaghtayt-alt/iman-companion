"""Publish the five checked current-source pairs in one guarded transaction."""
from pathlib import Path
import argparse,copy,json,shutil,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'books'))
from published_library import read,sha,capture,current,scope_key,merge,stage
from automatic_publication import ensure_main,managed_paths,run
from download_page import publish_bundles,write_catalog
from download_tables import release_url
from word_layout_check import verify_pair
from font_integrity import verify as verify_fonts

REPO='blaghtayt-alt/iman-companion'
SOURCE='9cceec8be6a3b6c7957e6d0c189c9bb514498483'
RECEIPT='40b632485cfd5554578cd5e446c5e17b42d5a4d85284c97ba0236c8399eaf3e5'
LANGUAGES={'ar','fa','bn','hi','th'}
PRIOR={'ru','vi','fil','en','id','ms','tr','fr','pt-BR','es','de','zh-CN','uz','ja'}

def checked_file(path,digest):
    if not path.is_file() or sha(path.read_bytes())!=digest:raise ValueError('Checked candidate bytes changed: '+str(path))

def check(root,candidate):
    receipt=candidate/'batch-receipt.json';checked_file(receipt,RECEIPT);data=read(receipt)
    if data.get('schema')!='iman-verified-five-book-batch-v1' or data.get('sourceCommit')!=SOURCE:raise ValueError('Wrong checked batch')
    rows=data['entries']
    if len(rows)!=len(LANGUAGES) or {r['language'] for r in rows}!=LANGUAGES:raise ValueError('Missing or unexpected candidate language')
    declarations=root/'books/reviewed-books.json';decs=read(declarations)
    for lang in LANGUAGES:
        found=[r for r in decs['books'] if (r.get('language'),r.get('collection'))==(lang,'tadabbur-extended')]
        if len(found)!=1 or found[0].get('automaticRelease') is not False or found[0].get('scopePolicy')!='reviewed-source-edition-v1':raise ValueError('Edition declaration changed: '+lang)
        found[0]['automaticRelease']=True;found[0]['requireActualWordLayout']=True;found[0].pop('releaseHold',None)
    declarations.write_text(json.dumps(decs,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    entries=[];conf=read(root/'books/config.json')
    for row in rows:
        lang=row['language'];folder=candidate/lang;name=f'Iman_Companion_{lang}_tadabbur-extended';doc=folder/(name+'.docx');pdf=folder/(name+'.pdf')
        for path,key in [(doc,'docxSHA256'),(pdf,'pdfSHA256'),(folder/(name+'.docx.word-layout.json'),'wordReadbackSHA256'),(folder/'word-proof.pdf','wordProofSHA256'),(folder/'source-unit.json','sourceUnitSHA256'),(folder/'source-manifest.json','sourceManifestSHA256'),(folder/'index.json','indexSHA256')]:checked_file(path,row[key])
        if row['allActualPagesInspected'] is not True or row['allSourceAndFormatChecksPassed'] is not True:raise ValueError('Incomplete review: '+lang)
        result=verify_pair(doc,pdf,lang)
        if result['word']['pages']!=row['wordPages'] or result['word']['matchedEntries']!=5 or result['pdf']['matchedEntries']!=5 or result['pdf']['visibleLabelsMatched']!=5:raise ValueError('Independent contents verification failed: '+lang)
        from pypdf import PdfReader
        if len(PdfReader(folder/'word-proof.pdf').pages)!=row['wordPages']:raise ValueError('Word proof page count changed: '+lang)
        verify_fonts(doc,conf,lang)
        manifest=read(folder/'source-manifest.json');units=manifest['units']
        if manifest.get('sourceCommit')!=SOURCE or len(units)!=1 or (units[0]['language'],units[0]['collection'],units[0]['id'])!=(lang,'tadabbur-extended','112:extended') or units[0]['sha256']!=row['sourceUnitSHA256']:raise ValueError('Unexpected source manifest: '+lang)
        path=(root/units[0]['path']).resolve()
        if not path.is_relative_to((root/'books/units/generated').resolve()):raise ValueError('Unsafe source unit path')
        path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(folder/'source-unit.json',path);shutil.copyfile(folder/'source-manifest.json',root/'books/manifest.json')
        index=read(folder/'index.json');snap=capture(root,index);saved=read(folder/'library-snapshot.json')
        if snap!=saved or len(snap['entries'])!=1:raise ValueError('Source binding or captured snapshot changed: '+lang)
        entry=snap['entries'][0];book=entry['book']
        if scope_key(book)!=(lang,'tadabbur-extended') or book['sha256']!=row['docxSHA256'] or book['pdfSha256']!=row['pdfSHA256'] or len(book['units'])!=1 or not current(root,entry):raise ValueError('Candidate is no longer current: '+lang)
        entries.append(entry)
    existing=read(root/'books/published-library.json');keys=[scope_key(e['book']) for e in existing['entries']]
    if len(keys)!=len(PRIOR) or set(keys)!={(x,'tadabbur-extended') for x in PRIOR} or any(not current(root,e) for e in existing['entries']):raise ValueError('Existing public books changed; stop')
    return entries,existing

def draft(root,tag):
    for page in range(1,101):
        rows=json.loads(run(['gh','api',f'repos/{REPO}/releases?per_page=100&page={page}'],root))
        found=[r for r in rows if r.get('tag_name')==tag and r.get('draft') is True]
        if len(found)>1:raise ValueError('Duplicate release draft')
        if found:return found[0]
        if len(rows)<100:break
    raise ValueError('Release draft missing')

def publish(root,candidate,out,commit,tag,entries,existing):
    ensure_main(root,commit)
    if run(['git','diff','--cached','--name-only'],root).strip():raise ValueError('Unexpected staged changes')
    assets=[]
    for entry in entries:
        book=entry['book'];lang=book['language'];folder=out/(lang+'-tadabbur-extended');folder.mkdir(parents=True,exist_ok=False)
        for name in [book['file'],Path(book['file']).with_suffix('.pdf').name]:
            target=folder/name;shutil.copyfile(candidate/lang/name,target);assets.append(target)
    run(['gh','release','create',tag,'--repo',REPO,'--target',commit,'--draft','--latest=false','--title','Verified Al-Ikhlas reflection books','--notes','Five checked language editions of the named reflection. Existing releases remain available.'],root)
    for file in assets:run(['gh','release','upload',tag,file,'--repo',REPO],root)
    uploaded=draft(root,tag).get('assets',[]);remote={a['name']:a for a in uploaded}
    if len(uploaded)!=len(assets) or set(remote)!={p.name for p in assets}:raise ValueError('Unexpected uploaded assets')
    for file in assets:
        a=remote[file.name]
        if a.get('state')!='uploaded' or a.get('size')!=file.stat().st_size or a.get('digest')!='sha256:'+sha(file.read_bytes()):raise ValueError('Uploaded bytes changed: '+file.name)
    ensure_main(root,commit);run(['gh','release','edit',tag,'--repo',REPO,'--draft=false','--latest=false'],root)
    incoming=[]
    for source in entries:
        entry=copy.deepcopy(source);book=entry['book'];entry['releaseTag']=tag
        book['download']=release_url(REPO,tag,book['file']);book['pdfDownload']=release_url(REPO,tag,Path(book['file']).with_suffix('.pdf').name);incoming.append(entry)
    fetch=lambda t:json.loads(run(['gh','api',f'repos/{REPO}/releases/tags/{t}'],root))
    library,ready,stale=merge(root,existing,incoming,REPO,fetch);wanted={(l,'tadabbur-extended') for l in LANGUAGES|PRIOR}
    if stale or set(ready)!=wanted:raise ValueError('Unexpected stale or missing books')
    before={scope_key(e['book']):e for e in existing['entries']};after={scope_key(e['book']):e for e in library['entries']}
    if any(after[(l,'tadabbur-extended')]!=before[(l,'tadabbur-extended')] for l in PRIOR):raise ValueError('Existing book was changed')
    oldbundles=read(root/'books/published-bundles.json');links,errors=publish_bundles(root,out,ready,commit,REPO,tag,run)
    if errors or set(links)!=LANGUAGES|PRIOR:raise ValueError('Bundle verification failed: '+str(errors))
    newbundles=read(root/'books/published-bundles.json')
    if any(oldbundles['languages'][l]!=newbundles['languages'][l] for l in PRIOR):raise ValueError('Existing bundle changed')
    stage(root,library,ready,REPO);catalog=write_catalog(root,out,ready,links)
    for entry in entries:
        book=entry['book'];rows=catalog['languages'][book['language']]['books']
        if len(rows)!=1 or rows[0]['sha256']!=book['sha256'] or rows[0]['pdfSha256']!=book['pdfSha256']:raise ValueError('Download catalog differs from verified pair')
    ensure_main(root,commit);files=[p for p in managed_paths(root) if (root/p).is_file()]+['books/reviewed-books.json']
    run(['git','add','--',*files],root);changed=run(['git','diff','--cached','--name-only'],root).splitlines()
    if not changed or not set(changed).issubset(set(files)):raise ValueError('Unexpected publication changes')
    run(['git','config','user.name','github-actions[bot]'],root);run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],root)
    run(['git','commit','-m','Publish five verified Al-Ikhlas reflection editions'],root);run(['git','push','origin','HEAD:refs/heads/main'],root)
    print(json.dumps({'published':True,'tag':tag,'newPairs':len(entries),'preserved':sorted(PRIOR),'totalPairs':len(ready),'bundles':len(links)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--publish',action='store_true');p.add_argument('--commit');p.add_argument('--tag');a=p.parse_args()
    root=Path.cwd().resolve();candidate=a.candidate.resolve();entries,existing=check(root,candidate)
    if a.publish:
        if not a.commit or not a.tag:raise ValueError('Missing release identity')
        publish(root,candidate,a.out.resolve(),a.commit,a.tag,entries,existing)
    else:print(json.dumps({'verified':True,'languages':sorted(LANGUAGES),'sourceCommit':SOURCE}))
