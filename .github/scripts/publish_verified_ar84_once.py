"""One-time release of the exact independently checked Arabic book pair."""
from pathlib import Path
import copy,hashlib,json,os,shutil,subprocess,sys
root=Path.cwd().resolve();sys.path.insert(0,str(root/'books'))
from published_library import read,sha,capture,current,limited_continuity,scope_key,merge,stage
from automatic_publication import run,ensure_main,managed_paths
from download_page import publish_bundles,write_catalog
from download_tables import release_url
from check_outputs import require_complete_references
from word_layout_check import verify_pair

REPO='blaghtayt-alt/iman-companion'
SOURCE='f230cbe1f7ca1e328b63bbbe77646602fcff4d72'
TAG='arabic-reflections-84-20261107'
DOC='Iman_Companion_ar_tadabbur-extended.docx'
PDF='Iman_Companion_ar_tadabbur-extended.pdf'
EXPECTED_DOC='6277c6bc29a8c32ba8533c8a743d7d7a778291a8dc11cd61a3b9d265ec2338e6'
EXPECTED_PDF='c3fefca174fe94b4096ebfb6511ece1b402b5369f0a44c0b9a7e0c043f3638ab'
EXPECTED_MANIFEST='f9414503e158144dc9907ca79ca703a62834dd72548e171b2bdec955324e530d'
INDEX_SHA='46d4d6651fa3b7a16b2c6f95051fbffd6abf2f9f3a643914d7cd7a551aec6cc8'
SNAPSHOT_SHA='996e6357915856e9515328a9cebea5de237a2c2860dadddbfb65ce5ef20c294b'
CANDIDATE=Path(os.environ['AR84_CANDIDATE']).resolve()
OUT=Path(os.environ['RUNNER_TEMP']).resolve()/'ar84-manual-release'
HEAD=os.environ['GITHUB_SHA']

def file_hash(path,expected):
 if not path.is_file() or sha(path.read_bytes())!=expected:raise ValueError('Verified release input changed: '+path.name)

def draft(tag):
 for page in range(1,101):
  rows=json.loads(run(['gh','api',f'repos/{REPO}/releases?per_page=100&page={page}'],root));found=[r for r in rows if r.get('tag_name')==tag and r.get('draft') is True]
  if len(found)>1:raise ValueError('Duplicate release draft')
  if found:return found[0]
  if len(rows)<100:break
 raise ValueError('Release draft missing')

