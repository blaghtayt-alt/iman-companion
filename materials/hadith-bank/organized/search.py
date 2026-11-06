#!/usr/bin/env python3
"""Browse public source and authored topic metadata."""
import argparse, hashlib, json, pathlib, re, sys, unicodedata, urllib.request
HERE=pathlib.Path(__file__).resolve().parent
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')

def load(path):
 with path.open(encoding='utf-8') as f:return json.load(f)
def norm(value):
 return ''.join(c for c in unicodedata.normalize('NFKD',str(value)).casefold() if not unicodedata.combining(c))
def output(value): print(json.dumps(value,ensure_ascii=False,indent=2))
def main():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--index',type=pathlib.Path,default=HERE/'INDEX.json'); sub=p.add_subparsers(dest='action',required=True)
 s=sub.add_parser('search'); s.add_argument('query',nargs='?',default=''); s.add_argument('--kind',choices=['package','reading','source','reference','lesson','chapter']); s.add_argument('--language'); s.add_argument('--chapter'); s.add_argument('--collection'); s.add_argument('--status'); s.add_argument('--surah',type=int); s.add_argument('--mode'); s.add_argument('--content-kind'); s.add_argument('--limit',type=int,default=20)
 r=sub.add_parser('resolve',help='Fetch a pinned published source and resolve a JSON pointer.'); r.add_argument('id'); r.add_argument('--pointer',default=None,help='RFC 6901 pointer within the referenced JSON; for a source record, defaults to its indexed object.');r.add_argument('--reading',action='store_true',help='Resolve the package or reading JSON rather than its source record.')
 args=p.parse_args(); pub=load(args.index)
 datasets=[('package',pub['packages']),('reading',pub['readingsOnly']),('source',pub['sourceRecords']),('reference',pub['quranCitationKeys']),('chapter',pub['chapters']),('lesson',pub['lessons'])]
 if args.action=='search':
  found=[]
  for typ,rows in datasets:
   if args.kind and args.kind!=typ:continue
   for item in rows:
    # Searching the serialized metadata covers titles, references, grades, links and recorded review states.
    text=norm(json.dumps(item,ensure_ascii=False));
    if any(norm(t) not in text for t in args.query.split()):continue
    if args.language and norm(args.language)!=norm(item.get('language','')) and not any(norm(args.language)==norm(n.get('language','')) for n in item.get('nativePublications',[])):continue
    if args.chapter and norm(args.chapter) not in norm(item.get('chapterId',item.get('lessonId',item.get('id','')))):continue
    if args.collection and norm(args.collection) not in norm(item.get('sourceBook','')) and norm(args.collection) not in norm(item.get('metadata',{})):continue
    if args.status and norm(args.status) not in text:continue
    if args.content_kind and item.get('contentKind')!=args.content_kind:continue
    if args.surah is not None and not any(o.get('surah')==args.surah for o in item.get('occurrences',[])):continue
    if args.mode and not any(norm(o.get('mode',''))==norm(args.mode) for o in item.get('occurrences',[])):continue
    found.append({'kind':typ,'record':item})
  output({'count':len(found),'shown':min(len(found),max(args.limit,0)),'results':found[:max(args.limit,0)]});return
 # Resolve only a source locator already present in our public allowlist, never arbitrary URLs.
 match=next(((typ,x) for typ,rows in datasets for x in rows if x['id']==args.id),None)
 if not match: p.error('ID not found in the public index')
 typ,item=match; loc=item.get('locator',{})
 if typ=='source' and not args.reading:
  f=loc.get('envelope',loc.get('file')); member=loc.get('member'); expected=loc.get('memberSha256'); ptr=args.pointer if args.pointer is not None else loc.get('memberJsonPointer',loc.get('jsonPointer',''))
 elif typ=='package': f=item['locators']['reading']; member=None;ptr=args.pointer or ''
 elif typ=='reading': f=item['reading'];member=None;ptr=args.pointer or ''
 else: p.error('This record does not have a supported resolvable JSON locator')
 prefix='https://github.com/blaghtayt-alt/iman-companion/blob/'; url=f['url'];
 if not re.fullmatch(r'https://github[.]com/blaghtayt-alt/iman-companion/blob/[0-9a-f]{40}/materials/[A-Za-z0-9_./-]+',url) or '..' in url:raise ValueError('Unexpected public source origin or path')
 raw='https://raw.githubusercontent.com/blaghtayt-alt/iman-companion/'+url[len(prefix):]
 with urllib.request.urlopen(raw,timeout=40) as response:b=response.read(30000001)
 if len(b)>30000000:raise ValueError('Source exceeds size limit')
 if hashlib.sha256(b).hexdigest()!=f['sha256'] or len(b)!=f['bytes']:raise ValueError('Pinned source hash or length mismatch')
 obj=json.loads(b)
 if member:
  entries=[x for x in obj['files'] if x['name']==member]
  if len(entries)!=1:raise ValueError('Source member not unique')
  text=entries[0]['text'];
  if hashlib.sha256(text.encode('utf-8')).hexdigest()!=expected:raise ValueError('Member hash mismatch')
  obj=json.loads(text)
 if ptr and not ptr.startswith('/'):raise ValueError('JSON pointer must be empty or begin with /')
 for part in ptr.split('/')[1:] if ptr else []:
  key=part.replace('~1','/').replace('~0','~');obj=obj[int(key)] if isinstance(obj,list) else obj[key]
 output({'source':url,'verifiedSHA256':f['sha256'],'member':member,'pointer':ptr,'value':obj})
if __name__=='__main__':
 try:main()
 except (OSError,ValueError,KeyError,IndexError) as e:sys.exit('Error: '+str(e))
