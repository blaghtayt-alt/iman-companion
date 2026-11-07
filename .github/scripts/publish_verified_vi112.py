"""Publish one independently verified Vietnamese book pair without replacing unrelated scopes."""
from pathlib import Path
import argparse,copy,json,os,shutil,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'books'))
from published_library import read,sha,current,scope_key,asset_names,merge,stage
from automatic_publication import ensure_main,managed_paths,run
from download_page import publish_bundles,write_catalog
from download_tables import release_url

REPO='blaghtayt-alt/iman-companion'
SOURCE='7d49e51763b9665c8d98aaa46eac6946caf9979f'
DOC='Iman_Companion_vi_tadabbur-extended.docx'
PDF='Iman_Companion_vi_tadabbur-extended.pdf'
HASHES={DOC:'92486ba98a6ae1099143cde94da88a474a28fe674a5b2af77d9a8338e82481e6',PDF:'bfa6d15ac1e3b1bc31c36e04535d15a5323b0238b8f7190f58f4bce83224ce25'}

def check(root,candidate):
    for name,digest in HASHES.items():
        p=candidate/name
        if not p.is_file() or sha(p.read_bytes())!=digest:raise ValueError('Verified book file differs: '+name)
    proof=read(candidate/'CURRENT-SOURCE-REPLACEMENT-VERIFICATION.json')
    if proof['sourceCommit']!=SOURCE or proof['docxSHA256']!=HASHES[DOC] or proof['pdfSHA256']!=HASHES[PDF] or proof['wordPages']!=22 or proof['pdfPages']!=21 or proof['originalOrnateCharactersPreserved']!=98 or not proof['sourceReaderChunksAndFootnotesExactlyPreserved']:raise ValueError('Candidate source or visual evidence differs')
    if not all(proof[k] is True for k in ['all43ActualWordAndPdfPagesRendered','all43PageTextBoundsAndMissingTextChecksPassed','all43ActualPagesVisuallyInspected']):raise ValueError('Actual page visual checks are incomplete')
    from word_layout_check import verify_pair
    checked=verify_pair(candidate/DOC,candidate/PDF,'vi')
    if checked!=proof['independentContentsVerification'] or checked['word']['pages']!=22 or checked['word']['matchedEntries']!=5 or checked['pdf']['matchedEntries']!=5 or checked['pdf']['visibleLabelsMatched']!=5:raise ValueError('Independent Word and PDF contents checks did not pass')
    index=read(candidate/'index.json');snap=read(candidate/'library-snapshot.json');entries=snap['entries']
    if snap['schema']!='iman-published-book-library-v1' or index['sourceCommit']!=SOURCE or len(entries)!=1 or len(index['books'])!=1:raise ValueError('Candidate index does not identify the reviewed source')
    entry=entries[0];book=entry['book']
    if index.get('previewOnly') is not False or index['books'][0]!=book or len(book.get('units',[]))!=1 or book['units'][0].get('id')!='112:extended':raise ValueError('Candidate index and reviewed unit differ')
    if scope_key(book)!=('vi','tadabbur-extended') or book['sourceCommit']!=SOURCE or book['sha256']!=HASHES[DOC] or book['pdfSha256']!=HASHES[PDF] or book['units'][0]['readerTextSHA256']!='8868a81f0c3c0cc89a6cedc3761aae627372d242b22cbdbf6cf24c3622c77774' or not current(root,entry):raise ValueError('The reviewed source, scope, or reader changed')
    existing=read(root/'books/published-library.json')
    keys=[scope_key(e['book']) for e in existing['entries']]
    if set(keys)!={('fil','tadabbur-extended'),('ru','tadabbur-extended'),('vi','tadabbur-extended')} or any(not current(root,e) for e in existing['entries']):raise ValueError('Current downloads changed; stop instead of removing or replacing them')
    return entry,existing

def find_draft(root,tag):
    for page in range(1,101):
        rows=json.loads(run(['gh','api',f'repos/{REPO}/releases?per_page=100&page={page}'],root))
        found=[r for r in rows if r.get('tag_name')==tag and r.get('draft') is True]
        if len(found)>1:raise ValueError('Duplicate candidate release')
        if found:return found[0]
        if len(rows)<100:break
    raise ValueError('Uploaded release draft not found')

