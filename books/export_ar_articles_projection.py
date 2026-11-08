"""Export exact current Arabic reader data alongside a reviewed source publication.

This accepts the structured app reader as the semantic authority and requires
its identities and visible content to match the public catalog/index/Markdown.
It never infers quotation roles or approves sources.
"""
from pathlib import Path
import argparse,hashlib,json,re
from bibliography import native_text
def current_record(row):
    retired={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
    return not row.get('archived') and row.get('current',True) is not False and not any(str(row.get(k,'')).lower() in retired for k in ('status','publicationStatus','translationStatus'))
def visible_markdown(text):return re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)

PREFIX='window.IMAN_ARTICLE_REPLACEMENTS982_DATA='
def sha(data):return hashlib.sha256(data).hexdigest()
def export(root,reader_file):
    raw=reader_file.read_bytes();text=raw.decode('utf8')
    if not text.startswith(PREFIX):raise ValueError('Unexpected current Arabic article reader')
    reader=json.loads(text[len(PREFIX):].rstrip(';\r\n'))
    if reader.get('schema')!='arabic-article-replacements982-v1' or reader.get('language')!='ar':raise ValueError('Unexpected article reader schema')
    index_path=root/'materials/articles/prepared-ar/index.json';index=json.loads(index_path.read_bytes())
    catalog=json.loads((root/'materials/catalog.json').read_bytes())
    rows=[x for x in catalog['entries'] if x.get('collection')=='articles' and x.get('language')=='ar' and x.get('translationStatus')=='supplied-arabic-current' and current_record(x)]
    active=[x for x in index['articles'] if current_record(x)]
    sources={x['id']:x for x in reader['articles']};indexed={x['id']:x for x in active};entries={x['id']:x for x in rows}
    known={x['id'] for x in catalog['entries'] if x.get('collection')=='articles' and x.get('language')=='ar' and 'id' in x}
    if len(sources)!=len(reader['articles']) or len(indexed)!=len(active) or len(entries)!=len(rows) or not entries or not set(entries).issubset(sources) or not set(sources).issubset(known) or set(indexed)!=set(entries):raise ValueError('Reader, index and current catalog coverage differ')
    numbers=[x.get('number') or x.get('position') for x in rows]
    if any(not isinstance(n,int) or isinstance(n,bool) or n<1 for n in numbers) or len(set(numbers))!=len(numbers):raise ValueError('Invalid article order')
    output=[]
    for row in sorted(rows,key=lambda x:x.get('number') or x.get('position')):
        ident=row['id'];a=sources[ident];i=indexed[ident];number=row.get('number') or row.get('position')
        if (i.get('number') or i.get('position'))!=number or row.get('title')!=a.get('title') or i.get('title')!=a.get('title') or row.get('sourceHashes')!=[a.get('sourceSHA256')] or i.get('preparedSourceSHA256')!=a.get('sourceSHA256'):raise ValueError('Article identity changed: '+ident)
        relative=Path('materials/articles/prepared-ar')/i['path'];file=(root/relative).resolve()
        if not file.is_relative_to(index_path.parent.resolve()) or row.get('markdown')!=relative.as_posix() or row.get('index')!='materials/articles/prepared-ar/index.json':raise ValueError('Invalid article source path')
        material=file.read_bytes();body=material.decode('utf8').split('\n\n')
        heading=next((n for n,x in enumerate(body) if x.strip() in ('## المراجع','## مراجع الشواهد')),None)
        paragraphs=[{k:v for k,v in p.items() if k!='index'} for p in a['paragraphs']]
        if any(x.get('segments') and (''.join(s.get('text','') for s in x['segments'])!=x['text'] or any(s.get('href') and not re.match(r'^https?://',s['href']) for s in x['segments'])) for x in a['references']):raise ValueError('Invalid current reader reference spans: '+ident)
        refs=[{'id':x.get('id',''),'text':x['text'],'segments':[{'text':s['text'],**({'externalLink':True} if s.get('href') else {})} for s in x.get('segments',[])],**{key:x[key] for key in ('continuationOf','preservedIdentifiers') if key in x}} for x in a['references']]
        previous=None
        for ref in refs:
            if 'preservedIdentifiers' in ref:native_text(ref['text'],'ar',preserved_identifiers=ref['preservedIdentifiers'])
            if 'continuationOf' in ref:
                if ref['id'] or not isinstance(ref['continuationOf'],str) or not ref['continuationOf'] or previous!=ref['continuationOf']:raise ValueError('Invalid current reader reference continuation: '+ident)
            else:previous=ref['id'] or None
        if heading is None or body[0]!='# '+a['title'] or [re.sub(r'^## ','',x).strip('\n') for x in body[1:heading]]!=[x['text'] for x in paragraphs] or [('heading' if x.startswith('## ') else 'body') for x in body[1:heading]]!=[x['kind'] for x in paragraphs] or [visible_markdown(x).strip() for x in body[heading+1:] if x.strip()]!=[x['text'].strip() for x in refs]:raise ValueError('Published Markdown differs from current reader: '+ident)
        if any(p.get('kind') not in {'heading','body'} or not p.get('segments') or any(s.get('role') not in {'plain','quran','hadith','scholar'} for s in p['segments']) or ''.join(s.get('text','') for s in p['segments'])!=p['text'] for p in paragraphs):raise ValueError('Invalid reader spans: '+ident)
        reading=sha((a['title']+'\n\n'+'\n\n'.join(p['text'] for p in paragraphs)).encode('utf8'))
        if reading!=i.get('readingSHA256') or reading!=row.get('readingSHA256') or a.get('reading')!=a['title']+'\n\n'+'\n\n'.join(p['text'] for p in paragraphs):raise ValueError('Published reading differs from current reader: '+ident)
        output.append({'id':ident,'title':a['title'],'number':number,'sourceSHA256':a['sourceSHA256'],'readingSHA256':reading,'paragraphs':paragraphs,'references':refs,'materialSHA256':sha(material)})
    return {'schema':'iman-reviewed-article-projection-v1','language':'ar','collection':'articles','scope':'Public supplied articles; exact current reader bodies and supplied reference lists. No new scholarly approval.','canonicalReaderSHA256':sha(raw),'articles':output}
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--reader-data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    result=export(args.root.resolve(),args.reader_data.resolve());args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'publishedReaderArticles':len(result['articles']),'sha256':sha(args.out.read_bytes())}))
if __name__=='__main__':main()
