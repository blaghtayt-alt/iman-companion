"""Publish one already-reviewed source and its book unit as one Git commit.

This is the source publisher, not an approval or translation generator. The
caller supplies the actual whole-review evidence and exact normalized reader.
The regular book workflow sees the source, catalogue and reader in one commit.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,re,subprocess,tempfile
from publish_approved_material import prepare,bytes_json

def git(root,*args,input=None,env=None,check=True):
    p=subprocess.run(['git',*map(str,args)],cwd=root,input=input,capture_output=True,env=env)
    if check and p.returncode:raise ValueError('Git operation failed: '+p.stderr.decode('utf8','replace')[-1000:])
    return p

def safe(root,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or any(ord(c)<32 for c in relative):raise ValueError('Unsafe publication path')
    p=PurePosixPath(relative)
    if p.is_absolute() or any(x in {'.','..'} for x in p.parts):raise ValueError('Unsafe publication path')
    candidate=root/Path(relative);current=root
    for part in p.parts:
        current=current/part
        if current.is_symlink():raise ValueError('Symlink cannot be a publication path')
    resolved=candidate.resolve()
    if not resolved.is_relative_to(root) or resolved==root:raise ValueError('Publication path leaves source repository')
    return resolved

def blob(root,head,relative):
    result=git(root,'show',head+':'+relative,check=False)
    if result.returncode:
        exists=git(root,'cat-file','-e',head+':'+relative,check=False)
        if exists.returncode:return None
        raise ValueError('Unable to read current tracked source')
    return result.stdout

def plan(root,handoff,expected_head):
    root=root.resolve();handoff=handoff.resolve()
    if Path(git(root,'rev-parse','--show-toplevel').stdout.decode('utf8').strip()).resolve()!=root:raise ValueError('Use the repository root')
    if not re.fullmatch('[a-f0-9]{40}',expected_head):raise ValueError('Exact expected main commit required')
    head=git(root,'rev-parse','HEAD').stdout.decode().strip()
    if head!=expected_head:raise ValueError('Source checkout advanced; revalidate before publishing')
    old_catalog=blob(root,head,'materials/catalog.json')
    if old_catalog is None or (root/'materials/catalog.json').read_bytes()!=old_catalog:raise ValueError('Source catalogue differs from current Git commit')
    raw=handoff.read_bytes();data=json.loads(raw);digest=hashlib.sha256(raw).hexdigest()
    bases=data.get('expectedSourceBase')
    if not isinstance(bases,list):raise ValueError('Expected source baselines are required')
    expected={}
    for item in bases:
        relative=item.get('path');safe(root,relative);value=item.get('sha256')
        if relative in expected or (value is not None and not re.fullmatch('[a-f0-9]{64}',value or '')):raise ValueError('Invalid or duplicate source baseline')
        expected[relative]=value
    actual_sources=[item.get('path') for item in data.get('sourceBindings',[])]
    if len(actual_sources)!=len(set(actual_sources)) or set(actual_sources)!=set(expected):raise ValueError('Every source needs one exact baseline')
    for relative in actual_sources:
        previous=blob(root,head,relative);previous_sha=hashlib.sha256(previous).hexdigest() if previous is not None else None
        if expected[relative]!=previous_sha:raise ValueError('Source advanced since review: '+relative)
    writes,receipt=prepare(root,handoff)
    # These outputs are calculated against the current tracked state. Never
    # overwrite a local or newer version that differs from that state.
    for relative in writes:
        path=safe(root,relative);before=blob(root,head,relative)
        if path.is_symlink():raise ValueError('Symlink cannot be a publication output')
        if before is None and path.exists():raise ValueError('Untracked publication output already exists: '+relative)
        if before is not None and (not path.is_file() or path.read_bytes()!=before):raise ValueError('Publication output changed locally: '+relative)
    files={}
    for item in receipt['requiredInputs']:
        relative=item['path'];path=safe(root,relative)
        if path.is_symlink() or not path.is_file():raise ValueError('Missing source or review input: '+relative)
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Reviewed publication input changed: '+relative)
        tracked=blob(root,head,relative)
        if relative not in expected and tracked is not None and tracked!=data:raise ValueError('Existing review or reader input cannot be replaced: '+relative)
        files[relative]=data
    for relative,data in writes.items():
        if relative in files and files[relative]!=data:raise ValueError('Source and generated outputs conflict: '+relative)
        files[relative]=data
    intake='materials/book-publication-intake/'+digest+'.json'
    history='materials/book-publication-intake-history/'+digest+'.json'
    proof={**receipt,'intakeSHA256':digest,'intakePath':intake}
    for relative,data in [(intake,raw),(history,bytes_json(proof))]:
        path=safe(root,relative);before=blob(root,head,relative)
        if path.is_symlink() or (before is not None and before!=data) or (before is None and path.exists() and path.read_bytes()!=data):raise ValueError('Immutable transaction history conflicts: '+relative)
        files[relative]=data
    for relative in files:
        safe(root,relative)
        tree=git(root,'ls-tree','-z',head,'--',relative).stdout
        if tree and tree.split(b' ',1)[0]!=b'100644':raise ValueError('Publication cannot change a special file mode: '+relative)
    if git(root,'rev-parse','HEAD').stdout.decode().strip()!=head:raise ValueError('Source checkout advanced while preparing publication')
    guards={}
    for relative in files:
        path=safe(root,relative)
        guards[relative]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return head,files,receipt,{'files':guards,'handoffPath':str(handoff),'handoffSHA256':digest}

def unchanged(root,guards):
    handoff=Path(guards['handoffPath'])
    if not handoff.is_file() or hashlib.sha256(handoff.read_bytes()).hexdigest()!=guards['handoffSHA256']:raise ValueError('Reviewed handoff changed during publication')
    for relative,expected in guards['files'].items():
        path=safe(root,relative);actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual!=expected:raise ValueError('Local publication input changed during publication: '+relative)

def commit_and_push(root,head,files,message,expected_remote,guards):
    root=root.resolve();actual_remote=git(root,'remote','get-url','origin').stdout.decode('utf8').strip()
    if not expected_remote or actual_remote!=expected_remote:raise ValueError('Publication remote differs from the expected repository')
    unchanged(root,guards)
    remote=git(root,'ls-remote','origin','refs/heads/main').stdout.decode().split()
    if not remote or remote[0]!=head:raise ValueError('Remote main advanced; revalidate before publication')
    # An isolated temporary Git index leaves the user's index and worktree alone.
    descriptor,index=tempfile.mkstemp(prefix='iman-source-index-');os.close(descriptor);os.unlink(index)
    env={**os.environ,'GIT_INDEX_FILE':index}
    try:
        git(root,'read-tree',head,env=env)
        for relative,data in sorted(files.items()):
            oid=git(root,'hash-object','-w','--stdin',input=data).stdout.decode().strip()
            git(root,'update-index','--add','--cacheinfo','100644',oid,relative,env=env)
        tree=git(root,'write-tree',env=env).stdout.decode().strip()
        if git(root,'rev-parse','HEAD').stdout.decode().strip()!=head:raise ValueError('Source checkout advanced during publication')
        commit=git(root,'commit-tree',tree,'-p',head,'-m',message).stdout.decode().strip()
        unchanged(root,guards)
        # This is always a fast-forward and Git rejects an advanced remote.
        git(root,'push','origin',commit+':refs/heads/main')
        return commit
    finally:
        if os.path.isfile(index):os.unlink(index)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--handoff',type=Path,required=True);p.add_argument('--expected-head',required=True);p.add_argument('--expected-remote');p.add_argument('--message',default='Publish reviewed source and book reader');p.add_argument('--publish',action='store_true');a=p.parse_args()
    root=a.root.resolve();head,files,receipt,guards=plan(root,a.handoff,a.expected_head)
    result={'schema':'iman-source-publication-transaction-v1','expectedHead':head,'material':receipt['material'],'paths':sorted(files),'published':False}
    if a.publish:result.update({'commit':commit_and_push(root,head,files,a.message,a.expected_remote,guards),'published':True})
    print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':main()
