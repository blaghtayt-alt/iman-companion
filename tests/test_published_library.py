"""Algorithm-only fixtures: these byte strings are not books or publication proof."""
from pathlib import Path
from copy import deepcopy
import tempfile,sys,json
W=Path(__file__).resolve().parents[1];sys.path.insert(0,str(W/'books'))
from published_library import *
checks=[]
def rejects(label,fn):
 try:fn()
 except ValueError:checks.append(label);return
 raise AssertionError(label)
with tempfile.TemporaryDirectory(prefix='library-fixture-',dir=W) as temp:
 root=Path(temp);(root/'books').mkdir();(root/'materials').mkdir()
 conf=read(W/'books/config.json'); registry={'schema':'iman-material-audio-v1','entries':[]}; registry_raw=(json.dumps(registry)+'\n').encode(); (root/'materials/audio').mkdir(); (root/'materials/audio/registry.json').write_bytes(registry_raw); conf['audioRegistry']={'path':'materials/audio/registry.json','sha256':sha(registry_raw)}
 (root/'books/config.json').write_text(json.dumps(conf,ensure_ascii=False),encoding='utf8');(root/'README.md').write_text('# Fixture\n',encoding='utf8')
 catalog={'entries':[]};declarations={'schema':'iman-reviewed-books-v1','books':[]}
 def write_json(rel,data):
  p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
 def candidate(collection,ident,title,tag):
  source=f'materials/{collection}-{ident}.txt';(root/source).write_text(title,encoding='utf8')
  catalog['entries'].append({'collection':collection,'language':'ar','id':ident,'markdown':source,'status':'published'})
  declarations['books'].append({'language':'ar','collection':collection,'state':'reviewed-current','automaticBuild':True,'automaticRelease':True})
  write_json('materials/catalog.json',catalog);write_json('books/reviewed-books.json',declarations)
  unit={'id':ident,'readerTextSHA256':sha(title.encode()),'sourceHashes':['a'*64],'inputBindings':[{'path':source,'sha256':sha(title.encode())}]}
  unit_path=f'books/units/{collection}-{ident}.json';write_json(unit_path,unit)
  commit='c'*40;write_json('books/manifest.json',{'sourceCommit':commit,'previewOnly':False,'units':[{'language':'ar','collection':collection,'path':unit_path,'sha256':sha((root/unit_path).read_bytes())}]})
  book={'language':'ar','collection':collection,'file':f'Iman_Companion_ar_{collection}.docx','sourceCommit':commit,'units':[unit],'exportVerified':True,'previewOnly':False,'sha256':sha(b'word-fixture'),'pdfSha256':sha(b'pdf-fixture')}
  index={'sourceCommit':commit,'previewOnly':False,'books':[book]}
  data=capture(root,index);entry=data['entries'][0];entry['releaseTag']=tag;return entry,index
 article,index=candidate('articles','article-1','مقالة','books-fixture-1')
 seerah,_=candidate('seerah','seerah-1','السيرة','books-fixture-2')
 def release(entry):
  tag=entry['releaseTag'];book=entry['book'];return {'tag_name':tag,'draft':False,'prerelease':False,'assets':[{'name':n,'state':'uploaded','size':12,'digest':'sha256:'+book[k],'browser_download_url':release_url('example/fixture',tag,n)} for n,k in asset_names(book)]}
 remote={e['releaseTag']:release(e) for e in [article,seerah]}
 existing={'schema':SCHEMA,'entries':[article]}
 library,ready,stale=merge(root,existing,[seerah],'example/fixture',remote.__getitem__)
 assert len(ready)==2 and not stale;checks.append('Adding one scoped book preserves a verified book from an earlier release')
 stage(root,library,ready,'example/fixture');table=(root/'README.md').read_text(encoding='utf8')
 assert all(e['releaseTag'] in table for e in [article,seerah]);assert len(list((root/'books/downloads').glob('*/README.md')))==20;checks.append('Merged root table and all 20 native pages use immutable per-book release URLs')
 # A newly published audio identity changes only its matching book scope.
 audio_path=root/'materials/audio/registry.json';old_audio=audio_path.read_bytes();old_conf=deepcopy(conf)
 updated_audio={'schema':'iman-material-audio-v1','entries':[{'materialId':'seerah-1','language':'ar','collection':'seerah','status':'published','sourceSHA256':'a'*64,'audioSHA256':'b'*64}]};audio_raw=(json.dumps(updated_audio)+'\n').encode();audio_path.write_bytes(audio_raw);conf['audioRegistry']['sha256']=sha(audio_raw);write_json('books/config.json',conf)
 isolated,ready,stale=merge(root,library,[],'example/fixture',remote.__getitem__)
 assert set(ready)=={('ar','articles')} and stale==[('ar','seerah')];checks.append('Unrelated article book survives a newly published Seerah audio identity')
 audio_path.write_bytes(old_audio);conf=old_conf;write_json('books/config.json',conf)
 # A purely additive item retains the exact checked earlier edition, labeled
 # with its real included units while the replacement is awaiting release QC.
 catalog['entries'].append({'collection':'seerah','language':'ar','id':'seerah-2','status':'published'});write_json('materials/catalog.json',catalog)
 current_library,ready,stale=merge(root,library,[],'example/fixture',remote.__getitem__)
 assert set(ready)=={('ar','articles'),('ar','seerah')} and not stale and ready[('ar','seerah')]['availability']['newMaterialsIncluded'] is False;checks.append('Additive material preserves a truthful limited earlier edition until replacement passes')
 rejects('A stale new candidate cannot be published',lambda:merge(root,existing,[seerah],'example/fixture',remote.__getitem__))
 catalog['entries'].pop();write_json('materials/catalog.json',catalog)
 tampered=deepcopy(remote);tampered[article['releaseTag']]['assets'][0]['digest']='sha256:'+'0'*64
 rejects('Actual release asset digest must match final checked Word/PDF',lambda:merge(root,existing,[],'example/fixture',tampered.__getitem__))
 bad=deepcopy(seerah);bad['book']['previewOnly']=True
 rejects('Review-only artifacts never become downloads',lambda:merge(root,existing,[bad],'example/fixture',remote.__getitem__))
 rejects('Duplicate incoming scopes cannot replace each other silently',lambda:merge(root,existing,[seerah,seerah],'example/fixture',remote.__getitem__))
 bad=deepcopy(article);bad['book']['collection']='combined'
 rejects('Personal combined edition cannot enter public library',lambda:merge(root,{'schema':SCHEMA,'entries':[bad]},[],'example/fixture',remote.__getitem__))
 tampered=deepcopy(remote);tampered[article['releaseTag']]['draft']=True
 rejects('Draft release cannot be advertised as downloadable',lambda:merge(root,existing,[],'example/fixture',tampered.__getitem__))
 # Revocation removes the current row even when there are no successful new builds.
 declarations['books'][0]['automaticRelease']=False;write_json('books/reviewed-books.json',declarations)
 lib,ready,stale=merge(root,existing,[],'example/fixture',remote.__getitem__);assert not ready and stale==[('ar','articles')];checks.append('Withdrawn publication declaration removes links without needing a replacement build')
assert len(checks)>=10
print(json.dumps({'passedChecks':len(checks)}))
