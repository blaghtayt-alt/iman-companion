"""Expose unchanged, already-published audio-pack members to the direct player.

Run only in the repository-owned Actions job. It does not create recordings or
approve source material; exact current published source and asset hashes gate it.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,tempfile,urllib.request,zipfile
from urllib.parse import urlsplit

REPO='blaghtayt-alt/iman-companion'
BASE='https://github.com/'+REPO+'/releases/download/'
PLAYER='https://blaghtayt-alt.github.io/iman-companion/listen/'
RETIRED={'held','draft','withdrawn','private','superseded','archived','not-currently-available'}

def retired(row):
    return row.get('current',True)is False or row.get('archived')is True or any(str(row.get(k,'')).lower()in RETIRED for k in ['status','publicationStatus','translationStatus'])
def sha(raw):return hashlib.sha256(raw).hexdigest()
def gh(*args):
    result=subprocess.run(['gh',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode:raise RuntimeError('GitHub operation failed: '+result.stderr[-1200:])
    return result.stdout
def read_release(tag):
    r=subprocess.run(['gh','api','repos/'+REPO+'/releases/tags/'+tag],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode:
        if '404' in r.stderr:return None
        raise RuntimeError('Could not read audio release: '+r.stderr[-1000:])
    return json.loads(r.stdout)
def validate_source(root,record):
    if record.get('collection')!='seerah' or record.get('approved') is not True:raise ValueError('Only the declared already-published Seerah audio is supported by this adapter')
    language=record['language'];index_path=root/'materials/seerah/new-adult'/language/'index.json'
    if not index_path.resolve().is_relative_to(root.resolve()):raise ValueError('Invalid audio source path')
    index_raw=index_path.read_bytes();index=json.loads(index_raw)
    if index.get('schema')!='new-adult-seerah-source-index-v1' or index.get('language')!=language:raise ValueError('Unexpected published audio source schema')
    approved=record['origin']['approvedAppRecord']
    if approved.get('approved') is not True or approved.get('locale')!=language or approved.get('sourceSHA256')!=record['sourceSHA256'] or approved.get('audioSHA256')!=record['audioSHA256']:raise ValueError('Approved app audio identity mismatch')
    chapter=next((c for c in index['chapters'] if c['id']==approved['chapterId'] and c['sourceSHA256']==record['sourceSHA256']),None)
    if not chapter or chapter.get('audio',{}).get('sha256')!=record['audioSHA256']:raise ValueError('Current published chapter/audio revision changed')
    if retired(index)or retired(chapter)or retired(chapter['audio']):raise ValueError('Audio is no longer available for publication')
    if record['materialId']!='new-seerah'+str(chapter['number']).zfill(3):raise ValueError('Audio belongs to a different lesson')
    reading=(index_path.parent/chapter['readingPath']).resolve()
    if not reading.is_relative_to(index_path.parent.resolve()) or sha(reading.read_bytes())!=record['readingSHA256'] or chapter['readingSHA256']!=record['readingSHA256']:raise ValueError('Published target reading changed')
    pack_url=record['origin']['packUrl']
    if not pack_url.startswith(BASE):raise ValueError('Unexpected published audio pack URL')
    pack=next((v for v in index.values() if isinstance(v,dict) and v.get('sha256')==record['origin']['packSHA256'] and v.get('file')==urlsplit(pack_url).path.rsplit('/',1)[1]),None)
    if not pack:raise ValueError('Pack no longer matches the published source index')
    if record['audioUrl']!=BASE+'material-audio-v1/'+urlsplit(record['audioUrl']).path.rsplit('/',1)[1] or record['audioSHA256'][:16] not in record['audioUrl']:raise ValueError('Invalid immutable audio destination')
    return chapter,pack,{'path':index_path.relative_to(root).as_posix(),'sha256':sha(index_raw)}

def select_current_sources(root,records):
    selected=[];retired_records=[];seen=set()
    for record in records:
        key=(record['materialId'],record['language'])
        if key in seen:raise ValueError('Duplicate current audio material/language')
        seen.add(key)
        if retired(record)or record.get('approved')is not True:
            retired_records.append({'materialId':record['materialId'],'language':record['language'],'reason':'not-current-approved-audio'});continue
        try:binding=validate_source(root,record)
        except (ValueError,FileNotFoundError)as error:
            retired_records.append({'materialId':record['materialId'],'language':record['language'],'reason':str(error)});continue
        selected.append((record,binding))
    return selected,retired_records

def reconcile_registry(root,old,published,seed):
    """Drop stale direct players as well as stale book QR cards automatically."""
    replacements={(r['materialId'],r['language'],r['sourceSHA256']):r for r in published}
    seed_by_scope={(r['materialId'],r['language']):r for r in seed}
    output=[]
    for previous in old.get('entries',[]):
        key=(previous['materialId'],previous['language'],previous['sourceSHA256'])
        if key in replacements:continue
        record=dict(previous)
        if record.get('collection')=='seerah'and record.get('origin',{}).get('approvedAppRecord'):
            matching=seed_by_scope.get(key[:2])
            invalid_seed=matching is not None and(retired(matching)or matching.get('approved')is not True or matching.get('audioSHA256')!=record.get('audioSHA256')or matching.get('sourceSHA256')!=record.get('sourceSHA256'))
            try:validate_source(root,record)
            except (ValueError,FileNotFoundError):invalid_seed=True
            if invalid_seed:record['status']='withdrawn-source-changed'
        output.append(record)
    return {'schema':'iman-material-audio-v1','playerBase':PLAYER,'entries':output+published}
def public_manifest(registry):
    keys=['materialId','collection','language','title','sourceSHA256','readingSHA256','readerTextSHA256','audioSHA256','audioBytes','audioUrl','approved','status']
    return {'schema':'iman-material-audio-v1','playerBase':PLAYER,'entries':[{k:r[k] for k in keys if k in r} for r in registry['entries'] if r.get('status')=='published' and r.get('approved') is True]}
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--verify-only',action='store_true');args=p.parse_args();root=args.root.resolve()
    seed=json.loads((root/'materials/audio/publish.json').read_text(encoding='utf-8'))
    if seed.get('schema')!='iman-material-audio-v1' or seed.get('playerBase')!=PLAYER:raise ValueError('Invalid audio publication input')
    selected,retired_records=select_current_sources(root,seed['entries'])
    if args.verify_only:
        registry=json.loads((root/'materials/audio/registry.json').read_bytes())
        for record in registry['entries']:
            if record.get('status')=='published'and record.get('collection')=='seerah':validate_source(root,record)
        print(json.dumps({'verifiedCurrentPublishedAudioInputs':len(selected),'retiredInputs':retired_records}));return
    release=read_release('material-audio-v1')
    if release is None and selected:
        gh('release','create','material-audio-v1','--repo',REPO,'--target',os.environ['GITHUB_SHA'],'--title','Material audio player files','--notes','Unchanged recordings from the published material audio packs. Source and listening-review conditions remain with the materials.','--latest=false');release=read_release('material-audio-v1')
    existing={a['name']:a for a in(release or{}).get('assets',[])};published=[]
    with tempfile.TemporaryDirectory() as tmp:
        cache=Path(tmp)
        for record,(chapter,pack,binding) in selected:
            filename=urlsplit(record['audioUrl']).path.rsplit('/',1)[1];asset=existing.get(filename)
            if asset:
                if asset.get('digest')!='sha256:'+record['audioSHA256'] or asset['size']!=record['audioBytes']:raise ValueError('Existing immutable audio asset differs; refusing overwrite')
            else:
                archive=cache/pack['file']
                if not archive.exists():
                    with urllib.request.urlopen(record['origin']['packUrl'],timeout=90) as response,archive.open('wb') as output:
                        while chunk:=response.read(1024*1024):output.write(chunk)
                if sha(archive.read_bytes())!=pack['sha256'] or archive.stat().st_size!=pack['bytes']:raise ValueError('Published audio-pack digest/size mismatch')
                with zipfile.ZipFile(archive) as z:
                    names=[n for n in z.namelist() if n==chapter['audio']['asset'] or n.endswith('/'+chapter['audio']['asset'])]
                    if len(names)!=1:raise ValueError('Exact audio pack member was not found')
                    audio=z.read(names[0])
                if sha(audio)!=record['audioSHA256'] or len(audio)!=record['audioBytes']:raise ValueError('Unchanged audio bytes failed their published hash')
                destination=cache/filename;destination.write_bytes(audio)
                gh('release','upload','material-audio-v1',str(destination),'--repo',REPO)
            current=read_release('material-audio-v1');asset=next(a for a in current['assets'] if a['name']==filename)
            if asset.get('digest')!='sha256:'+record['audioSHA256'] or asset['size']!=record['audioBytes']:raise ValueError('Uploaded direct audio digest/size did not verify')
            output={**record,'title':chapter['title'],'status':'published','publishedSourceBinding':binding,'reviewScope':chapter['audio'].get('reviewScope','')};published.append(output)
    target=root/'materials/audio/registry.json'
    old=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'entries':[]}
    registry=reconcile_registry(root,old,published,seed['entries'])
    target.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'docs/listen/materials.json').write_text(json.dumps(public_manifest(registry),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'publishedDirectAudio':len(published),'playerBase':PLAYER,'sourceApprovalChanged':False,'retiredInputs':retired_records}))
if __name__=='__main__':main()