def main():
 ensure_main(root,HEAD)
 if run(['git','diff','--cached','--name-only'],root).strip():raise ValueError('Unexpected staged changes')
 run(['git','merge-base','--is-ancestor',SOURCE,HEAD],root)
 run([sys.executable,'books/index_units.py','--root',root,'--commit',SOURCE,'--language','ar','--collection','tadabbur-extended'],root)
 if read(root/'books/manifest.json')!=read(CANDIDATE/'source-manifest.json'):raise ValueError('Regenerated source manifest differs')
 for name,digest in [(DOC,EXPECTED_DOC),(PDF,EXPECTED_PDF),('index.json',INDEX_SHA),('library-snapshot.json',SNAPSHOT_SHA),('source-manifest.json',EXPECTED_MANIFEST), (DOC+'.reader-checks.json','e5afbda7863d18522eaf7cd420ca72444926d34ffb525c60fcaba5e54df75d5b'),(DOC+'.word-layout.json','8c895f6c500c3079974b98d5e027e74f6b59467521ef9a40ba3f3172c745c8ed')]:file_hash(CANDIDATE/name,digest)
 index=read(CANDIDATE/'index.json');book=index['books'][0]
 if index.get('sourceCommit')!=SOURCE or index.get('previewOnly') is not False or len(index['books'])!=1 or scope_key(book)!=('ar','tadabbur-extended') or book.get('sha256')!=EXPECTED_DOC or book.get('pdfSha256')!=EXPECTED_PDF or book.get('exportVerified') is not True or len(book.get('units',[]))!=84 or book.get('pages')!=3041 or book.get('wordPages')!=3128:raise ValueError('Candidate scope or format checks differ')
 require_complete_references(book)
 verified=verify_pair(CANDIDATE/DOC,CANDIDATE/PDF,'ar')
 if verified['word']['matchedEntries']!=84 or verified['pdf']['matchedEntries']!=84 or verified['pdf']['visibleLabelsMatched']!=84:raise ValueError('Contents or final Word checks differ')
 snap=capture(root,index);saved=read(CANDIDATE/'library-snapshot.json')
 if snap!=saved or len(snap['entries'])!=1 or not current(root,snap['entries'][0]):raise ValueError('Candidate source binding differs')
 existing=read(root/'books/published-library.json');before={scope_key(e['book']):e for e in existing['entries']}
 if len(before)!=20 or ('ar','tadabbur-extended') not in before or any(not(current(root,e) or limited_continuity(root,e)) for e in existing['entries']):raise ValueError('Prior book inventory is not preserved')
 oldbundles=read(root/'books/published-bundles.json');OUT.mkdir(parents=True,exist_ok=False);folder=OUT/'ar-tadabbur-extended';folder.mkdir()
 for name in [DOC,PDF]:shutil.copyfile(CANDIDATE/name,folder/name)
 ensure_main(root,HEAD)
 probe=subprocess.run(['gh','api',f'repos/{REPO}/releases/tags/{TAG}'],cwd=root,capture_output=True,text=True,encoding='utf8')
 if probe.returncode==0:
  release=json.loads(probe.stdout)
  if release.get('tag_name')!=TAG or release.get('target_commitish')!=SOURCE or release.get('draft') is not False or release.get('prerelease') is not False:raise ValueError('Existing release identity differs')
 else:
  if '404' not in probe.stderr:raise ValueError('Cannot check existing release: '+probe.stderr[-500:])
  run(['gh','release','create',TAG,'--repo',REPO,'--target',SOURCE,'--draft','--latest=false','--title','Reviewed Arabic reflections: 84 current sections','--notes','Arabic reflections cover 84 sections: 59 include all ayah numbers, and 25 contain selected ayahs. Material for 30 surahs is not prepared. This is not a complete Quran edition.'],root)
  for name in [DOC,PDF]:run(['gh','release','upload',TAG,folder/name,'--repo',REPO],root)
  release=draft(TAG)
 remote={a['name']:a for a in release.get('assets',[])}
 if set(remote)!={DOC,PDF}:raise ValueError('Release asset set differs')
 for name,digest in [(DOC,EXPECTED_DOC),(PDF,EXPECTED_PDF)]:
  x=remote[name]
  if x.get('state')!='uploaded' or x.get('size')!=(folder/name).stat().st_size or x.get('digest')!='sha256:'+digest:raise ValueError('Release bytes differ: '+name)
 if release.get('draft') is True:
  ensure_main(root,HEAD);run(['gh','release','edit',TAG,'--repo',REPO,'--draft=false','--latest=false'],root)
 incoming=copy.deepcopy(snap['entries'][0]);incoming['releaseTag']=TAG;incoming['book']['download']=release_url(REPO,TAG,DOC);incoming['book']['pdfDownload']=release_url(REPO,TAG,PDF)
 fetch=lambda tag:json.loads(run(['gh','api',f'repos/{REPO}/releases/tags/{tag}'],root))
 library,ready,stale=merge(root,existing,[incoming],REPO,fetch);after={scope_key(e['book']):e for e in library['entries']}
 if stale or len(ready)!=20 or set(after)!=set(before):raise ValueError('Existing book inventory changed')
 for k,v in before.items():
  if k==('ar','tadabbur-extended'):continue
  if any(after[k].get(field)!=value for field,value in v.items()) or set(after[k])-set(v)-{'availability'}:raise ValueError('Existing book entry changed: '+str(k))
 links,errors=publish_bundles(root,OUT,ready,SOURCE,REPO,TAG,run)
 if errors or len(links)!=20:raise ValueError('Combined book checks failed: '+str(errors))
 newbundles=read(root/'books/published-bundles.json')
 if any(oldbundles['languages'][l]!=newbundles['languages'][l] for l in oldbundles['languages'] if l!='ar'):raise ValueError('Another language bundle changed')
 stage(root,library,ready,REPO);catalog=write_catalog(root,OUT,ready,links);ar=catalog['languages']['ar']['books']
 if len(ar)!=1 or ar[0]['units']!=84 or ar[0]['sha256']!=EXPECTED_DOC or ar[0]['pdfSha256']!=EXPECTED_PDF:raise ValueError('Arabic catalog differs from verified pair')
 ensure_main(root,HEAD);files=[p for p in managed_paths(root) if (root/p).is_file()];run(['git','add','--',*files],root);changed=run(['git','diff','--cached','--name-only'],root).splitlines()
 if not changed or not set(changed).issubset(set(files)):raise ValueError('Unexpected publication files')
 run(['git','config','user.name','github-actions[bot]'],root);run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],root);run(['git','commit','-m','Publish verified Arabic reflection book'],root);run(['git','push','origin','HEAD:refs/heads/main'],root)
 print(json.dumps({'published':True,'tag':TAG,'sourceCommit':SOURCE,'units':84,'priorOtherBooksPreserved':19,'docx':incoming['book']['download'],'pdf':incoming['book']['pdfDownload'],'bundle':links['ar']['zip']}))
if __name__=='__main__':main()
