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

    # The pre-V4 catalogue also contains a typed legacy Ikhlas publisher
    # unit (Filipino FINAL746). Copy its exact historical dependency closure,
    # not just the adapter's source directory. These bytes are confined to the
    # isolated regression fixture and must never authorize the V4 readers.
    import json
    destination=Path(destination).resolve()
    catalog=json.loads((destination/'materials/catalog.json').read_bytes())

    def copy_bound(binding):
        relative=binding['path']
        target=(destination/relative).resolve()
        if not target.is_relative_to(destination) or target==destination:
            raise ValueError('Historical Ikhlas dependency escapes fixture')
        raw=subprocess.run(['git','show',LEGACY_TADABBUR_COMMIT+':'+relative],
                           cwd=repo,capture_output=True,check=True).stdout
        if hashlib.sha256(raw).hexdigest()!=binding['sha256']:
            raise ValueError('Historical Ikhlas dependency differs from its pin: '+relative)
        if target.exists() and target.read_bytes()!=raw:
            raise ValueError('Conflicting historical Ikhlas fixture dependency: '+relative)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        return raw

    for row in catalog['entries']:
        if row.get('collection')!='tadabbur' or str(row.get('id'))!='112:extended' or not row.get('bookReaderUnit'):
            continue
        unit=json.loads(copy_bound(row['bookReaderUnit']))
        if (unit.get('collection'),unit.get('language'),unit.get('id'))!=('tadabbur-extended',row['language'],'112:extended'):
            raise ValueError('Historical Ikhlas typed reader identity differs')
        inputs={}
        for binding in unit['inputBindings']:
            if binding['path'] in inputs:
                raise ValueError('Duplicate historical Ikhlas reader dependency')
            inputs[binding['path']]=binding['sha256']
            copy_bound(binding)
        approval=unit['publicationApproval']
        if inputs.get(approval['path'])!=approval['sha256']:
            raise ValueError('Historical Ikhlas reader omits its approval binding')
        handoff=json.loads((destination/approval['path']).read_bytes())
        # The original approved snapshot, source files and review evidence
        # must be included under their own exact pins. The production selector
        # still independently validates the complete handoff in the test.
        for binding in [handoff['readerUnit'],*handoff['sourceBindings'],*handoff['approval']['reviewArtifacts']]:
            if inputs.get(binding['path'])!=binding['sha256']:
                raise ValueError('Historical Ikhlas reader omits a pinned handoff dependency')

