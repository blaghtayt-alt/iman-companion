"""Publish only the human-accepted Arabic Jibril pilot pack successor."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,tempfile,urllib.request,zipfile
REPO='blaghtayt-alt/iman-companion'
TAG='language-packs-2026-10-24-alp-pages-10-19'
BASE='https://github.com/'+REPO+'/releases/download/'+TAG
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def enc(o):return json.dumps(o,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode('utf8')
def copycheck(src,dst,e):
 h=hashlib.sha256();n=0
 for b in iter(lambda:src.read(1048576),b''):h.update(b);n+=len(b);dst.write(b)
 if n!=e['bytes'] or h.hexdigest()!=e['sha256']:raise ValueError('Input asset failed integrity: '+e['path'])
def info(name):
 item=zipfile.ZipInfo(name,(2026,1,1,0,0,0));item.create_system=0;return item
def build(oldfile,audio,config,target):
 old=config['previousPack'];new=config['newPack'];entry=config['audio']
 if oldfile.stat().st_size!=old['bytes'] or digest(oldfile)!=old['sha256'] or audio.stat().st_size!=entry['bytes'] or digest(audio)!=entry['sha256']:raise ValueError('Input pack or audio mismatch')
 with zipfile.ZipFile(oldfile) as z:
  raw=z.read('manifest.json')
  if hashlib.sha256(raw).hexdigest()!=old['manifestSha256']:raise ValueError('Old manifest mismatch')
  manifest=json.loads(raw);files=manifest['files']
  if manifest['language']!='ar' or manifest['version']!=old['version'] or len(files)!=old['files'] or entry['path'] in z.namelist() or 'assets/learning/kids/at-tin-ar.mp3' in z.namelist():raise ValueError('Unexpected predecessor contents')
  merged=sorted(files+[entry],key=lambda x:x['path']);version=hashlib.sha256(enc(merged)).hexdigest()[:20];mr=enc({'schema':1,'language':'ar','version':version,'files':merged})
  if version!=new['version'] or hashlib.sha256(mr).hexdigest()!=new['manifestSha256']:raise ValueError('Successor identity mismatch')
  with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_STORED,allowZip64=False) as out:
   out.writestr(info('manifest.json'),mr)
   for e in merged:
    with (audio.open('rb') if e['path']==entry['path'] else z.open(e['path'])) as src:
     with out.open(info(e['path']),'w') as dst:copycheck(src,dst,e)
 if target.stat().st_size!=new['bytes'] or digest(target)!=new['sha256']:raise ValueError('Successor ZIP does not match independently tested candidate')
 return target
def run(*args):
 return subprocess.run(args,check=True,capture_output=True,text=True).stdout
def read_release():return json.loads(run('gh','api','repos/'+REPO+'/releases/tags/'+TAG))
def remote_catalog():
 req=urllib.request.Request('https://raw.githubusercontent.com/'+REPO+'/refs/heads/main/language-packs/catalog.json',headers={'User-Agent':'Iman-Companion-pilot-publication','Cache-Control':'no-cache'})
 with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--source-pack',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args();root=a.root.resolve()
 config=json.loads((root/'language-packs/jibril-human-pilot-ar.json').read_bytes());old=config['previousPack'];new=config['newPack'];audio=root/config['audioSource'];script=root/config['scriptSource']
 if digest(script)!=config['scriptSHA256'] or config['approval']!='human-accepted-arabic-pilot':raise ValueError('Unexpected approved pilot script')
 with tempfile.TemporaryDirectory() as d:
  temp=Path(d);oldfile=a.source_pack or temp/old['file']
  if not a.source_pack:
   if remote_catalog()['packs']['ar']!=old:raise ValueError('Public Arabic pack changed; rebase and rebuild')
   req=urllib.request.Request(BASE+'/'+old['file'],headers={'User-Agent':'Iman-Companion-pilot-publication'})
   with urllib.request.urlopen(req,timeout=180) as r,oldfile.open('xb') as dst:shutil.copyfileobj(r,dst,1048576)
  target=a.output or temp/new['file'];build(oldfile,audio,config,target)
  if a.verify_only:print(json.dumps({'pass':True,'file':new['file'],'sha256':new['sha256']}));return
  if remote_catalog()['packs']['ar']!=old:raise ValueError('Public Arabic pack changed before upload')
  matches=[x for x in read_release()['assets'] if x['name']==new['file']]
  if matches:
   if len(matches)!=1 or matches[0].get('digest')!='sha256:'+new['sha256'] or matches[0]['size']!=new['bytes']:raise ValueError('Existing asset differs; never overwrite')
  else:run('gh','release','upload',TAG,str(target),'--repo',REPO)
  matches=[x for x in read_release()['assets'] if x['name']==new['file']]
  if len(matches)!=1 or matches[0].get('state')!='uploaded' or matches[0].get('digest')!='sha256:'+new['sha256'] or matches[0].get('size')!=new['bytes'] or matches[0].get('browser_download_url')!=BASE+'/'+new['file']:raise ValueError('Published successor did not verify')
  print(json.dumps({'pass':True,'published':new['file'],'sha256':new['sha256'],'catalogActivated':False}))
if __name__=='__main__':main()
