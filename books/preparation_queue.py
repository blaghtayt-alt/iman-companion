"""Durable preparation state, deliberately inadmissible as a public release.

GitHub's existing source-push job renders candidates and uploads its artifacts.
This queue binds those candidates to the exact source/approval/settings inputs.
Actual Word and visual release checks remain explicit, independent gates.
"""
import copy,json,os,re
from pathlib import Path
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
from published_library import read,sha,inside,scope_key,declaration,catalog_members,catalog_fingerprint,scope_settings,capture

SCHEMA='iman-book-preparation-queue-v1'
PATH='books/prepared-library.json'

def artifact_available(artifact):
    """A source signature alone does not prove that queued files still exist."""
    try:
        if datetime.fromisoformat(artifact['expiresAt'])<=datetime.now(timezone.utc):return False
        repo=artifact['repository'];run=artifact['runId']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or not re.fullmatch(r'\d+',run):return False
        headers={'User-Agent':'Iman-Companion-books','Accept':'application/vnd.github+json'}
        token=os.environ.get('GH_TOKEN')
        if token:headers['Authorization']='Bearer '+token
        request=Request(f'https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts?per_page=100',headers=headers)
        with urlopen(request,timeout=15) as response:data=json.load(response)
        matches=[a for a in data.get('artifacts',[]) if a.get('name')==artifact['name']]
        return len(matches)==1 and matches[0].get('expired')is False and matches[0].get('size_in_bytes',0)>0
    except (ValueError,OSError,KeyError,TypeError):return False

def signature(root,key):
    declared=declaration(root,key,for_release=False)
    rows,report=catalog_members(root,key,for_release=False)
    if not rows:raise ValueError('No eligible reviewed material in scope')
    inputs={}
    for row in rows:
        for name in ('json','markdown'):
            if row.get(name):inputs[row[name]]=sha(inside(root,row[name]).read_bytes())
    # Rendering code matters to pending preparation; unrelated publication
    # metadata or another language's new material does not change this key.
    code={p.name:sha(p.read_bytes()) for p in sorted((root/'books').glob('*.py')) if not p.name.startswith('test_')}
    payload={'declaration':declared,'catalog':catalog_fingerprint(rows,report),'inputs':inputs,
      'settings':scope_settings(root,key,[str(r['id']) for r in rows]),'code':code}
    return sha(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf8'))

def load(root):
    path=root/PATH
    result=read(path) if path.exists() else {'schema':SCHEMA,'entries':[]}
    if result.get('schema')!=SCHEMA:raise ValueError('Invalid book preparation queue')
    if len({scope_key(r) for r in result['entries']})!=len(result['entries']):raise ValueError('Duplicate preparation queue scope')
    return result

def summaries(root):
    """Report the whole queue, including unchanged and stale pending editions.

    Candidate snapshots are intentionally excluded: their prospective release
    URLs are not downloads. Keep the artifact location and exact pending checks
    visible on retry, without rendering again or querying artifact transport.
    """
    result=[]
    for row in load(root)['entries']:
        item={key:copy.deepcopy(row[key]) for key in (
            'language','collection','sourceCommit','inputFingerprint','state',
            'folder','pendingChecks','artifact') if key in row}
        item['releaseVerified']=False
        item['includedUnits']=len(row.get('candidate',{}).get('snapshot',{}).get('unitIds',[]))
        result.append(item)
    return result

def complete(root,keys):
    """Remove only successfully released scopes, preserving other queue records."""
    keys=set(keys)
    if not keys:return
    queue=load(root)
    queue['entries']=[row for row in queue['entries'] if scope_key(row) not in keys]
    (root/PATH).write_text(json.dumps(queue,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def still_prepared(root,row):
    try:
        if row.get('artifact') and not artifact_available(row['artifact']):return False
        if row.get('localArtifacts') and not all(Path(b['path']).is_file() and sha(Path(b['path']).read_bytes())==b['sha256'] for b in row['localArtifacts']):return False
        if row['inputFingerprint']!=signature(root,scope_key(row)):return False
        snapshot=row['candidate']['snapshot']
        if snapshot['scopeSettingsSHA256']!=scope_settings(root,scope_key(row),snapshot['unitIds']):return False
        return bool(snapshot['bindings']) and all(sha(inside(root,b['path']).read_bytes())==b['sha256'] for b in snapshot['bindings'])
    except (ValueError,OSError,KeyError):return False

def record(root,index,folder,commit,holds):
    prepared=capture(root,index,preparation=True)
    if len(prepared['entries'])!=1:raise ValueError('One prepared scope per queue entry')
    candidate=prepared['entries'][0];key=scope_key(candidate['book'])
    row={'language':key[0],'collection':key[1],'sourceCommit':commit,
      'inputFingerprint':signature(root,key),'state':'prepared-awaiting-release-qc',
      'releaseVerified':False,'pendingChecks':holds,'candidate':candidate,'folder':folder.name}
    run=os.environ.get('GITHUB_RUN_ID');attempt=os.environ.get('GITHUB_RUN_ATTEMPT');repo=os.environ.get('GITHUB_REPOSITORY')
    if run and attempt and repo:
        now=datetime.now(timezone.utc)
        row['artifact']={'runURL':f'https://github.com/{repo}/actions/runs/{run}',
          'repository':repo,'runId':run,'name':f'current-book-publication-{run}-{attempt}',
          'createdAt':now.isoformat(),'expiresAt':(now+timedelta(days=90)).isoformat(),'retentionDays':90}
    else:
        book=candidate['book'];word=folder/book['file']
        row['localArtifacts']=[{'path':str(word.resolve()),'sha256':book['sha256']},{'path':str(word.with_suffix('.pdf').resolve()),'sha256':book['pdfSha256']}]
    (folder/'prepared-snapshot.json').write_text(json.dumps({'schema':SCHEMA,'entries':[row]},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return row

def update(root,rows,completed):
    existing=load(root);replaced={scope_key(r) for r in rows}|set(completed)
    kept=[]
    for row in existing['entries']:
        if scope_key(row) in replaced:continue
        retained=copy.deepcopy(row)
        if not still_prepared(root,row):retained['state']='superseded-source-awaiting-preparation';retained['releaseVerified']=False
        kept.append(retained)
    result={'schema':SCHEMA,'entries':sorted(kept+rows,key=scope_key)}
    (root/PATH).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return result