def publish(root,candidate,out,commit,tag):
    entry,existing=check(root,candidate);ensure_main(root,commit)
    if run(['git','diff','--cached','--name-only'],root).strip():raise ValueError('Unexpected staged changes')
    folder=out/'vi-tadabbur-extended';folder.mkdir(parents=True,exist_ok=False)
    for name in HASHES:shutil.copyfile(candidate/name,folder/name)
    run(['gh','release','create',tag,'--repo',REPO,'--target',commit,'--draft','--latest=false','--title','Verified Vietnamese Quran reflection book','--notes','The checked Vietnamese Word and PDF pair. Existing book releases remain available.'],root)
    for name in HASHES:run(['gh','release','upload',tag,folder/name,'--repo',REPO],root)
    draft=find_draft(root,tag);assets=draft.get('assets',[]);remote={a['name']:a for a in assets}
    if len(assets)!=2 or set(remote)!=set(HASHES):raise ValueError('Unexpected draft release assets')
    for name,digest in HASHES.items():
        row=remote.get(name,{})
        if row.get('state')!='uploaded' or row.get('size')!=(folder/name).stat().st_size or row.get('digest')!='sha256:'+digest:raise ValueError('Uploaded candidate differs from the independently checked file')
    ensure_main(root,commit)
    run(['gh','release','edit',tag,'--repo',REPO,'--draft=false','--latest=false'],root)
    fetch=lambda t:json.loads(run(['gh','api',f'repos/{REPO}/releases/tags/{t}'],root))
    entry=copy.deepcopy(entry);entry['releaseTag']=tag;entry['book']['download']=release_url(REPO,tag,DOC);entry['book']['pdfDownload']=release_url(REPO,tag,PDF)
    library,ready,stale=merge(root,existing,[entry],REPO,fetch)
    if stale or set(ready)!={('fil','tadabbur-extended'),('ru','tadabbur-extended'),('vi','tadabbur-extended')}:raise ValueError('Unexpected stale or removed scope')
    before={scope_key(e['book']):e for e in existing['entries']};after={scope_key(e['book']):e for e in library['entries']}
    if any(after[(l,'tadabbur-extended')]!=before[(l,'tadabbur-extended')] for l in ['fil','ru']):raise ValueError('Unrelated book entry changed')
    prior=read(root/'books/published-bundles.json');links,errors=publish_bundles(root,out,ready,commit,REPO,tag,run)
    if errors or set(links)!={'fil','ru','vi'}:raise ValueError('Bundle publication failed; existing public tables remain unchanged: '+str(errors))
    nextbundles=read(root/'books/published-bundles.json')
    if any(nextbundles['languages'][l]!=prior['languages'][l] for l in ['fil','ru']):raise ValueError('Unrelated bundle changed')
    stage(root,library,ready,REPO);catalog=write_catalog(root,out,ready,links)
    if catalog['languages']['vi']['books'][0]['sha256']!=HASHES[DOC] or catalog['languages']['vi']['books'][0]['pdfSha256']!=HASHES[PDF]:raise ValueError('New table does not identify verified pair')
    ensure_main(root,commit)
    files=[p for p in managed_paths(root) if (root/p).is_file()];run(['git','add','--',*files],root)
    changed=run(['git','diff','--cached','--name-only'],root).splitlines()
    if not changed or not set(changed).issubset(set(files)):raise ValueError('Unexpected publication changes')
    run(['git','config','user.name','github-actions[bot]'],root);run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],root)
    run(['git','commit','-m','Publish verified Vietnamese Quran reflection book'],root);run(['git','push','origin','HEAD:refs/heads/main'],root)
    print(json.dumps({'published':True,'bookTag':tag,'pairs':len(ready),'newPair':'vi','oldScopesPreserved':['fil','ru'],'bundles':len(links),'staleRemoved':stale,'files':changed}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--publish',action='store_true');p.add_argument('--commit');p.add_argument('--tag');a=p.parse_args();root=Path.cwd().resolve();candidate=a.candidate.resolve()
    check(root,candidate)
    if a.publish:
        if not a.commit or not a.tag:raise ValueError('Missing immutable release identity')
        publish(root,candidate,a.out.resolve(),a.commit,a.tag)
    else:print(json.dumps({'verified':True,'sourceCommit':SOURCE,'candidateFiles':HASHES}))
