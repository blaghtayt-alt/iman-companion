"""Generate the reviewed Arabic article book inputs from current public sources.

A source update must also update the independently checked reader projection. This
adapter never infers semantic colors, references, or current status from prose.
"""
from pathlib import Path
import hashlib,json,re
from build_books import check_unit,inside,reference_text
from bibliography import native_text

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())
def visible_markdown(text):return re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)

def reference_groups(refs):
    """Keep explicitly supplied continuation paragraphs with their source note.

    An ordinary unnumbered bibliography paragraph stays unanchored. Only an
    explicit, contiguous continuationOf binding joins a numbered source.
    """
    numbered={r['id']:r for r in refs if r['id']}
    if len(numbered)!=sum(bool(r['id']) for r in refs):raise ValueError('Duplicate article reference number')
    groups={key:[value] for key,value in numbered.items()};previous=None
    for ref in refs:
        if ref.get('segments') and ''.join(s['text'] for s in ref['segments'])!=ref['text']:raise ValueError('Article reference spans differ from their source text')
        parent=ref.get('continuationOf')
        if parent is not None:
            if ref['id'] or not isinstance(parent,str) or not parent or parent not in numbered or previous!=parent:raise ValueError('Article reference continuation is not bound to its preceding source')
            groups[parent].append(ref)
        else:previous=ref['id'] or None
    return groups

def validate_reference_markers(paragraph,groups):
    """Fail on orphaned source numbers instead of exporting a dangling marker."""
    spans=[];offset=0
    for segment in paragraph['segments']:
        spans.append((offset,offset+len(segment['text']),segment.get('note')))
        offset+=len(segment['text'])
    digits=r'[0-9\u0660-\u0669]+'
    for marker in re.finditer(r'\[('+digits+r'(?:\s*[،,]\s*'+digits+r')*)\]',paragraph['text']):
        numbers=list(re.finditer(digits,marker.group(1)))
        for item in numbers:
            number=item.group()
            if number not in groups:raise ValueError('Article source marker has no reference: '+number)
            # A composite marker has a distinct source-note span on each number.
            # Single-number markers retain their whole-bracket binding check.
            left,right=(marker.start(),marker.end()) if len(numbers)==1 else (marker.start(1)+item.start(),marker.start(1)+item.end())
            if not any(start<=left and end>=right and note==number for start,end,note in spans):raise ValueError('Article source marker is not bound to its reference: '+number)
