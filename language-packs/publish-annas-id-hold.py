from pathlib import Path
import argparse,json,subprocess,tempfile,urllib.request
from publish_clean_attin_packs import REPO,TAG,build,assets,verify_asset,gh
def current():
 req=urllib.request.Request('https://raw.githubusercontent.com/'+REPO+'/refs/heads/main/language-packs/catalog.json',headers={'User-Agent':'Iman-Companion-AnnNas-hold','Cache-Control':'no-cache'})
 with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--test-local',type=Path);a=p.parse_args();root=a.root.resolve()
 data=json.loads((root/'language-packs/annas-indonesian-hold.json').read_bytes());r=data['entry'];old=r['oldPack'];new=r['newPack']
 if data['schema']!='iman-annas-indonesian-audio-hold-v1' or data['releaseTag']!=TAG or r['language']!='id' or r['excludedAsset']!='assets/learning/kids/an-nas-id.mp3' or r['excludedSHA256']!='3f2143f718d2141afb2e4f92d5704bab077197b7baf6557a560aabbe0bc5e274':raise ValueError('Unexpected hold scope')
 with tempfile.TemporaryDirectory() as d:
  folder=Path(d);source=a.test_local or folder/old['file'];target=folder/new['file']
  if not a.test_local:
   if current()['packs']['id']!=old:raise ValueError('Public Indonesian pack changed')
   published=assets()
   if not verify_asset(published.get(old['file']),old):raise ValueError('Predecessor release asset mismatch')
   if new['file'] in published:
    if not verify_asset(published[new['file']],new):raise ValueError('Existing successor differs')
    print(json.dumps({'pass':True,'alreadyPublished':True,'catalogActivated':False}));return
   with urllib.request.urlopen(r['oldURL'],timeout=180) as response,source.open('xb') as dst:
    for part in iter(lambda:response.read(1048576),b''):dst.write(part)
  build(r,source,target)
  if a.test_local:print(json.dumps({'pass':True,'sha256':new['sha256'],'localOnly':True}));return
  if current()['packs']['id']!=old:raise ValueError('Public Indonesian pack changed before upload')
  gh('release','upload',TAG,str(target),'--repo',REPO)
  asset=assets().get(new['file'])
  if not verify_asset(asset,new) or asset.get('browser_download_url')!='https://github.com/'+REPO+'/releases/download/'+TAG+'/'+new['file']:raise ValueError('Uploaded asset did not verify')
  print(json.dumps({'pass':True,'published':new['file'],'sha256':new['sha256'],'catalogActivated':False,'historicAssetsRetained':True}))
if __name__=='__main__':main()
