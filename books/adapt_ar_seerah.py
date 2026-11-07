"""Create current Arabic Seerah book units from exact published/app-reader bindings."""
import hashlib,json
from pathlib import Path
from build_books import check_unit,inside
from adapt_ar_articles import current_record
def sha(raw):return hashlib.sha256(raw).hexdigest()
def generate(root,catalog,declaration):
    if (declaration.get('language'),declaration.get('collection'),declaration.get('adapter'),declaration.get('edition'))!=('ar','seerah','arabic-new-seerah-v1','new-adult'):raise ValueError('Unsupported Seerah source adapter')
    projection_path=inside(root,declaration['projection']);raw=projection_path.read_bytes()
    if sha(raw)!=declaration.get('projectionSHA256'):raise ValueError('Reviewed Seerah projection changed')
    projection=json.loads(raw)
    if (projection.get('schema'),projection.get('language'),projection.get('collection'),projection.get('edition'))!=('iman-reviewed-seerah-projection-v1','ar','seerah','new-adult'):raise ValueError('Unexpected Seerah projection')
    allrows=[e for e in catalog['entries'] if e.get('collection')=='seerah' and e.get('language')=='ar' and e.get('edition')=='new-adult'];rows=[e for e in allrows if current_record(e)];entries={e['id']:e for e in rows};reviewed=projection['chapters'];byid={a['id']:a for a in reviewed};known={e['id'] for e in allrows}
    if len(entries)!=len(rows) or len(byid)!=len(reviewed) or not entries or not set(entries).issubset(byid) or not set(byid).issubset(known):raise ValueError('Current Seerah coverage changed or is ambiguous')
    index_path=inside(root,declaration['materialIndex']);index=json.loads(index_path.read_bytes())
    if index.get('schema')!='new-adult-seerah-source-index-v1' or index.get('language')!='ar':raise ValueError('Unexpected Seerah index')
    current_index=[x for x in index['chapters'] if current_record(x)];indexed={x['id']:x for x in current_index}
    if len(indexed)!=len(current_index) or {x.get('sourceChapterId') for x in rows}!=set(indexed):raise ValueError('Current Seerah index coverage changed')
    numbers=[e.get('chapter') for e in rows]
    if any(not isinstance(n,int) or isinstance(n,bool) or n<1 for n in numbers) or len(set(numbers))!=len(numbers):raise ValueError('Current Seerah order is missing or ambiguous')
    output=[];rolemap={'plain':'body','quran':'quran','hadith':'hadith'}
    for ident in sorted(entries,key=lambda x:entries[x]['chapter']):
        e=entries[ident];a=byid[ident];i=indexed[e['sourceChapterId']];number=e['chapter']
        if ident!=f'new-seerah{number:03d}' or a.get('chapterId')!=i['id'] or any(obj.get('title')!=a['title'] for obj in (e,i)) or a.get('number')!=number or i.get('number')!=number or e.get('sourceHashes')!=[a['sourceSHA256']] or i.get('sourceSHA256')!=a['sourceSHA256'] or e.get('readingSHA256')!=a['readingSHA256'] or i.get('readingSHA256')!=a['readingSHA256']:raise ValueError('Reviewed Seerah identity changed: '+ident)
        if e.get('index')!=declaration['materialIndex'] or str(Path(declaration['materialIndex']).parent/i.get('readingPath','')).replace('\\','/')!=e.get('markdown'):raise ValueError('Seerah source path changed')
        material=inside(root,e['markdown']);material_raw=material.read_bytes()
        if sha(material_raw)!=a['readingSHA256']:raise ValueError('Seerah reading bytes changed: '+ident)
        paragraphs=a['paragraphs'];expected='# '+a['title']+'\n\n'+'\n\n'.join(p['text'] for p in paragraphs)
        if material_raw.decode('utf8').replace('\r\n','\n').strip()!=expected.strip():raise ValueError('Seerah reader text differs from publication: '+ident)
        blocks=[];missing_quran=0;missing_hadith=0
        for p in paragraphs:
            spans=[]
            for s in p['segments']:
                if s.get('role') not in rolemap:raise ValueError('Unknown reviewed Seerah segment')
                span={'text':s['text'],'role':rolemap[s['role']]}
                for key in ('verseKeys','citations','noteTexts'):
                    if s.get(key):span[key]=s[key]
                if s['role']=='quran' and not s.get('verseKeys'):missing_quran+=1
                if s['role']=='hadith' and not (s.get('citations') or s.get('noteTexts')):missing_hadith+=1
                spans.append(span)
            if ''.join(s['text'] for s in spans)!=p['text']:raise ValueError('Seerah segment text changed')
            blocks.append({'kind':'paragraph','text':p['text'],'spans':spans})
        unit={'schema':'iman-book-unit-v1','id':ident,'language':'ar','collection':'seerah','chapter':number,'title':a['title'],'complete':True,'reviewGate':'published-current','sourceHashes':[a['sourceSHA256']],'inputBindings':[{'path':e['markdown'],'sha256':sha(material_raw)},{'path':declaration['materialIndex'],'sha256':sha(index_path.read_bytes())},{'path':declaration['projection'],'sha256':sha(raw)}],'catalogBindings':[{'collection':'seerah','language':'ar','id':ident}],'sections':[{'blocks':blocks}],'readerTextSHA256':sha(''.join(b['text'] for b in blocks).encode('utf8')),'referenceReadiness':{'unboundQuranSegments':missing_quran,'unboundHadithSegments':missing_hadith},'provenance':{'readingSHA256':a['readingSHA256'],'projectionSHA256':sha(raw),'sourceChapterId':i['id'],'edition':'new-adult'}}
        check_unit(unit,{'language':'ar','collection':'seerah','id':ident});output.append(unit)
    return output
