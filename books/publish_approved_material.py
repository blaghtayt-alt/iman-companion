"""Stage one explicitly approved source and its exact reader unit together.

This is a shared transaction entrypoint for source-publishing tools, not an
approval generator. The sole integration writer commits the returned file list
in the SAME commit as the approved source files. The existing workflow then
rebuilds books, eligible audio QR cards, releases, bundles and download tables.
"""
from pathlib import Path
from copy import deepcopy
from urllib.parse import quote
import argparse,json,os,re,tempfile
from published_library import inside,read,sha
from build_books import check_unit
from locale_copy import COPY

MAP={'tadabbur':'tadabbur-extended','articles':'articles','seerah':'seerah','essential-hadith':'hadith'}
RETIRED={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
def key(row):return row.get('collection'),row.get('language'),str(row.get('id'))
def available(row):
    return row.get('current',True)is not False and not row.get('archived')and not any(str(row.get(k,'')).lower()in RETIRED for k in['status','publicationStatus','translationStatus'])
def bytes_json(value):return(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')
def atomic(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False)as stream:stream.write(raw);temporary=Path(stream.name)
    os.replace(temporary,path)
def bindings(root,rows):
    if not rows:raise ValueError('Missing explicit review/source bindings')
    result={}
    for row in rows:
        relative=row.get('path','');file=inside(root,relative)
        if relative in result or not re.fullmatch('[a-f0-9]{64}',row.get('sha256',''))or not file.is_file()or sha(file.read_bytes())!=row['sha256']:raise ValueError('Missing, duplicate or changed approved input: '+relative)
        result[relative]=row['sha256']
    return result

def prepare(root,handoff_file,transaction_base=None):
    raw=handoff_file.read_bytes();handoff=json.loads(raw)
    if handoff.get('schema')!='iman-approved-material-publication-v1':raise ValueError('Unsupported publication handoff')
    approval=handoff.get('approval',{})
    if approval.get('decision')!='approved'or approval.get('wholeMaterial')is not True or not approval.get('approvalId')or not approval.get('reviewer'):raise ValueError('An existing explicit whole-material approval is required')
    reviewed=bindings(root,approval.get('reviewArtifacts',[]));source=bindings(root,handoff.get('sourceBindings',[]))
    catalog_path=root/'materials/catalog.json';catalog_raw=catalog_path.read_bytes()
    expected=handoff.get('expectedCatalogSHA256')
    if expected!=sha(catalog_raw) and (transaction_base is None or expected!=transaction_base):raise ValueError('Catalogue advanced; rebase the publication handoff before applying')
    catalog=json.loads(catalog_raw);entry=deepcopy(handoff.get('catalogEntry',{}));collection,language,ident=key(entry)
    if collection not in MAP or language not in COPY or not ident or not available(entry):raise ValueError('Only a current public material can be registered')
    if key(approval.get('material',{}))!=key(entry):raise ValueError('Approval is for a different material or language')
    if collection=='tadabbur':
        from quran_scope import canonical_surah
        if canonical_surah(entry)is None:raise ValueError('Only extended Quran reflections enter current books')
    if collection=='seerah':
        from book_edition_scope import CURRENT_SEERAH_EDITIONS
        if entry.get('edition') not in CURRENT_SEERAH_EDITIONS:raise ValueError('A supported explicit current Seerah edition is required')
    for name in['json','markdown']:
        if entry.get(name)and entry[name]not in source:raise ValueError('Approval does not bind the actual catalogue '+name)
    if not entry.get('json')and not entry.get('markdown'):raise ValueError('Catalogue material has no bound public source')
    reader_binding=handoff.get('readerUnit',{});reader_path=inside(root,reader_binding.get('path',''))
    if 'books/units/current/'in reader_binding.get('path','')or reader_path==handoff_file.resolve():raise ValueError('Reader approval cannot bind its own current output')
    reader_raw=reader_path.read_bytes()
    if sha(reader_raw)!=reader_binding.get('sha256'):raise ValueError('Approved reader snapshot changed')
    unit=json.loads(reader_raw);unitkey={'language':language,'collection':MAP[collection],'id':unit.get('id')}
    if unit.get('readerTextSHA256')!=approval.get('readerTextSHA256'):raise ValueError('Reader text was not part of this exact approval')
    if unit.get('catalogBindings')!=[{'collection':collection,'language':language,'id':entry['id']}]:raise ValueError('Reader unit does not cover exactly this approved material')
    inputs=bindings(root,unit.get('inputBindings',[]))
    if not all(inputs.get(p)==digest for p,digest in source.items()):raise ValueError('Reader unit omits or changes an approved source binding')
    if 'materials/catalog.json'in inputs:raise ValueError('Bind source files, not the self-modifying catalogue')
    order=unit.get('order')
    quran=read(root/'books/assets/quran-arabic.json')
    if type(order)is not int or order<1 or order!=handoff.get('canonicalOrder'):raise ValueError('Missing explicit canonical source order')
    if collection=='tadabbur':
        if order!=canonical_surah(entry):raise ValueError('Surah must use its canonical Quran order')
        if unit.get('surah',order)!=order:raise ValueError('Reader surah differs from its canonical catalogue order')
        from reviewed_coverage import validate
        validate(unit,quran,approval)
    elif collection in{'seerah','essential-hadith'}:
        from material_order import validate_publication
        validate_publication(unit,ident)
    if collection=='essential-hadith'and not any(b.get('citations')or any(s.get('citations')for s in b.get('spans',[]))for section in unit['sections']for b in section['blocks']):raise ValueError('Extended Hadith requires its verified original collection and narration number')
    check_unit(unit,unitkey,quran,root=root)
    approval_relative='materials/book-publication-approvals/'+sha(raw)+'.json'
    combined={**inputs,**reviewed,reader_binding['path']:reader_binding['sha256'],approval_relative:sha(raw)}
    unit['inputBindings']=[{'path':p,'sha256':digest}for p,digest in sorted(combined.items())]
    unit['publicationApproval']={'path':approval_relative,'sha256':sha(raw),'approvalId':approval['approvalId']}
    unit_relative='books/units/current/'+language+'/'+MAP[collection]+'/'+quote(str(unit['id']),safe='')+'.json';unit_raw=bytes_json(unit)
    entry['bookReaderUnit']={'schema':'iman-book-unit-v1','path':unit_relative,'sha256':sha(unit_raw)}
    matches=[i for i,row in enumerate(catalog['entries'])if key(row)==key(entry)]
    if len(matches)>1:raise ValueError('Duplicate catalogue identity')
    if matches:catalog['entries'][matches[0]]=entry
    else:catalog['entries'].append(entry)
    writes={approval_relative:raw,unit_relative:unit_raw,'materials/catalog.json':bytes_json(catalog)}
    # A first approved typed material creates only a preparation declaration.
    # Existing declarations and their release/source holds are never modified.
    declared_path=root/'books/reviewed-books.json'
    declarations=read(declared_path) if declared_path.exists() else {'schema':'iman-reviewed-books-v1','books':[]}
    if declarations.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid book source declarations')
    declared=[d for d in declarations['books'] if (d.get('language'),d.get('collection'))==(language,MAP[collection])]
    if len(declared)>1:raise ValueError('Duplicate book scope declaration')
    if collection=='seerah':
        if declared and declared[0].get('edition')!=entry.get('edition'):
            raise ValueError('Approved Seerah source belongs to a different declared lecture edition')
        if not declared and entry.get('edition')!='new-adult':
            raise ValueError('Current Seerah lecture translations require their existing reviewed edition declaration')
    created=not declared
    if created:
        declaration={'language':language,'collection':MAP[collection],'adapter':'published-reader-units-v1','state':'reviewed-current','scopePolicy':'reviewed-source-edition-v1','sourceReviewBindings':[], 'automaticBuild':True,'automaticRelease':False,'requireActualWordLayout':True,'releaseHold':'New collection is automatically prepared from exact whole-material approvals; final Word and visual release checks remain required.'}
        if collection=='seerah':declaration['edition']='new-adult'
        declarations['books'].append(declaration);writes['books/reviewed-books.json']=bytes_json(declarations)
    prior=inside(root,unit_relative)
    if prior.exists()and prior.read_bytes()!=unit_raw:
        old=prior.read_bytes();writes['books/units/history/'+sha(old)+'.json']=old
    required={**inputs,**reviewed,reader_binding['path']:reader_binding['sha256']}
    if handoff.get('approvedAudioIntake')is not None:
        from approved_reader_audio import source_intake
        audio_path,audio_raw,audio_inputs=source_intake(root,unit,unit_relative,handoff['approvedAudioIntake'])
        writes[audio_path]=audio_raw;required.update(audio_inputs)
    receipt={'schema':'iman-book-source-publication-receipt-v1','material':approval['material'],'canonicalOrder':order,'readerUnit':entry['bookReaderUnit'],'approvalId':approval['approvalId'],'sourceBindings':handoff['sourceBindings'],'generatedFiles':sorted(writes),'requiredInputs':[{'path':p,'sha256':digest}for p,digest in sorted(required.items())],'files':sorted(set(writes)|set(required)),'sourceApprovalCreated':False,'scopeReleaseHoldsChanged':False,'preparationScopeCreated':created}
    return writes,receipt

def apply(root,handoff_file,transaction_base=None):
    writes,receipt=prepare(root,handoff_file,transaction_base)
    # Validate everything before changing any file. Git publication must include
    # this entire list and the source bindings, so remote readers see one commit.
    for relative,raw in writes.items():atomic(inside(root,relative),raw)
    return receipt

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--handoff',type=Path,required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args();root=args.root.resolve();handoff=args.handoff.resolve()
    result=apply(root,handoff)if args.apply else prepare(root,handoff)[1];print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
