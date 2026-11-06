#!/usr/bin/env python3
"""Generate a narrow English children At-Tin hold against a pinned public snapshot."""
from pathlib import Path
import argparse,hashlib,json
def digest(data):return hashlib.sha256(data).hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();source=args.source.resolve(strict=True);output=args.output.absolute();require(source.is_dir() and not args.source.is_symlink(),'Invalid source');require(not output.exists() and not output.is_symlink() and not output.resolve().is_relative_to(source),'Output must be new and outside source')
 contract=json.loads(Path(__file__).with_name('contract.json').read_bytes());rows={x['path']:x for x in contract['files']};names={'features109.js','runtime/scripts/content-audio-badge1036.js','runtime/scripts/content-audio-catalog1036.js','index.html','mobile.html','tablet.html'};require(set(rows)==names,'Unexpected patch paths');original={}
 for name,row in rows.items():
  p=source/name;require(p.resolve().is_relative_to(source) and not p.is_symlink() and p.is_file(),'Invalid source path '+name);raw=p.read_bytes();require(len(raw)==row['sourceBytes'] and digest(raw)==row['sourceSHA256'],'Public source changed: '+name);original[name]=raw
 def change(name,old,new):
  text=original[name].decode('utf8');require(text.count(old)==1,'Unexpected source: '+name);return text.replace(old,new).encode('utf8')
 outputs={}
 outputs['features109.js']=change('features109.js',".filter(x=>x.category===view);body=", ".filter(x=>x.category===view&&!(lang==='en'&&x.id==='at-tin'));body=")
 outputs['runtime/scripts/content-audio-badge1036.js']=change('runtime/scripts/content-audio-badge1036.js',".filter(x=>x.category===view),cards=", ".filter(x=>x.category===view&&!(lang==='en'&&x.id==='at-tin')),cards=")
 name='runtime/scripts/content-audio-catalog1036.js';prefix='window.IMAN_APPROVED_CONTENT_AUDIO1036=';text=original[name].decode('utf8');require(text.startswith(prefix),'Unexpected audio catalog');catalog=json.loads(text[len(prefix):].rstrip(';\r\n'));removed=[x for x in catalog['entries'] if x.get('id')=='kids:at-tin' and x.get('language')=='en'];require(len(removed)==1 and removed[0].get('kind')=='lesson','Unexpected English At-Tin approvals');catalog['entries']=[x for x in catalog['entries'] if not(x.get('id')=='kids:at-tin' and x.get('language')=='en')];outputs[name]=(prefix+json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+';\n').encode('utf8')
 for name in ['index.html','mobile.html','tablet.html']:
  text=original[name].decode('utf8')
  for asset in ['features109.js','runtime/scripts/content-audio-badge1036.js','runtime/scripts/content-audio-catalog1036.js']:
   old=asset+'?v='+digest(original[asset])[:12];new=asset+'?v='+digest(outputs[asset])[:12];require(text.count(old)==1,'Unexpected entry-page reference: '+name);text=text.replace(old,new)
  outputs[name]=text.encode('utf8')
 for name,raw in outputs.items():require(len(raw)==rows[name]['targetBytes'] and digest(raw)==rows[name]['targetSHA256'],'Output mismatch: '+name)
 output.mkdir(parents=True,exist_ok=False)
 for name,raw in outputs.items():
  p=output/name;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb') as f:f.write(raw)
 print(json.dumps({'status':'generated-and-verified','files':len(outputs),'heldLesson':'at-tin','language':'en','approvalEntriesHeld':1}))
if __name__=='__main__':main()