def current_record(row):
    retired={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
    return not row.get('archived') and row.get('current',True) is not False and not any(str(row.get(k,'')).lower() in retired for k in ('status','publicationStatus','translationStatus'))

def approved_exclusions(root,catalog,declaration,excluded_catalog_keys=()):
    """Exclude only independently bound whole-material publisher snapshots.

    A normalized file's presence, identifier, or self-asserted reviewGate is not
    an approval. Callers pass current catalogue identities, never unit filenames.
    """
    if not excluded_catalog_keys:return set()
    from book_edition_scope import typed_basis
    collection={'articles':'articles','seerah':'seerah','hadith':'essential-hadith'}[declaration['collection']]
    requested=set()
    for identity in excluded_catalog_keys:
        if not isinstance(identity,(tuple,list)) or len(identity)!=3:raise ValueError('Invalid adapter exclusion identity')
        key=(identity[0],identity[1],str(identity[2]))
        if key[:2]!=(collection,declaration['language']):raise ValueError('Adapter exclusion belongs to another collection')
        matches=[r for r in catalog['entries'] if (r.get('collection'),r.get('language'),str(r.get('id')))==key]
        if len(matches)!=1 or not current_record(matches[0]) or (declaration.get('edition') and matches[0].get('edition')!=declaration['edition']):raise ValueError('Adapter exclusion is not one current catalogue identity')
        if typed_basis(root,matches[0]) is None:raise ValueError('Adapter exclusion requires an exact approved publisher snapshot')
        requested.add(key[2])
    return requested

def require_mixed_index_binding(root,declaration,excluded_ids):
    """A per-material approval never approves changes to a shared legacy index."""
    if excluded_ids:
        expected=declaration.get('materialIndexSHA256','')
        if not re.fullmatch('[a-f0-9]{64}',expected) or sha(inside(root,declaration['materialIndex']).read_bytes())!=expected:
            raise ValueError('Mixed adapter shared material index needs its unchanged exact binding')

def generate(root,catalog,declaration,*,excluded_catalog_keys=()):
    if (declaration.get('language'),declaration.get('collection'),declaration.get('adapter'))!=('ar','articles','arabic-articles-v1'):raise ValueError('Unsupported reviewed source adapter')
    excluded=approved_exclusions(root,catalog,declaration,excluded_catalog_keys)
    require_mixed_index_binding(root,declaration,excluded)
    projection_path=inside(root,declaration['projection']);raw=projection_path.read_bytes()
    if sha(raw)!=declaration.get('projectionSHA256'):raise ValueError('Reviewed article projection changed')
    projection=json.loads(raw)
    if projection.get('schema')!='iman-reviewed-article-projection-v1' or projection.get('language')!='ar' or projection.get('collection')!='articles':raise ValueError('Invalid reviewed article projection')
    allrows=[e for e in catalog['entries'] if e.get('collection')=='articles' and e.get('language')=='ar']
    if excluded and any(current_record(e) and str(e['id']) not in excluded and e.get('translationStatus')!='supplied-arabic-current' for e in allrows):raise ValueError('Uncovered current article has no eligible legacy source or approved publisher snapshot')
    rows=[e for e in allrows if e.get('translationStatus')=='supplied-arabic-current' and current_record(e) and str(e['id']) not in excluded]
    entries={e['id']:e for e in rows};reviewed=projection['articles'];byid={a['id']:a for a in reviewed}
    known_ids={e['id'] for e in allrows if 'id' in e}
    if len(entries)!=len(rows) or len(byid)!=len(reviewed) or not set(entries).issubset(byid) or not set(byid).issubset(known_ids) or not entries:raise ValueError('Current article coverage changed or is ambiguous')
    numbers=[e.get('number') or e.get('position') for e in rows]
    if any(not isinstance(n,int) or isinstance(n,bool) or n<1 for n in numbers) or len(set(numbers))!=len(numbers):raise ValueError('Current article order is missing or ambiguous')
    index_path=inside(root,declaration['materialIndex']);index=read(index_path);active_index=[x for x in index['articles'] if current_record(x) and str(x['id']) not in excluded];indexed={x['id']:x for x in active_index}
    if len(indexed)!=len(active_index) or set(entries)!=set(indexed):raise ValueError('Article index coverage changed')
    output=[]
    for ident in sorted(entries,key=lambda x:(entries[x].get('number') or entries[x].get('position') or 0,x)):
        e=entries[ident];a=byid[ident];i=indexed[ident];number=e.get('number') or e.get('position')
        if number!=a['number'] or e.get('title')!=a['title'] or i.get('title')!=a['title'] or e.get('sourceHashes')!=[a['sourceSHA256']] or i.get('preparedSourceSHA256')!=a['sourceSHA256'] or e.get('readingSHA256')!=a['readingSHA256'] or i.get('readingSHA256')!=a['readingSHA256']:raise ValueError('Reviewed article identity changed: '+ident)
        if e.get('index')!=declaration['materialIndex'] or str(Path(declaration['materialIndex']).parent / i.get('path','')).replace('\\','/')!=e.get('markdown'):raise ValueError('Article source path or index changed: '+ident)
        material=inside(root,e['markdown'])
        if sha(material.read_bytes())!=a['materialSHA256']:raise ValueError('Article source bytes changed: '+ident)
        parts=material.read_text(encoding='utf8').split('\n\n')
        heading=next((k for k,v in enumerate(parts) if v.strip() in ('## المراجع','## مراجع الشواهد')),None)
        paragraphs=a['paragraphs'];refs=a['references']
        if heading is None or parts[0]!='# '+a['title'] or [re.sub(r'^## ','',x).strip('\n') for x in parts[1:heading]]!=[p['text'] for p in paragraphs]:raise ValueError('Article body differs from the reviewed reader: '+ident)
        if [('heading' if x.startswith('## ') else 'body') for x in parts[1:heading]]!=[p['kind'] for p in paragraphs]:raise ValueError('Article heading structure changed: '+ident)
        if [visible_markdown(x).strip() for x in parts[heading+1:] if x.strip()]!=[x['text'].strip() for x in refs]:raise ValueError('Article references differ from the reviewed reader: '+ident)
        if sha((a['title']+'\n\n'+'\n\n'.join(p['text'] for p in paragraphs)).encode('utf8'))!=a['readingSHA256']:raise ValueError('Article reader hash mismatch: '+ident)
        refmap=reference_groups(refs)
        def citation(r):
            # Link targets are retrieval furniture; their visible source titles
            # are still part of the citation and must not be deleted.
            text=''.join(x['text'] for x in r['segments']) if r['segments'] else r['text']
            return native_text(reference_text(text),'ar',preserved_identifiers=r.get('preservedIdentifiers',()))
        def numbered_citation(number):return '\n'.join(citation(r) for r in refmap[number])
        def numbered_identifiers(number):return list(dict.fromkeys(value for r in refmap[number] for value in r.get('preservedIdentifiers',())))
        blocks=[];referenced=set()
        rolemap={'plain':'body','quran':'quran','hadith':'hadith','scholar':'scholar'}
        for para in paragraphs:
            if para['kind'] not in {'heading','body'}:raise ValueError('Unknown article paragraph type')
            validate_reference_markers(para,refmap)
            spans=[]
            for seg in para['segments']:
                if seg['role'] not in rolemap:raise ValueError('Unknown reviewed article segment')
                span={'text':seg['text'],'role':rolemap[seg['role']]}
                if seg.get('note'):
                    if seg['note'] not in refmap:raise ValueError('Article reference marker is not bound')
                    referenced.add(seg['note'])
                    span['noteTexts']=[numbered_citation(seg['note'])]
                    identifiers=numbered_identifiers(seg['note'])
                    if identifiers:span['noteIdentifiers']=[identifiers]
                spans.append(span)
            if ''.join(x['text'] for x in spans)!=para['text']:raise ValueError('Article semantic spans do not match body')
            blocks.append({'kind':'heading' if para['kind']=='heading' else 'paragraph','text':para['text'],'spans':spans})
        # Preserve source entries without a reader anchor as one lesson-level
        # footnote attached after the final body paragraph. Do not duplicate
        # anchored references as ordinary body text or invent an anchor.
        unanchored_refs=[r for r in refs if not r.get('continuationOf') and (not r['id'] or r['id'] not in referenced)]
        unanchored=[numbered_citation(r['id']) if r['id'] else citation(r) for r in unanchored_refs]
        if unanchored:
            identifiers=list(dict.fromkeys(value for r in unanchored_refs for value in (numbered_identifiers(r['id']) if r['id'] else r.get('preservedIdentifiers',()))))
            blocks.append({'kind':'note','text':'؛ '.join(unanchored),**({'preservedIdentifiers':identifiers} if identifiers else {})})
        sections=[{'blocks':blocks}]
        alltext=''.join(b['text'] for section in sections for b in section['blocks'])
        unit={'schema':'iman-book-unit-v1','id':ident,'language':'ar','collection':'articles','number':number,'title':a['title'],'complete':True,'reviewGate':'published-current','sourceHashes':[a['sourceSHA256']],'inputBindings':[{'path':e['markdown'],'sha256':sha(material.read_bytes())},{'path':declaration['materialIndex'],'sha256':sha(index_path.read_bytes())},{'path':declaration['projection'],'sha256':sha(raw)}],'catalogBindings':[{'collection':'articles','language':'ar','id':ident}],'sections':sections,'readerTextSHA256':sha(alltext.encode('utf8')),'provenance':{'readingSHA256':a['readingSHA256'],'projectionSHA256':sha(raw),'sourceIdentity':e.get('sourceIdentity')}}
        check_unit(unit,{'language':'ar','collection':'articles','id':ident});output.append(unit)
    return output
