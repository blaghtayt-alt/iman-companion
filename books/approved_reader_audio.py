"""Explicit, source-matched audio intake for all four normalized book types.

Publication of a ZIP alone is never an approval. A real source/recording approval
record is a mandatory pinned input. No review or listening scope is created here.
"""
from pathlib import Path
from urllib.parse import urlsplit,quote
import argparse,json,re
from published_library import inside,read,sha
from publish_approved_material import bindings,atomic,bytes_json,MAP,available
from build_books import check_unit
from material_audio import validate_record,PLAYER_BASE

REPO='blaghtayt-alt/iman-companion';BASE='https://github.com/'+REPO+'/releases/download/'

def intake_path(unit):
    return'materials/audio/approved-intakes/'+unit['language']+'/'+unit['collection']+'/'+quote(unit['id'],safe='')+'.json'

def source_intake(root,unit,unit_relative,spec):
    """Stage existing recording approval metadata with a source transaction."""
    if not isinstance(spec,dict)or set(spec)!={'approvalRecord','pack'}:raise ValueError('Expected exact approved recording reference and pack metadata')
    refs=bindings(root,[spec['approvalRecord']]);approval=read(inside(root,spec['approvalRecord']['path']))
    if approval.get('schema')!='iman-material-audio-approval-v1'or approval.get('approved')is not True or approval.get('decision')not in{'approved','approved-for-publication'}or not approval.get('approvalId')or not approval.get('reviewer'):raise ValueError('Source transaction has no actual recording approval')
    if(approval.get('materialId'),approval.get('language'),approval.get('collection'))!=(unit['id'],unit['language'],unit['collection']):raise ValueError('Recording approval belongs to a different material')
    if approval.get('sourceSHA256')not in unit['sourceHashes']:raise ValueError('Recording approval uses a different source revision')
    if approval.get('readerTextSHA256')!=unit['readerTextSHA256']:
        reading=approval.get('readingSource',{});inputs={b['path']:b['sha256']for b in unit['inputBindings']}
        if not approval.get('readingSHA256')or reading.get('sha256')!=approval['readingSHA256']or inputs.get(reading.get('path'))!=approval['readingSHA256']:raise ValueError('Recording approval uses a different target reading')
    refs.update(bindings(root,approval.get('reviewArtifacts',[])))
    payload={'schema':'iman-approved-audio-intake-v1','approvalRecord':spec['approvalRecord'],'bookUnit':unit_relative,'pack':spec['pack']}
    return intake_path(unit),bytes_json(payload),refs

def validate_source(root,record,pending_intake=None):
    try:return _validate_source(root,record,pending_intake)
    except(KeyError,TypeError,AttributeError)as error:raise ValueError('Incomplete approved reader/audio binding')from error

