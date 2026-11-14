"""Build independent current books, then publish verified immutable pairs/tables.

Run by the repository-owned workflow. Source approval remains with the existing
published source units; this controller never creates a translation approval.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,signal,subprocess,sys,shutil,tempfile,time
from published_library import SCHEMA,asset_names,capture,current,merge,read,sha,stage,scope_key
from check_contents_targets import check as check_contents

COMMAND_TIMEOUT_SECONDS=600
COMMAND_TERMINATE_GRACE_SECONDS=5
BUILD_TIMEOUT_SECONDS=70*60

class CommandTimeoutError(RuntimeError):
    """A bounded command failed; its partial output is never a candidate."""

def run(args,root,timeout=COMMAND_TIMEOUT_SECONDS,**kwargs):
    """Bound each command and, on Linux, stop only its owned process group."""
    command=[str(x)for x in args];label=' '.join(command[:2]);started=time.monotonic()
    print('[command:start] '+label,file=sys.stderr,flush=True)
    input_data=kwargs.pop('input',None)
    if input_data is not None:
        if 'stdin' in kwargs:raise ValueError('stdin and input arguments may not both be used')
        kwargs['stdin']=subprocess.PIPE
    process=subprocess.Popen(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf8',start_new_session=os.name=='posix',**kwargs)
    def stop(force=False):
        try:
            if os.name=='posix':os.killpg(process.pid,signal.SIGKILL if force else signal.SIGTERM)
            elif force:process.kill()
            else:process.terminate()
        except ProcessLookupError:pass
    try:
        stdout,stderr=process.communicate(input=input_data,timeout=timeout)
    except subprocess.TimeoutExpired:
        stop()
        try:stdout,stderr=process.communicate(timeout=COMMAND_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            stop(force=True);stdout,stderr=process.communicate()
        # A detached-output descendant can outlive the leader without keeping
        # communicate() blocked. Retire any remainder of our group as well.
        stop(force=True)
        print(f'[command:timeout] {label} after {time.monotonic()-started:.2f}s',file=sys.stderr,flush=True)
        raise CommandTimeoutError(f'Command timed out after {timeout:g}s: {label}\n'+stderr[-3500:]+'\n'+stdout[-1000:]) from None
    except BaseException:
        stop(force=True);process.communicate();raise
    print(f'[command:end] {label}: {process.returncode} in {time.monotonic()-started:.2f}s',file=sys.stderr,flush=True)
    if process.returncode:raise RuntimeError('Command failed: '+label+'\n'+stderr[-3500:]+'\n'+stdout[-1000:])
    return stdout

def scopes(root,for_release=False):
    declarations=read(root/'books/reviewed-books.json')
    if declarations.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid book source declarations')
    rows=[];seen=set()
    for row in declarations['books']:
        key=scope_key(row)
        if key in seen:raise ValueError('Duplicate book source declaration')
        seen.add(key)
        if row.get('state')=='reviewed-current'and row.get('automaticBuild')is True and (not for_release or row.get('automaticRelease')is True):rows.append(row)
    return rows

def require_word_layout(declaration,folder,book,language):
    if declaration.get('requireActualWordLayout') is True:
        from word_layout_check import verify_pair
        docx=folder/book['file'];receipt=docx.with_name(docx.name+'.word-layout.json')
        if not receipt.is_file():raise ValueError('Actual Word layout receipt is required for this edition')
        result=verify_pair(docx,folder/Path(book['file']).with_suffix('.pdf'),language)
        if result.get('word') is None:raise ValueError('Actual Word layout receipt was not verified')
        book['independentWordLayoutVerification']=result

def requires_qr_layout_update(book):
    """Queue the larger A4 QR without withdrawing an unchanged verified book."""
    if not book.get('audioPanels'):return False
    from build_books import expected_page_layout
    return book.get('pageLayout')!=expected_page_layout()

def retain_failed_preparation(out,folder,error):
    """Keep diagnostics outside the paths reserved for checked candidate pairs."""
    (folder/'BUILD-ERROR.txt').write_text(str(error),encoding='utf8')
    failed=out/'failed-preparations';failed.mkdir(exist_ok=True)
    retained=Path(tempfile.mkdtemp(prefix=folder.name+'-',dir=failed))/folder.name
    folder.rename(retained)
    return retained.relative_to(out).as_posix()

def build(root,out,commit,repo,tag,uno_python='/usr/bin/python3',build_timeout=BUILD_TIMEOUT_SECONDS):
    from preparation_queue import load as load_queue,still_prepared,record,update,summaries
    out.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+build_timeout
    def build_command(command):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise CommandTimeoutError('Preparation time budget exhausted; this scope needs a retry')
        return run(command,root,timeout=min(COMMAND_TIMEOUT_SECONDS,remaining))
    report={'sourceCommit':commit,'built':[],'prepared':[],'unchanged':[],'failed':[],'buildComplete':False}
    def checkpoint():
        # Each completed folder already has its immutable prepared snapshot.
        # Keep their inventory even if a later renderer or the runner stops.
        temporary=out/'build-report.json.tmp'
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        temporary.replace(out/'build-report.json')
    readiness=out/'language-readiness.json'
    if readiness.is_file():report['languageReadiness']=read(readiness)
    approved_audio=root/'books/.cache/approved-audio-intake-report.json'
    report['approvedAudioIntakeErrors']=read(approved_audio).get('errors',[])if approved_audio.exists()else[]
    existing=read(root/'books/published-library.json')if(root/'books/published-library.json').exists()else{'schema':SCHEMA,'entries':[]}
    previous={scope_key(row['book']):row for row in existing['entries']}
    pending={scope_key(row):row for row in load_queue(root)['entries']};new_pending=[];completed=[]
    checkpoint()
    for declaration in scopes(root):
        language,collection=key=scope_key(declaration)
        if key in previous and current(root,previous[key]) and not requires_qr_layout_update(previous[key]['book']):
            report['unchanged'].append({'language':language,'collection':collection});checkpoint();continue
        if key in pending and still_prepared(root,pending[key]):
            report['unchanged'].append({'language':language,'collection':collection,'state':pending[key]['state']});checkpoint();continue
        folder=out/(language+'-'+collection);folder.mkdir(exist_ok=True)
        identity={'language':language,'collection':collection}
        report['activeScope']=identity;checkpoint();scope_started=time.monotonic()
        print('[scope:start] '+language+'/'+collection,file=sys.stderr,flush=True)
        try:
            # All source normalization and every lesson's QR are regenerated.
            commands=[
              [sys.executable,'books/index_units.py','--root',root,'--commit',commit,'--language',language,'--collection',collection],
              [sys.executable,'books/build_books.py','--root',root,'--out',folder,'--commit',commit],
              [uno_python,'books/render_uno.py','--folder',folder],
              [sys.executable,'books/native_pagination.py','--root',root,'--folder',folder],
              [uno_python,'books/render_uno.py','--folder',folder,'--keep-contents'],
            ]
            for i,command in enumerate(commands):
                build_command(command)
                if i==0:shutil.copy2(root/'books/manifest.json',folder/'source-manifest.json')
            # Reconcile cached TOC page labels with actual PDF destinations.
            # Re-render after each correction and refuse non-convergence.
            for attempt in range(4):
                try:
                    build_command([sys.executable,'books/toc_sync.py','--folder',folder])
                    break
                except CommandTimeoutError:raise
                except RuntimeError:
                    build_command([sys.executable,'books/toc_sync.py','--folder',folder,'--write'])
                    build_command([uno_python,'books/render_uno.py','--folder',folder,'--keep-contents'])
            build_command([sys.executable,'books/toc_sync.py','--folder',folder])
            build_command([sys.executable,'books/restore_book_fonts.py','--root',root,'--folder',folder])
            # Word can compress RTL text that shares a paragraph with a terminal page break.
            # Normalize equivalent paragraph boundaries before the immutable handoff.
            build_command([sys.executable,'books/normalize_word_page_breaks.py','--folder',folder])
            build_command([sys.executable,'books/check_outputs.py','--root',root,'--folder',folder,'--tag',tag,'--repo',repo,'--prepare-only'])
            index=read(folder/'index.json')
            if len(index['books'])!=1 or scope_key(index['books'][0])!=key:raise ValueError('Scoped build emitted a different book')
            book=index['books'][0]
            book['contentsTargetVerification']=check_contents(folder/book['file'],folder/Path(book['file']).with_suffix('.pdf'))
            holds=[]
            if declaration.get('automaticRelease')is not True:holds.append({'check':'scope-release-hold','reason':declaration.get('releaseHold','Release declaration remains disabled')})
            from check_outputs import require_complete_references
            try:require_complete_references(book)
            except ValueError as error:holds.append({'check':'source-references','reason':str(error),'readiness':book.get('referenceReadiness') or book.get('sourceReferencePreservation')})
            # New Linux renders are preparation artifacts. Never let older
            # declarations silently bypass real Word QC on a changed edition.
            receipt=(folder/book['file']).with_name(book['file']+'.word-layout.json')
            if not receipt.is_file():holds.append({'check':'actual-word-layout','reason':'Awaiting owned Microsoft Word final-file pagination and layout receipt'})
            else:require_word_layout({'requireActualWordLayout':True},folder,book,language)
            holds.append({'check':'final-visual-inspection','reason':'Prepared files need final visual release acceptance; no approval is generated by this job'})
            (folder/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            queued=record(root,index,folder,commit,holds);new_pending.append(queued)
            report['prepared'].append({**identity,'folder':folder.name,'state':queued['state'],'inputFingerprint':queued['inputFingerprint'],'pendingChecks':holds})
        except Exception as error:
            # Partial files have no valid preparation snapshot. They must not
            # shadow an older verified edition with the same public filenames.
            retained=retain_failed_preparation(out,folder,error)
            report['failed'].append({**identity,'error':str(error),'folder':retained})
        report.pop('activeScope',None);checkpoint()
        print(f'[scope:end] {language}/{collection} in {time.monotonic()-scope_started:.2f}s',file=sys.stderr,flush=True)
    update(root,new_pending,completed)
    report['preparedAwaitingReleaseQC']=summaries(root)
    report['buildComplete']=True;checkpoint()
    return report

def candidates(root,out,tag):
    report=read(out/'build-report.json');result=[];assets=[];seen=set()
    if report.get('buildComplete')is False:raise ValueError('Preparation batch did not complete; its checkpoint is not a release')
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
            from published_library import declaration
            declared=declaration(root,key)
            require_word_layout(declared,folder,entry['book'],key[0])
            if declared.get('requireFinalVisualAcceptance') is True:
                from finalize_prepared import verify_final_visual_acceptance
                verify_final_visual_acceptance(folder,entry['book'])
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
    audio_history=[p.relative_to(root).as_posix()for p in sorted((root/'materials/audio/intake-history').glob('*.json'))if re.fullmatch('[a-f0-9]{64}[.]json',p.name)]if root else[]
    intake=root/'books/.cache/material-intake-report.json' if root else None
    transaction_files=read(intake).get('generatedFiles',[]) if intake and intake.exists() else []
    if any(not p.startswith(('books/units/current/','books/units/history/','materials/book-publication-approvals/','materials/book-publication-intake-history/','materials/audio/')) and p not in {'materials/catalog.json','books/reviewed-books.json'} for p in transaction_files):raise ValueError('Unexpected source transaction output')
    connector_history=[p.relative_to(root).as_posix() for p in sorted((root/'materials/book-finalization-intake-history').glob('*.json')) if re.fullmatch('[a-f0-9]{64}[.]json',p.name)] if root else []
    return ['README.md','books/published-library.json','books/prepared-library.json','books/config.json','materials/audio/publish.json','materials/audio/registry.json','docs/listen/materials.json']+[f'books/downloads/{language}/README.md'for language in COPY]+(download_paths(root)if root else[])+audio_history+transaction_files+connector_history

def publish(root,out,commit,repo,tag,execute=run):
    entries,assets=candidates(root,out,tag)
    ensure_main(root,commit)
    staged=execute(['git','diff','--cached','--name-only'],root).splitlines()
    if staged:raise ValueError('Publication requires a checkout with no previously staged changes')
    if assets:
        # A unique run tag is immutable; never overwrite an earlier book pair.
        execute(['gh','release','create',tag,'--repo',repo,'--target',commit,'--draft','--latest=false','--title','Current multilingual books','--notes','Automatically built from current published materials. Each language page lists the included material count.'],root)
        for asset in assets:execute(['gh','release','upload',tag,asset,'--repo',repo],root)
        # Verify the uploaded draft before making any new pair public. A local
        # export check cannot prove that the remote upload has the same bytes.
        draft=None
        for page in range(1,101):
            releases=json.loads(execute(['gh','api',f'repos/{repo}/releases?per_page=100&page={page}'],root))
            matches=[r for r in releases if r.get('tag_name')==tag and r.get('draft')is True]
            if len(matches)>1:raise ValueError('Duplicate draft publication tag')
            if matches:draft=matches[0];break
            if len(releases)<100:break
        if draft is None:raise ValueError('Uploaded draft release is missing')
        for asset in assets:
            path=Path(asset);remote=[a for a in draft.get('assets',[]) if a.get('name')==path.name]
            if len(remote)!=1 or remote[0].get('state')!='uploaded' or remote[0].get('size')!=path.stat().st_size or remote[0].get('digest')!='sha256:'+sha(path.read_bytes()):
                raise ValueError('Uploaded draft asset differs from the checked bytes: '+path.name)
        execute(['gh','release','edit',tag,'--repo',repo,'--draft=false','--latest=false'],root)
    def fetch(release_tag):return json.loads(execute(['gh','api',f'repos/{repo}/releases/tags/{release_tag}'],root))
    existing=read(root/'books/published-library.json')if(root/'books/published-library.json').exists()else{'schema':SCHEMA,'entries':[]}
    library,ready,stale=merge(root,existing,entries,repo,fetch,retain_previous=True)
    from preparation_queue import complete,summaries
    complete(root,[scope_key(entry['book']) for entry in entries])
    ensure_main(root,commit)
    count=stage(root,library,ready,repo)
    from download_page import publish as publish_download_page
    downloads=publish_download_page(root,out,ready,commit,repo,tag,execute)
    from connector_candidate_transfer import record_published
    record_published(root,out,entries,repo)
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
    build_report=read(out/'build-report.json')
    result={'verifiedBookPairs':count,'newPairs':len(entries),'preparedAwaitingReleaseQC':summaries(root),'staleScopesRemoved':stale,'nativeLanguagePages':20,'tablesCommitted':bool(changed),'failedScopes':build_report['failed'],'approvedAudioIntakeErrors':build_report.get('approvedAudioIntakeErrors',[])}
    result['previousEditionsAwaitingUpdate']=[{'language':key[0],'collection':key[1]} for key,book in ready.items() if book.get('availability',{}).get('state')=='previous-published-edition']
    result['verifiedCurrentBookPairs']=sum(not book.get('availability') for book in ready.values())
    result['downloadPage']=downloads
    result['finalizedIntakeErrors']=build_report.get('finalizedIntakeErrors',[])
    intake=root/'books/.cache/material-intake-report.json'
    result['sourceTransactionErrors']=read(intake).get('errors',[]) if intake.exists() else []
    if 'languageReadiness' in build_report:result['languageReadiness']=build_report['languageReadiness']
    (out/'publication-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['build','finalize','publish']);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--commit',required=True);parser.add_argument('--repo',required=True);parser.add_argument('--tag',required=True);parser.add_argument('--uno-python',default='/usr/bin/python3');parser.add_argument('--finalized-dir',type=Path);args=parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.commit)or not re.fullmatch('[A-Za-z0-9._-]+/[A-Za-z0-9._-]+',args.repo)or not re.fullmatch('[A-Za-z0-9._-]{1,120}',args.tag):raise ValueError('Invalid publication identity')
    root=args.root.resolve();out=args.out.resolve()
    if args.action=='build':result=build(root,out,args.commit,args.repo,args.tag,args.uno_python)
    elif args.action=='finalize':
        if args.finalized_dir is None:raise ValueError('Finalization requires an extracted checked-candidate bundle')
        from release_candidate_intake import process
        result=process(root,args.finalized_dir.resolve(),out,args.commit,args.repo,args.tag)
    else:result=publish(root,out,args.commit,args.repo,args.tag)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
