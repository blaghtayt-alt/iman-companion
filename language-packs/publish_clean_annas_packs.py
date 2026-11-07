"""Publish exact clean successors of public packs; retain old packs and all other files."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,tempfile,urllib.request,zipfile

REPO='blaghtayt-alt/iman-companion'
TAG='language-packs-2026-10-24-alp-pages-10-19'
BASE='https://github.com/'+REPO+'/releases/download/'+TAG+'/'
encode=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode('utf8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for part in iter(lambda:f.read(1048576),b''):h.update(part)
    return h.hexdigest()
def check_stream(source,dest,entry):
    h=hashlib.sha256();size=0
    for part in iter(lambda:source.read(1048576),b''):
        h.update(part);size+=len(part)
        if dest is not None:dest.write(part)
    if h.hexdigest()!=entry['sha256'] or size!=entry['bytes']:raise ValueError('Pack member digest mismatch: '+entry['path'])
def info(name):
    item=zipfile.ZipInfo(name,(2026,1,1,0,0,0));item.create_system=0;return item
def build(row,source,target):
    old=row['oldPack'];new=row['newPack']
    if source.stat().st_size!=old['bytes'] or sha(source)!=old['sha256']:raise ValueError('Published predecessor pack changed')
    with zipfile.ZipFile(source) as z:
        raw=z.read('manifest.json')
        if hashlib.sha256(raw).hexdigest()!=old['manifestSha256']:raise ValueError('Predecessor manifest changed')
        manifest=json.loads(raw);files=manifest['files'];removed=[e for e in files if e['path']==row['excludedAsset']]
        if manifest['language']!=row['language'] or manifest['version']!=old['version'] or len(files)!=old['files'] or len({e['path'] for e in files})!=len(files):raise ValueError('Unexpected predecessor identity')
        if len(removed)!=1 or removed[0]['sha256']!=row['excludedSHA256']:raise ValueError('Exact held recording not found')
        if set(z.namelist())!={'manifest.json'}|{e['path'] for e in files}:raise ValueError('Unexpected predecessor ZIP members')
        kept=[e for e in files if e['path']!=row['excludedAsset']];version=hashlib.sha256(encode(kept)).hexdigest()[:20]
        if version!=new['version'] or new['file']!=f"iman-{row['language']}-{version}.zip":raise ValueError('Unexpected clean version')
        manifest_raw=encode({'schema':1,'language':row['language'],'version':version,'files':kept})
        if hashlib.sha256(manifest_raw).hexdigest()!=new['manifestSha256'] or len(kept)!=new['files'] or sum(e['bytes'] for e in kept)!=new['unpackedBytes']:raise ValueError('Unexpected clean manifest')
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_STORED,allowZip64=False) as result:
            result.writestr(info('manifest.json'),manifest_raw)
            for entry in files:
                with z.open(entry['path']) as member:
                    if entry['path']==row['excludedAsset']:check_stream(member,None,entry)
                    else:
                        with result.open(info(entry['path']),'w') as output:check_stream(member,output,entry)
    if target.stat().st_size!=new['bytes'] or sha(target)!=new['sha256']:raise ValueError('Clean archive does not match the independently built pack')
    with zipfile.ZipFile(target) as check:
        if row['excludedAsset'] in check.namelist() or set(check.namelist())!={'manifest.json'}|{e['path'] for e in kept}:raise ValueError('Held audio survived clean packaging')
def gh(*args):
    p=subprocess.run(['gh',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if p.returncode:raise RuntimeError('GitHub operation failed: '+p.stderr[-1200:])
    return p.stdout
def assets():
    release=json.loads(gh('api',f'repos/{REPO}/releases/tags/{TAG}'))
    if release.get('draft'):raise ValueError('Pack release is a draft')
    return {a['name']:a for a in release['assets']}
def verify_asset(asset,metadata):
    return bool(asset and asset.get('state')=='uploaded' and asset.get('digest')=='sha256:'+metadata['sha256'] and asset.get('size')==metadata['bytes'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--test-local',type=Path);p.add_argument('--language');args=p.parse_args();root=args.root.resolve();spec=json.loads((root/'language-packs/annas-human-hold.json').read_bytes());rows=spec['entries']
    if spec.get('schema')!='iman-annas-human-pack-hold-v1' or spec.get('releaseTag')!=TAG or {r['language'] for r in rows}!={'ar','bn','en','fr','ms','pt-BR','tr','ur'} or len(rows)!=8:raise ValueError('Unexpected human-hold scope')
    if args.test_local and not args.language:raise ValueError('Select one local language test')
    with tempfile.TemporaryDirectory() as temporary:
        temp=Path(temporary)
        for row in rows:
            if args.language and row['language']!=args.language:continue
            if row['oldURL']!=BASE+row['oldPack']['file'] or row['excludedAsset']!=f"assets/learning/kids/an-nas-{row['language']}.mp3":raise ValueError('Unexpected public predecessor')
            old=temp/row['oldPack']['file'];new=temp/row['newPack']['file']
            if args.test_local:old=args.test_local/row['oldPack']['file']
            else:
                current=assets()
                if not verify_asset(current.get(row['oldPack']['file']),row['oldPack']):raise ValueError('Public predecessor asset digest differs')
                if row['newPack']['file'] in current:
                    if not verify_asset(current[row['newPack']['file']],row['newPack']):raise ValueError('Existing immutable clean asset differs')
                    print('Already verified:',row['language'],flush=True);continue
                with urllib.request.urlopen(row['oldURL'],timeout=120) as response,old.open('xb') as output:
                    for part in iter(lambda:response.read(1048576),b''):output.write(part)
            build(row,old,new)
            if not args.test_local:
                gh('release','upload',TAG,str(new),'--repo',REPO)
                if not verify_asset(assets().get(row['newPack']['file']),row['newPack']):raise ValueError('Clean uploaded asset did not verify')
                old.unlink()
            new.unlink();print('Verified clean pack:',row['language'],flush=True)
    if not args.test_local:
        current=assets()
        if not all(verify_asset(current.get(r['newPack']['file']),r['newPack']) for r in rows):raise ValueError('Not all clean pack assets are published')
    print(json.dumps({'cleanPacksVerified':1 if args.language else len(rows),'catalogActivated':False,'oldPublicPacksDeleted':False}))
if __name__=='__main__':main()
