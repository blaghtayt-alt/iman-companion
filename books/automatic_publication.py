"""Build independent current books, then publish verified immutable pairs/tables.

Run by the repository-owned workflow. Source approval remains with the existing
published source units; this controller never creates a translation approval.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys
from published_library import SCHEMA,asset_names,capture,current,merge,read,sha,stage,scope_key
from check_contents_targets import check as check_contents

def run(args,root,**kwargs):
    result=subprocess.run([str(x)for x in args],cwd=root,capture_output=True,text=True,encoding='utf8',**kwargs)
    if result.returncode:raise RuntimeError('Command failed: '+str(args[0])+' '+str(args[1])+'\n'+result.stderr[-3500:]+'\n'+result.stdout[-1000:])
    return result.stdout

def scopes(root):
    declarations=read(root/'books/reviewed-books.json')
    if declarations.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid book source declarations')
    rows=[];seen=set()
    for row in declarations['books']:
        key=scope_key(row)
        if key in seen:raise ValueError('Duplicate book source declaration')
        seen.add(key)
        if row.get('state')=='reviewed-current'and row.get('automaticBuild')is True and row.get('automaticRelease')is True:rows.append(row)
    return rows

def build(root,out,commit,repo,tag,uno_python='/usr/bin/python3'):
    out.mkdir(parents=True,exist_ok=True)
    report={'sourceCommit':commit,'built':[],'unchanged':[],'failed':[]}
    existing=read(root/'books/published-library.json')if(root/'books/published-library.json').exists()else{'schema':SCHEMA,'entries':[]}
    previous={scope_key(row['book']):row for row in existing['entries']}
    for declaration in scopes(root):
        language,collection=key=scope_key(declaration)
        if key in previous and current(root,previous[key]):report['unchanged'].append({'language':language,'collection':collection});continue
        folder=out/(language+'-'+collection);folder.mkdir(exist_ok=True)
        identity={'language':language,'collection':collection}
        try:
            # All source normalization and every lesson's QR are regenerated.
            commands=[
              [sys.executable,'books/index_units.py','--root',root,'--commit',commit,'--language',language,'--collection',collection],
              [sys.executable,'books/build_books.py','--root',root,'--out',folder,'--commit',commit],
              [uno_python,'books/render_uno.py','--folder',folder],
              [sys.executable,'books/native_pagination.py','--root',root,'--folder',folder],
              [uno_python,'books/render_uno.py','--folder',folder,'--keep-contents'],
            ]
            for command in commands:run(command,root)
            # Reconcile cached TOC page labels with actual PDF destinations.
            # Re-render after each correction and refuse non-convergence.
            for attempt in range(4):
                try:
                    run([sys.executable,'books/toc_sync.py','--folder',folder],root)
                    break
                except RuntimeError:
                    run([sys.executable,'books/toc_sync.py','--folder',folder,'--write'],root)
                    run([uno_python,'books/render_uno.py','--folder',folder,'--keep-contents'],root)
            run([sys.executable,'books/toc_sync.py','--folder',folder],root)
            run([sys.executable,'books/restore_book_fonts.py','--root',root,'--folder',folder],root)
            run([sys.executable,'books/check_outputs.py','--root',root,'--folder',folder,'--tag',tag,'--repo',repo],root)
            index=read(folder/'index.json')
            if len(index['books'])!=1 or scope_key(index['books'][0])!=key:raise ValueError('Scoped build emitted a different book')
            book=index['books'][0]
            book['contentsTargetVerification']=check_contents(folder/book['file'],folder/Path(book['file']).with_suffix('.pdf'))
            (folder/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            snapshot=capture(root,index)
            (folder/'library-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            report['built'].append({**identity,'folder':folder.name})
        except Exception as error:
            report['failed'].append({**identity,'error':str(error)})
            (folder/'BUILD-ERROR.txt').write_text(str(error),encoding='utf8')
    (out/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return report

def candidates(root,out,tag):
    report=read(out/'build-report.json');result=[];assets=[];seen=set()
    for row in report['built']:
        folder=(out/row['folder']).resolve()
        if not folder.is_relative_to(out.resolve()):raise ValueError('Candidate escapes build output')
        snapshot=read(folder/'library-snapshot.json')
        if snapshot.get('schema')!=SCHEMA:raise ValueError('Wrong candidate snapshot')
        for entry in snapshot['entries']:
            key=scope_key(entry['book'])
            if key in seen or key!=(row['language'],row['collection']):raise ValueError('Duplicate or incorrect candidate scope')
            seen.add(key)
            if not current(root,entry):raise ValueError('Candidate source or audio changed after the build')
            for name,hashkey in asset_names(entry['book']):
                path=folder/name
                if not path.is_file()or sha(path.read_bytes())!=entry['book'].get(hashkey):raise ValueError('Candidate file changed after final checks')
                assets.append(path)
            result.append({**entry,'releaseTag':tag})
    return result,assets

def ensure_main(root,commit):
    if run(['git','rev-parse','HEAD'],root).strip()!=commit:raise ValueError('Build checkout changed')
    remote=run(['git','ls-remote','origin','refs/heads/main'],root).split()
    if not remote or remote[0]!=commit:raise ValueError('Newer main exists; its queued workflow must publish the latest sources')

def managed_paths(root=None):
    from download_page import managed_paths as download_paths
    from locale_copy import COPY
    return ['README.md','books/published-library.json','books/config.json','materials/audio/registry.json','docs/listen/materials.json']+[f'books/downloads/{language}/README.md'for language in COPY]+(download_paths(root)if root else[])

def publish(root,out,commit,repo,tag,execute=run):
    entries,assets=candidates(root,out,tag)
    ensure_main(root,commit)
    staged=execute(['git','diff','--cached','--name-only'],root).splitlines()
    if staged:raise ValueError('Publication requires a checkout with no previously staged changes')
    if assets:
        # A unique run tag is immutable; never overwrite an earlier book pair.
        execute(['gh','release','create',tag,'--repo',repo,'--target',commit,'--draft','--latest=false','--title','Current multilingual books','--notes','Automatically built from current published materials. Each language page lists the included material count.'],root)
        for asset in assets:execute(['gh','release','upload',tag,asset,'--repo',repo],root)
        execute(['gh','release','edit',tag,'--repo',repo,'--draft=false','--latest=false'],root)
    def fetch(release_tag):return json.loads(execute(['gh','api',f'repos/{repo}/releases/tags/{release_tag}'],root))
    existing=read(root/'books/published-library.json')if(root/'books/published-library.json').exists()else{'schema':SCHEMA,'entries':[]}
    library,ready,stale=merge(root,existing,entries,repo,fetch)
    ensure_main(root,commit)
    count=stage(root,library,ready,repo)
    from download_page import publish as publish_download_page
    downloads=publish_download_page(root,out,ready,commit,repo,tag,execute)
    ensure_main(root,commit)
    files=[p for p in managed_paths(root)if(root/p).is_file()]
    execute(['git','add','--',*files],root)
    changed=execute(['git','diff','--cached','--name-only'],root).splitlines()
    if not set(changed).issubset(set(files)):raise ValueError('Unexpected staged publication file')
    if changed:
        execute(['git','config','user.name','github-actions[bot]'],root)
        execute(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],root)
        execute(['git','commit','-m','Update verified book downloads and material audio players'],root)
        execute(['git','push','origin','HEAD:refs/heads/main'],root)
    result={'verifiedBookPairs':count,'newPairs':len(entries),'staleScopesRemoved':stale,'nativeLanguagePages':20,'tablesCommitted':bool(changed),'failedScopes':read(out/'build-report.json')['failed']}
    result['downloadPage']=downloads
    (out/'publication-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['build','publish']);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--commit',required=True);parser.add_argument('--repo',required=True);parser.add_argument('--tag',required=True);parser.add_argument('--uno-python',default='/usr/bin/python3');args=parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.commit)or not re.fullmatch('[A-Za-z0-9._-]+/[A-Za-z0-9._-]+',args.repo)or not re.fullmatch('[A-Za-z0-9._-]{1,120}',args.tag):raise ValueError('Invalid publication identity')
    root=args.root.resolve();out=args.out.resolve()
    if args.action=='build':result=build(root,out,args.commit,args.repo,args.tag,args.uno_python)
    else:result=publish(root,out,args.commit,args.repo,args.tag)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
