"""Bind published material audio and refresh the generated direct-player registry."""
from pathlib import Path
import argparse,hashlib,json,urllib.request
from urllib.parse import urlsplit
from material_audio import PLAYER_BASE,validate_record

def verify_remote(entries,fetch=None):
    """Verify the named individual release assets before generating public QRs."""
    cached={}
    for entry in entries:
        path=urlsplit(entry['audioUrl']).path.split('/')
        tag=path[-2]
        if tag not in cached:
            url='https://api.github.com/repos/blaghtayt-alt/iman-companion/releases/tags/'+tag
            if fetch is None:
                request=urllib.request.Request(url,headers={'User-Agent':'Iman-Companion-book-builder','Accept':'application/vnd.github+json'})
                with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
            else:release=fetch(url)
            if release.get('draft') or release.get('tag_name')!=tag:raise ValueError('Audio release is not published under its pinned tag')
            cached[tag]=release
        matches=[a for a in cached[tag].get('assets',[]) if a.get('browser_download_url')==entry['audioUrl']]
        if len(matches)!=1 or matches[0].get('state')!='uploaded' or matches[0].get('size')!=entry['audioBytes'] or matches[0].get('digest')!='sha256:'+entry['audioSHA256']:raise ValueError('Audio release asset identity cannot be verified')

def sync(root,verify_published=False):
    source=root/'materials/audio/registry.json';raw=source.read_bytes();registry=json.loads(raw)
    if registry.get('schema')!='iman-material-audio-v1' or registry.get('playerBase')!=PLAYER_BASE:raise ValueError('Invalid canonical material audio registry')
    published=[];seen=set()
    fields=['materialId','collection','language','title','sourceSHA256','readingSHA256','readerTextSHA256','audioSHA256','audioBytes','audioUrl','approved','status']
    for record in registry.get('entries',[]):
        if record.get('status')!='published' or record.get('approved') is not True:continue
        validate_record(record)
        key=(record['materialId'],record['language'],record['sourceSHA256'])
        if key in seen:raise ValueError('Duplicate published material audio revision')
        seen.add(key);published.append({k:record[k] for k in fields if k in record})
    if verify_published:verify_remote(published)
    public={'schema':registry['schema'],'playerBase':PLAYER_BASE,'entries':published}
    target=root/'docs/listen/materials.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    config=root/'books/config.json';conf=json.loads(config.read_text(encoding='utf-8'));conf['audioRegistry']={'path':source.relative_to(root).as_posix(),'sha256':hashlib.sha256(raw).hexdigest()};config.write_text(json.dumps(conf,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'publishedAudio':len(published),'canonicalRegistrySHA256':hashlib.sha256(raw).hexdigest()}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--verify-remote',action='store_true');args=parser.parse_args();print(json.dumps(sync(args.root.resolve(),verify_published=args.verify_remote)))
if __name__=='__main__':main()
