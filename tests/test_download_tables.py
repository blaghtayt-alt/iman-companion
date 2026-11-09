from pathlib import Path
from copy import deepcopy
import sys,json,tempfile,hashlib,re,subprocess,shutil
P=Path(__file__).resolve().parents[1];W=P.parent;sys.path.insert(0,str(P/'books'))
from download_tables import render,merge_readme,MARKER_START,MARKER_END,verified_books,COLLECTIONS
from prepare_readme import prepare
from bibliography import native_text
conf=json.loads((P/'books/config.json').read_text(encoding='utf-8'));results=[];sha=lambda b:hashlib.sha256(b).hexdigest()
def passed(name):results.append({'check':name,'passed':True})
def rejects(name,fn):
 try:fn()
 except ValueError:passed(name);return
 raise AssertionError('Did not reject '+name)
with tempfile.TemporaryDirectory(dir=W,prefix='download-table-test-') as tmp:
 root=Path(tmp);folder=root/'dist';folder.mkdir();(root/'books').mkdir();(root/'books/config.json').write_text(json.dumps(conf,ensure_ascii=False),encoding='utf-8')
 original=(P/'test-fixtures/SOURCE-README.md').read_text(encoding='utf-8');(root/'README.md').write_text(original,encoding='utf-8')
 books=[]
 for lang in conf['languages']:
  for collection in COLLECTIONS:
   file=f'fixture_{lang}_{collection}.docx';word=(lang+collection+'word fixture only').encode();pdf=(lang+collection+'pdf fixture only').encode();(folder/file).write_bytes(word);(folder/Path(file).with_suffix('.pdf')).write_bytes(pdf)
   books.append({'language':lang,'collection':collection,'file':file,'sha256':sha(word),'pdfSha256':sha(pdf),'exportVerified':True,'hadithEdition':'new-extended','units':[{'id':'fixture-only'}]})
 index={'sourceCommit':'test-source','previewOnly':False,'books':books};(folder/'index.json').write_text(json.dumps(index),encoding='utf-8')
 table,pages=render(conf,index,folder,'example/fixture','test-only')
 assert len(pages)==20 and table.count('/releases/download/')==160;passed('20 languages and 80 Word/PDF pairs')
 for lang,page in pages.items():
  assert page.count('/releases/download/')==8
  for line in page.splitlines():native_text(re.sub(r'\]\([^)]*\)',']',line),lang)
 passed('All native language page labels contain no English fallback')
 updated=merge_readme(original,table);assert merge_readme(updated,table)==updated;assert updated.count(MARKER_START)==updated.count(MARKER_END)==1;passed('README insertion is idempotent')
 outside=updated.replace(MARKER_START+'\n'+table.rstrip()+'\n'+MARKER_END,'')
 for anchor in ['## Start here','## Using the material','## Where the material comes from','## Articles','## Current Al-Ikhlas reflections']:
  assert anchor in outside
 assert 'language-packs-2026-10-24-alp-pages-10-19' in outside;passed('Existing repository sections and old pack links preserved')
 x=deepcopy(index);x['books'][0]['exportVerified']=False;assert len(verified_books(x,folder,'example/fixture','test-only'))==79;passed('Unverified book has no download links')
 x=deepcopy(index);x['previewOnly']=True;assert not verified_books(x,folder,'example/fixture','test-only');passed('Internal preview never becomes a library download')
 x=deepcopy(index);del x['previewOnly'];assert not verified_books(x,folder,'example/fixture','test-only');passed('Missing production declaration cannot expose downloads')
 x=deepcopy(index);x['books'][0]['language']='unknown';rejects('Unknown download language',lambda:render(conf,x,folder,'example/fixture','test-only'))
 x=deepcopy(index);x['books'][0]['file']='fixture.pdf';rejects('Non-Word editable asset',lambda:render(conf,x,folder,'example/fixture','test-only'))
 x=deepcopy(index);x['books'][1]['hadithEdition']='legacy-short';rejects('Legacy short Hadith download',lambda:render(conf,x,folder,'example/fixture','test-only'))
 x=deepcopy(index);x['books'][0]['collection']='combined';rejects('Non-public book cannot become a public download',lambda:render(conf,x,folder,'example/fixture','test-only'))
 assert table.count('### ')==1 and all(len([line for line in page.splitlines() if line.startswith('| ')])==6 for page in pages.values());passed('Only four public collections appear in every language')
 from build_books import build_book
 rejects('Non-public book cannot be built by public builder',lambda:build_book(None,None,None,None,'combined',None,None))
 blocked=root/'blocked-release';blocked.mkdir();(blocked/'index.json').write_text(json.dumps({'books':[{'collection':'combined'}]}),encoding='utf-8')
 run=subprocess.run([sys.executable,str(P/'books/check_outputs.py'),'--folder',str(blocked),'--tag','test-only','--repo','example/fixture'],capture_output=True,text=True)
 assert run.returncode!=0 and 'Only public collection books' in run.stderr;passed('Non-public book cannot be checked for release')
 from check_outputs import public_export_inputs
 expected=root/'expected-public';expected.mkdir();(expected/'book.docx').write_bytes(b'test');(expected/'book.pdf').write_bytes(b'test')
 public_export_inputs({'books':[{'collection':'hadith','file':'book.docx'}]},expected);passed('Indexed public Word and PDF pair is accepted')
 (blocked/'index.json').write_text(json.dumps({'books':[]}),encoding='utf-8');(blocked/'unindexed.pdf').write_bytes(b'private fixture')
 run=subprocess.run([sys.executable,str(P/'books/check_outputs.py'),'--folder',str(blocked),'--tag','test-only','--repo','example/fixture'],capture_output=True,text=True)
 assert run.returncode!=0 and 'Unindexed or missing' in run.stderr;passed('Unindexed files cannot enter the public release')
 target=folder/Path(books[0]['file']).with_suffix('.pdf');saved=target.read_bytes();target.write_bytes(b'changed')
 rejects('Changed PDF asset',lambda:render(conf,index,folder,'example/fixture','test-only'));target.write_bytes(saved)
 x=deepcopy(index);x['books'].append(x['books'][0]);rejects('Duplicate book cell',lambda:render(conf,x,folder,'example/fixture','test-only'))
 x=deepcopy(index);x['books']=x['books'][:1];partial,_=render(conf,x,folder,'example/fixture','test-only');assert partial.count('/releases/download/')==2;passed('Missing books remain plain status text, without fake links')
 rejects('Unmatched README markers',lambda:merge_readme(original+'\n'+MARKER_START,table))
 assert prepare(root,folder,'example/fixture','test-only','test-source')==20
 assert len(list((root/'books/downloads').glob('*/README.md')))==20;passed('Root README and 20 native pages prepared together')
 rejects('Wrong source checkout',lambda:prepare(root,folder,'example/fixture','test-only','wrong-source'))
 x=deepcopy(index);x['previewOnly']=True;(folder/'index.json').write_text(json.dumps(x));rejects('Publishing formatting preview as full library',lambda:prepare(root,folder,'example/fixture','test-only','test-source'))
 # Use actual source-bound internal lesson units plus an archive record to test eligibility.
 fixture=P/'test-fixtures/extended';checkroot=root/'catalog-check'
 for rel in ['materials/hadith/essential-ar/01/001.json','materials/hadith/essential-ar/01/002.json','books/units/current/ar/essential-01-001.json','books/units/current/ar/essential-01-002.json']:
  dest=checkroot/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(fixture/rel,dest)
 # Restore the exact fixture bytes only when Windows checkout newline conversion is detectable.
 for n in ['001','002']:
  unit=json.loads((checkroot/f'books/units/current/ar/essential-01-{n}.json').read_text(encoding='utf-8'))
  source=checkroot/unit['inputBindings'][0]['path'];data=source.read_bytes();expected=unit['inputBindings'][0]['sha256']
  if sha(data)!=expected and sha(data.replace(b'\r\n',b'\n'))==expected:source.write_bytes(data.replace(b'\r\n',b'\n'))
 cat=json.loads((fixture/'materials/catalog.json').read_text(encoding='utf-8'));cat['entries'].append({'collection':'seerah','language':'ar','id':'23','status':'source-archive','json':'materials/seerah/ar/source-archive/chapter-23.json'})
 (checkroot/'materials/catalog.json').write_text(json.dumps(cat,ensure_ascii=False),encoding='utf-8')
 run=subprocess.run([sys.executable,str(P/'books/index_units.py'),'--root',str(checkroot),'--commit','test-source'],capture_output=True,text=True)
 assert run.returncode==0,run.stderr
 m=json.loads((checkroot/'books/manifest.json').read_text(encoding='utf-8'));assert len(m['units'])==2 and m['previewOnly'] is True;passed('Source archives excluded and sample catalogue flagged as preview')
 # Scope coverage to one actual language and collection, without accepting partial groups.
 cat['entries'].append({'collection':'seerah','language':'ar','id':'unreconciled','status':'published','json':'materials/seerah/unreviewed.json'})
 (checkroot/'materials/catalog.json').write_text(json.dumps(cat,ensure_ascii=False),encoding='utf-8')
 command=[sys.executable,str(P/'books/index_units.py'),'--root',str(checkroot),'--commit','test-source']
 run=subprocess.run(command+['--language','ar','--collection','hadith'],capture_output=True,text=True)
 m=json.loads((checkroot/'books/manifest.json').read_text(encoding='utf-8'))
 assert run.returncode==0 and m['previewOnly'] is True and len(m['units'])==2 and m['scope']=={'language':'ar','collection':'hadith'};passed('An unrelated collection does not block the selected group')
 run=subprocess.run(command,capture_output=True,text=True);assert run.returncode!=0 and 'lack book reader units' in run.stderr;passed('Unscoped indexing checks every eligible group')
 cat['entries'].append({'collection':'essential-hadith','language':'ar','id':'missing','json':'missing.json'})
 (checkroot/'materials/catalog.json').write_text(json.dumps(cat,ensure_ascii=False),encoding='utf-8')
 run=subprocess.run(command+['--language','ar','--collection','hadith'],capture_output=True,text=True);assert run.returncode!=0 and 'lack book reader units' in run.stderr;passed('Missing selected-group unit blocks that group')
 cat['entries'].pop();run=subprocess.run(command+['--language','ar'],capture_output=True,text=True);assert run.returncode!=0 and 'Select a language and collection together' in run.stderr;passed('Incomplete scope selection is rejected')
 # A production-shaped catalogue cannot bypass reconciliation merely by supplying units.
 cat['languages']={'ar':'Arabic'};cat['scope']='production';(checkroot/'materials/catalog.json').write_text(json.dumps(cat,ensure_ascii=False),encoding='utf-8')
 run=subprocess.run([sys.executable,str(P/'books/index_units.py'),'--root',str(checkroot),'--commit','test-source'],capture_output=True,text=True)
 assert run.returncode!=0 and 'Production indexing held' in run.stderr;passed('Production indexing held until current catalogue reconciliation')
 run=subprocess.run(command+['--language','ar','--collection','hadith'],capture_output=True,text=True)
 assert run.returncode!=0 and 'Production indexing held' in run.stderr;passed('Scoped indexing cannot bypass production review')
receipt={'passedChecks':len(results),'results':results,'scope':'Download table generation, actual staged-asset hash guards, README preservation, native labels and source archive eligibility. Synthetic byte fixtures only test link generation; no books or online changes were made by these tests.'}
(P/'DOWNLOAD-TABLE-VERIFICATION.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passedChecks':len(results)}))