def _validate_source(root,record,pending_intake=None):
    if record.get('approved')is not True:raise ValueError('Recording has no explicit publication approval')
    validate_record({**record,'status':'published'})
    origin=record['origin'];approval_ref=origin['approvedReaderAudio'];approval_path=inside(root,approval_ref['path']);approval_raw=approval_path.read_bytes()
    if origin.get('intakeMetadata'):
        metadata=origin['intakeMetadata'];raw=pending_intake if pending_intake is not None else inside(root,metadata['path']).read_bytes()
        if sha(raw)!=metadata['sha256']:raise ValueError('Current audio intake changed or was withdrawn')
        expected={'schema':'iman-approved-audio-intake-v1','approvalRecord':approval_ref,'bookUnit':origin['bookUnit'],'pack':{'url':origin['packUrl'],'sha256':origin['packSHA256'],'bytes':origin['packBytes'],'member':origin['member']}}
        if json.loads(raw)!=expected:raise ValueError('Current audio intake identity changed')
    if sha(approval_raw)!=approval_ref['sha256']:raise ValueError('Recording approval changed or was withdrawn')
    approval=json.loads(approval_raw)
    if approval.get('schema')!='iman-material-audio-approval-v1'or approval.get('approved')is not True or approval.get('decision')not in{'approved','approved-for-publication'}or not approval.get('approvalId')or not approval.get('reviewer'):raise ValueError('A real recording-specific approval is required')
    for field in['materialId','collection','language','sourceSHA256','audioSHA256','audioBytes']:
        if approval.get(field)!=record.get(field):raise ValueError('Recording approval identity mismatch: '+field)
    for field in['readingSHA256','readerTextSHA256']:
        if approval.get(field)!=record.get(field):raise ValueError('Recording approval reading mismatch')
    bindings(root,approval.get('reviewArtifacts',[]))
    unit_path=inside(root,origin['bookUnit'])
    if not unit_path.is_relative_to((root/'books/units/current').resolve()):raise ValueError('Audio must bind a current normalized public reader')
    unit_raw=unit_path.read_bytes();unit=json.loads(unit_raw)
    if(unit.get('id'),unit.get('language'),unit.get('collection'))!=(record['materialId'],record['language'],record['collection']):raise ValueError('Recording belongs to a different material, language or book')
    check_unit(unit,{'id':record['materialId'],'language':record['language'],'collection':record['collection']},read(root/'books/assets/quran-arabic.json'))
    inputs=bindings(root,unit.get('inputBindings',[]))
    if record['sourceSHA256']not in unit['sourceHashes']:raise ValueError('Recording source revision is no longer current')
    if record.get('readerTextSHA256')and record['readerTextSHA256']!=unit['readerTextSHA256']:raise ValueError('Current reader text changed after recording approval')
    if record.get('readingSHA256'):
        reading=approval.get('readingSource',{})
        if reading.get('sha256')!=record['readingSHA256']or inputs.get(reading.get('path'))!=record['readingSHA256']:raise ValueError('Recording is not bound to the current published target reading')
    catalog=read(root/'materials/catalog.json')
    for binding in unit['catalogBindings']:
        if MAP.get(binding['collection'])!=record['collection']or binding['language']!=record['language']:raise ValueError('Incorrect audio catalogue category')
        matches=[row for row in catalog['entries']if(row.get('collection'),row.get('language'),str(row.get('id')))==(binding['collection'],binding['language'],str(binding['id']))]
        if len(matches)!=1 or not available(matches[0]):raise ValueError('Audio source material is held, withdrawn or unavailable')
        current=matches[0]['bookReaderUnit']
        if current['path']!=origin['bookUnit']or current['sha256']!=sha(unit_raw):raise ValueError('Current normalized source binding changed')
        audio=matches[0].get('audio')
        if isinstance(audio,dict)and not available(audio):raise ValueError('Current source explicitly holds this voice')
    pack=urlsplit(origin['packUrl'])
    if pack.scheme!='https'or pack.netloc!='github.com'or pack.query or pack.fragment or not re.fullmatch(r'/blaghtayt-alt/iman-companion/releases/download/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.zip',pack.path):raise ValueError('Audio pack must be an immutable published release ZIP')
    if not re.fullmatch('[a-f0-9]{64}',origin.get('packSHA256',''))or type(origin.get('packBytes'))is not int or origin['packBytes']<=0:raise ValueError('Missing exact published pack size/hash')
    member=origin.get('member','')
    if not member or member.startswith('/')or'..'in Path(member).parts or'\\'in member:raise ValueError('Invalid approved audio pack member')
    expected=BASE+'material-audio-v1/'+record['audioUrl'].rsplit('/',1)[-1]
    if record['audioUrl']!=expected:raise ValueError('Incorrect immutable audio destination')
    return({'title':unit['title'],'audio':{'asset':member,'reviewScope':approval.get('reviewScope','')}},
      {'file':pack.path.rsplit('/',1)[-1],'sha256':origin['packSHA256'],'bytes':origin['packBytes']},
      {'path':origin['bookUnit'],'sha256':sha(unit_raw),'approval':approval_ref})

