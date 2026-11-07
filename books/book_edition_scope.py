"""Select an explicitly bounded edition without approving unknown legacy rows.

Existing declarations retain their original all-current-row policy. Opted-in
editions use source-owner review bindings plus later whole-material publisher
transactions. Every eligible member still needs a complete reader adapter.
"""
from pathlib import Path
import hashlib, json, re

POLICY = 'reviewed-source-edition-v1'
MAP = {'tadabbur':'tadabbur-extended','articles':'articles','seerah':'seerah','essential-hadith':'hadith'}
RETIRED = {'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
def key(row): return row.get('collection'),row.get('language'),str(row.get('id'))
def inside(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or path==root.resolve(): raise ValueError('Edition input escapes repository')
    return path
def pinned(root,binding):
    raw=inside(root,binding.get('path','')).read_bytes()
    if not re.fullmatch('[a-f0-9]{64}',binding.get('sha256','')) or sha(raw)!=binding['sha256']:
        raise ValueError('Changed edition review/source input: '+str(binding.get('path')))
    return raw
def available(row):
    return row.get('collection') in MAP and (row.get('collection')!='tadabbur' or row.get('mode')=='extended') and not row.get('archived') and row.get('current',True) is not False and not any(str(row.get(k,'')).lower() in RETIRED for k in ('status','publicationStatus','translationStatus')) and not any('/source-archive/' in str(row.get(k,'')) for k in ('json','markdown'))

def typed_basis(root,row):
    """A declared publisher snapshot must be exact; malformed ones never fall back."""
    binding=row.get('bookReaderUnit')
    if binding is None: return None
    if binding.get('schema')!='iman-book-unit-v1': raise ValueError('Invalid declared publisher reader schema')
    unit=json.loads(pinned(root,binding))
    expected={'collection':row['collection'],'language':row['language'],'id':row['id']}
    if unit.get('catalogBindings')!=[expected] or unit.get('language')!=row['language'] or unit.get('collection')!=MAP[row['collection']]: raise ValueError('Publisher unit belongs to another edition')
    approval_binding=unit.get('publicationApproval',{})
    handoff=json.loads(pinned(root,approval_binding)); approval=handoff.get('approval',{})
    if handoff.get('schema')!='iman-approved-material-publication-v1' or approval.get('decision')!='approved' or approval.get('wholeMaterial') is not True or not approval.get('reviewer') or not approval.get('approvalId') or approval.get('approvalId')!=approval_binding.get('approvalId') or key(approval.get('material',{}))!=key(row) or approval.get('readerTextSHA256')!=unit.get('readerTextSHA256'):
        raise ValueError('Publisher unit lacks its exact whole-material approval')
    inputs={}
    for item in unit.get('inputBindings',[]):
        if item['path'] in inputs: raise ValueError('Duplicate publisher input binding')
        pinned(root,item);inputs[item['path']]=item['sha256']
    if not inputs: raise ValueError('Missing publisher input bindings')
    for rows in (handoff.get('sourceBindings',[]),approval.get('reviewArtifacts',[])):
        if not rows: raise ValueError('Missing publisher source/review artifacts')
        for item in rows:
            pinned(root,item)
            if inputs.get(item['path'])!=item['sha256']: raise ValueError('Publisher unit omits an approved input')
    for name in ('json','markdown'):
        if row.get(name) and row[name] not in {b['path'] for b in handoff['sourceBindings']}: raise ValueError('Publisher approval omits catalogue source')
    if inputs.get(approval_binding['path'])!=approval_binding['sha256']: raise ValueError('Publisher unit omits approval binding')
    if not any(key(b)==key(row) for b in unit['catalogBindings']): raise ValueError('Missing edition member binding')
    return {'kind':'whole-material-publisher','readerUnit':binding,'publicationApproval':approval_binding}

def select(root,catalog,declaration):
    lang=declaration['language']; collection=declaration['collection']; edition=declaration.get('edition')
    potential=[r for r in catalog['entries'] if available(r) and (r.get('language'),MAP[r['collection']])==(lang,collection) and (not edition or r.get('edition')==edition)]
    if len({key(r) for r in potential})!=len(potential): raise ValueError('Duplicate edition catalogue identity')
    if declaration.get('scopePolicy') is None: return potential,None
    if declaration.get('scopePolicy')!=POLICY: raise ValueError('Unsupported reviewed edition scope policy')
    historical={}
    evidence=[]
    bindings=declaration.get('sourceReviewBindings',[])
    if not bindings: raise ValueError('A bounded edition requires source-owner review evidence')
    for binding in bindings:
        data=json.loads(pinned(root,binding));evidence.append(binding)
        if data.get('schema')=='iman-existing-source-review-bindings-v1':
            for record in data.get('records',[]):
                if record.get('language')!=lang or MAP.get(record.get('collection'))!=collection: continue
                ident=str(record['materialId'])+(':extended' if record.get('collection')=='tadabbur' and record.get('mode')=='extended' else '')
                identity=(record['collection'],lang,ident)
                if identity in historical: raise ValueError('Duplicate historical review identity')
                if not record.get('existingWholeReview',{}).get('handoffSHA256') or not record.get('historicalPublication',{}).get('commit') or not record.get('sourceFiles') or not record.get('sourceConditions'):
                    raise ValueError('Incomplete historical whole-review evidence')
                historical[identity]=(record,record['sourceFiles']+record['sourceConditions'])
        elif data.get('schema')=='iman-arabic-current-reader-source-binding-v1':
            # This source-owner disposition deliberately excludes the mixed MD
            # and unestablished introduction. The adapter validates each section.
            if lang!='ar' or collection!='tadabbur-extended' or not data.get('sections'): raise ValueError('Arabic source binding in another edition')
            ids={s['key'].split(':')[0] for s in data['sections']}
            if len(ids)!=1: raise ValueError('Arabic binding mixes surahs')
            historical[('tadabbur','ar',next(iter(ids))+':extended')]=(data,[data['sourceJSON']])
        else: raise ValueError('Unsupported source-owner review evidence schema')
    selected=[]; unknown=[]; decisions=[]
    for row in potential:
        basis=typed_basis(root,row)
        if basis is None and key(row) in historical:
            record,files=historical[key(row)]
            revision=record.get('sourceRevisionSHA256',record.get('sourceOriginalSHA256'))
            if revision and revision not in row.get('sourceHashes',[]): raise ValueError('Catalogue source revision differs from historical review')
            for item in files:
                pinned(root,item)
                if item.get('reviewedSHA256') and item['reviewedSHA256']!=item['sha256']: raise ValueError('Historical reviewed bytes differ')
            if 'sourceFiles' in record:
                for name in ('json','markdown'):
                    if row.get(name) and row[name] not in {i['path'] for i in files}: raise ValueError('Historical binding omits catalogue source')
            basis={'kind':'existing-source-review','recordSHA256':sha(canonical(record))}
        identity={'collection':row['collection'],'language':lang,'id':row['id']}
        if basis is None:
            unknown.append({**identity,'reviewBinding':'UNKNOWN'})
        else:
            selected.append(row);decisions.append({**identity,'basis':basis})
    report={'schema':'iman-reviewed-edition-reconciliation-v1','policy':POLICY,'language':lang,'collection':collection,'sourceReviewBindings':evidence,'selected':decisions,'unknownLegacyRows':unknown,'unknownRowsApproved':False,'unknownRowsHeld':False}
    return selected,report

def scope_fingerprint(rows,report):
    payload={'rows':sorted(rows,key=lambda r:str(r['id'])),'policy':report['policy'],'evidence':report['sourceReviewBindings'],'selected':report['selected']}
    return sha(canonical(payload))
