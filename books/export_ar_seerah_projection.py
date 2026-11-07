"""Export the currently published Arabic Seerah reader structure without changing it.

Run at the source-publication step with the exact current app reader data and
the checked-out public index/readings. It refuses incomplete or different text.
"""
from pathlib import Path
import argparse,hashlib,json
PREFIX='window.IMAN_NEW_ADULT_SEERAH_AR='
def sha(raw):return hashlib.sha256(raw).hexdigest()
def export(root,reader_file):
    text=reader_file.read_text(encoding='utf8')
    if not text.startswith(PREFIX):raise ValueError('Unexpected current Arabic Seerah reader data')
    reader=json.loads(text[len(PREFIX):].rstrip(';\r\n'))
    index_path=root/'materials/seerah/new-adult/ar/index.json';index=json.loads(index_path.read_bytes())
    if reader.get('schema')!='new-adult-seerah-ar-v1' or index.get('schema')!='new-adult-seerah-source-index-v1' or reader.get('language')!='ar' or index.get('language')!='ar':raise ValueError('Unexpected Seerah source schema')
    readers={x['id']:x for x in reader['chapters']};chapters=index['chapters'];ids=[x['id'] for x in chapters];numbers=[x['number'] for x in chapters]
    if len(readers)!=len(reader['chapters']) or len(set(ids))!=len(ids) or set(readers)!=set(ids) or len(set(numbers))!=len(numbers):raise ValueError('Reader and published Seerah coverage differ')
    out=[]
    for item in sorted(chapters,key=lambda x:x['number']):
        current=readers[item['id']];number=item['number']
        if not isinstance(number,int) or isinstance(number,bool) or number<1:raise ValueError('Invalid chapter number')
        if any(current.get(k)!=item.get(k) for k in ('id','number','title','sourceSHA256')):raise ValueError('Reader and published chapter identity differ')
        path=(index_path.parent/item['readingPath']).resolve()
        if not path.is_relative_to(index_path.parent.resolve()):raise ValueError('Invalid reading path')
        raw=path.read_bytes()
        if sha(raw)!=item['readingSHA256']:raise ValueError('Published chapter reading changed')
        paragraphs=current['paragraphs'];md=raw.decode('utf8').replace('\r\n','\n');expected='# '+item['title']+'\n\n'+'\n\n'.join(p['text'] for p in paragraphs)
        if md.strip()!=expected.strip():raise ValueError('Published chapter differs from current app reader')
        for p in paragraphs:
            if not p.get('segments') or any(s.get('role') not in {'plain','quran','hadith'} for s in p['segments']) or ''.join(s.get('text','') for s in p['segments'])!=p['text']:raise ValueError('Invalid current reader segment')
        out.append({'id':f'new-seerah{number:03d}','chapterId':item['id'],'number':number,'title':item['title'],'sourceSHA256':item['sourceSHA256'],'readingSHA256':item['readingSHA256'],'paragraphs':paragraphs})
    return {'schema':'iman-reviewed-seerah-projection-v1','language':'ar','collection':'seerah','edition':'new-adult','chapters':out}
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--reader-data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args();result=export(args.root.resolve(),args.reader_data.resolve());args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'publishedReaderChapters':len(result['chapters']),'sha256':sha(args.out.read_bytes())}))
if __name__=='__main__':main()