def intake(root,handoff_file,apply=False):
    handoff=read(handoff_file)
    if handoff.get('schema')!='iman-approved-audio-intake-v1':raise ValueError('Unsupported approved audio handoff')
    approval_ref=handoff['approvalRecord'];approval_raw=inside(root,approval_ref['path']).read_bytes()
    if sha(approval_raw)!=approval_ref['sha256']:raise ValueError('Audio approval handoff changed')
    approval=json.loads(approval_raw);unit=read(inside(root,handoff['bookUnit']));pack=handoff['pack'];extension=Path(pack['member']).suffix.lower()
    if extension not in{'.opus','.mp3','.m4a','.ogg','.wav'}:raise ValueError('Unsupported approved recording format')
    slug=re.sub('[^A-Za-z0-9._-]','-',unit['id']);filename=unit['collection']+'-'+unit['language']+'-'+slug+'-'+approval['audioSHA256'][:16]+extension
    keys=['materialId','collection','language','sourceSHA256','audioSHA256','audioBytes','readingSHA256','readerTextSHA256']
    record={k:approval[k]for k in keys if k in approval};record.update(title=unit['title'],approved=approval.get('approved'),status='ready-for-publication',audioUrl=BASE+'material-audio-v1/'+filename,
      origin={'approvedReaderAudio':approval_ref,'bookUnit':handoff['bookUnit'],'packUrl':pack['url'],'packSHA256':pack['sha256'],'packBytes':pack['bytes'],'member':pack['member']})
    stored={'schema':'iman-approved-audio-intake-v1','approvalRecord':approval_ref,'bookUnit':handoff['bookUnit'],'pack':pack}
    if handoff!=stored:raise ValueError('Unexpected audio intake fields')
    stored_raw=handoff_file.read_bytes()if handoff_file.resolve()==inside(root,intake_path(unit))else bytes_json(stored)
    record['origin']['intakeMetadata']={'path':intake_path(unit),'sha256':sha(stored_raw)}
    validate_source(root,record,pending_intake=stored_raw)
    path=root/'materials/audio/publish.json';seed=read(path)if path.exists()else{'schema':'iman-material-audio-v1','playerBase':PLAYER_BASE,'entries':[]}
    if seed.get('schema')!='iman-material-audio-v1'or seed.get('playerBase')!=PLAYER_BASE:raise ValueError('Invalid existing approved audio inputs')
    key=(record['materialId'],record['language']);old=[r for r in seed['entries']if(r['materialId'],r['language'])==key]
    if len(old)>1:raise ValueError('Ambiguous current audio input')
    if any(r.get('collection')!=record['collection'] for r in old):raise ValueError('Audio material ID is already used by another collection in this language')
    writes={intake_path(unit):stored_raw}
    if old and old[0]!=record:
        raw=bytes_json(old[0]);writes['materials/audio/intake-history/'+sha(raw)+'.json']=raw
    seed['entries']=[r for r in seed['entries']if(r['materialId'],r['language'])!=key]+[record];writes['materials/audio/publish.json']=bytes_json(seed)
    if apply:
        for relative,raw in writes.items():atomic(inside(root,relative),raw)
    required={b['path']:b['sha256']for b in unit['inputBindings']}
    required.update({b['path']:b['sha256']for b in approval['reviewArtifacts']})
    required.update({approval_ref['path']:approval_ref['sha256'],handoff['bookUnit']:sha(inside(root,handoff['bookUnit']).read_bytes())})
    return{'schema':'iman-approved-audio-intake-receipt-v1','materialId':record['materialId'],'language':record['language'],'collection':record['collection'],'approvalId':approval['approvalId'],'generatedFiles':sorted(writes),'requiredInputs':[{'path':p,'sha256':digest}for p,digest in sorted(required.items())],'files':sorted(set(writes)|set(required)),'reviewOrListeningApprovalCreated':False,'qrIsGeneratedByBookBuilder':True}

def discover(root,apply=True):
    """Called by the actual CI audio publisher, before it loads pending audio."""
    report={'schema':'iman-automatic-approved-audio-intakes-v1','accepted':[],'errors':[],'generatedFiles':[]};seen=set();files=[]
    candidates=sorted((root/'materials/audio/approved-intakes').rglob('*.json'));collections_by_key={}
    for file in candidates:
        try:
            handoff=read(file);unit=read(inside(root,handoff['bookUnit']));key=(unit['id'],unit['language'])
            collections_by_key.setdefault(key,set()).add(unit['collection'])
        except (ValueError,KeyError,TypeError,FileNotFoundError):pass
    for file in candidates:
        relative=file.relative_to(root).as_posix()
        try:
            handoff=read(file);unit=read(inside(root,handoff['bookUnit']));identity=(unit['language'],unit['collection'],unit['id'])
            if len(collections_by_key.get((unit['id'],unit['language']),set()))>1:raise ValueError('Audio material ID is used by multiple collections in this language')
            if relative!=intake_path(unit)or identity in seen:raise ValueError('Duplicate or incorrectly filed current audio intake')
            seen.add(identity);receipt=intake(root,file,apply);report['accepted'].append({'path':relative,'materialId':receipt['materialId'],'language':receipt['language'],'collection':receipt['collection']});files.extend(receipt['generatedFiles'])
        except(ValueError,KeyError,TypeError,FileNotFoundError)as error:report['errors'].append({'path':relative,'error':str(error)})
    report['generatedFiles']=sorted(set(files))
    if apply:atomic(root/'books/.cache/approved-audio-intake-report.json',bytes_json(report))
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--handoff',type=Path,required=True);p.add_argument('--apply',action='store_true');args=p.parse_args();print(json.dumps(intake(args.root.resolve(),args.handoff.resolve(),args.apply),ensure_ascii=False))
if __name__=='__main__':main()
