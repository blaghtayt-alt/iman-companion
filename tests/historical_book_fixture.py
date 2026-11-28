"""Exact historical inputs for code regressions, never current approval.

CI explicitly fetches this existing commit. Production selection always reads
the live checkout; only temporary test roots receive these historical bytes.
"""
from pathlib import Path
import hashlib,subprocess

QURAN_FIXTURE_COMMIT='80c666acc4ca8c87f6f6b0fc2df82be31b4f4792'


def pinned_fixture(repo,relative,digest,commit=QURAN_FIXTURE_COMMIT):
    path=repo/relative
    raw=path.read_bytes() if path.is_file() else None
    if raw is None or hashlib.sha256(raw).hexdigest()!=digest:
        result=subprocess.run(['git','show',commit+':'+relative],cwd=repo,capture_output=True,check=True)
        raw=result.stdout
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Historical test fixture does not match its review pin: '+relative)
    return raw


def copy_projection_fixture(repo,destination,inventory,extra_paths=()):
    pins={}
    for record in inventory['records']:
        for binding in record['sourceFiles']+record['sourceConditions']:
            if binding['path'] in pins and pins[binding['path']]!=binding['sha256']:raise ValueError('Conflicting fixture pins')
            pins[binding['path']]=binding['sha256']
    for relative in set(pins)|set(extra_paths):
        path=destination/relative;path.parent.mkdir(parents=True,exist_ok=True)
        if relative in pins:raw=pinned_fixture(repo,relative,pins[relative],inventory['sourceCommit'])
        elif relative=='materials/catalog.json':
            # Live approved successors must not change an historical fixture's
            # membership or add current-only reader bindings to that fixture.
            raw=subprocess.run(['git','show',inventory['sourceCommit']+':'+relative],cwd=repo,capture_output=True,check=True).stdout
        else:raw=(repo/relative).read_bytes()
        path.write_bytes(raw)


# Exact immediately pre-V4 book declarations; never installed in production.
LEGACY_TADABBUR_COMMIT='0f2e681490ed2e6eb4ded796f91a2ff93a03c1ae'
LEGACY_DECLARATIONS_BLOB='797a93ab2693db4c5fa396ec9c3c06f6532d5a88'


def legacy_tadabbur_declarations(repo):
    import json
    raw=subprocess.run(['git','show',LEGACY_TADABBUR_COMMIT+':books/reviewed-books.json'],cwd=repo,capture_output=True,check=True).stdout
    actual=hashlib.sha1(b'blob '+str(len(raw)).encode('ascii')+b'\0'+raw).hexdigest()
    if actual!=LEGACY_DECLARATIONS_BLOB:raise ValueError('Legacy Tadabbur fixture declaration pin differs')
    data=json.loads(raw)
    rows=[r for r in data['books'] if r['collection']=='tadabbur-extended']
    if len(rows)!=20 or len({r['language'] for r in rows})!=20:raise ValueError('Legacy fixture scope inventory changed')
    return rows


def restore_legacy_tadabbur_declarations(repo,destination):
    """Copy exact historical declarations into an isolated test root only."""
    import json
    if Path(repo).resolve()==Path(destination).resolve():raise ValueError('Do not install historical fixtures in the live checkout')
    target=Path(destination)/'books/reviewed-books.json'
    data=json.loads(target.read_bytes()) if target.is_file() else {'schema':'iman-reviewed-books-v1','books':[]}
    data['books']=[r for r in data['books'] if r['collection']!='tadabbur-extended']+legacy_tadabbur_declarations(repo)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def copy_legacy_ikhlas_fixture(repo,destination):
    """Materialize exact historical reader inputs for adapter regression only."""
    if Path(repo).resolve()==Path(destination).resolve():raise ValueError('Historical fixture requires an isolated root')
    prefixes=['materials/catalog.json','materials/tadabbur/sources/112','materials/tadabbur/ikhlas-112','books/assets/quran-arabic.json','books/config.json','books/reviewed-books.json']
    for row in legacy_tadabbur_declarations(repo):
        if row['language']!='ar':
            prefixes.extend('materials/tadabbur/'+row['language']+'/extended/112'+suffix for suffix in ('.json','.md'))
    paths=subprocess.run(['git','ls-tree','-r','--name-only',LEGACY_TADABBUR_COMMIT,'--',*prefixes],cwd=repo,capture_output=True,check=True,text=True).stdout.splitlines()
    if not paths:raise ValueError('Missing historical Ikhlas fixture paths')
    for relative in paths:
        target=Path(destination)/relative;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.run(['git','show',LEGACY_TADABBUR_COMMIT+':'+relative],cwd=repo,capture_output=True,check=True).stdout)
