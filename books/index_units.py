"""Bind approved reader units to the material bytes in this checkout.

The publisher writes normalized reader units when a whole reviewed translation is
published. A changed material cannot reuse a stale normalized book unit.
"""
from pathlib import Path
import argparse,json,hashlib,sys
from urllib.parse import quote
from build_books import check_unit,inside
def sha(b):return hashlib.sha256(b).hexdigest()
COLLECTION_MAP={'tadabbur':'tadabbur-extended','articles':'articles','seerah':'seerah','essential-hadith':'hadith'}
def eligible(e):
    excluded={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
    return e.get('collection')in COLLECTION_MAP and(e.get('collection')!='tadabbur'or e.get('mode')=='extended')and not e.get('archived')and e.get('current',True)is not False and not any(str(e.get(k,'')).lower()in excluded for k in['status','publicationStatus','translationStatus'])and not any('/source-archive/'in str(e.get(k,''))for k in['json','markdown'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--commit',required=True);p.add_argument('--language');p.add_argument('--collection',choices=['tadabbur-extended','articles','seerah','hadith']);args=p.parse_args();root=args.root.resolve()
    if bool(args.language)!=bool(args.collection):raise ValueError('Select a language and collection together')
    units=[];seen=set();covered=set()
    catalog=json.loads((root/'materials/catalog.json').read_text(encoding='utf-8-sig'))
    production=bool(catalog.get('languages')) and 'preview' not in str(catalog.get('scope','')).lower()
    generated=[];scope_edition=None;edition_report=None;edition_rows=None
    if production:
        if not args.language:raise ValueError('Production indexing held: select an independently reviewed book scope')
        declarations_path=root/'books/reviewed-books.json'
        if not declarations_path.is_file():raise ValueError('Production indexing held: no reviewed-book declarations')
        declarations=json.loads(declarations_path.read_text(encoding='utf8'))
        if declarations.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid reviewed-book declarations')
        matches=[d for d in declarations.get('books',[]) if d.get('language')==args.language and d.get('collection')==args.collection]
        if len(matches)!=1 or matches[0].get('state')!='reviewed-current' or matches[0].get('automaticBuild') is not True:raise ValueError('Production indexing held: book scope has no current reviewed declaration')
        declaration=matches[0]
        from book_edition_scope import select
        edition_rows,edition_report=select(root,catalog,declaration)
        scope_edition=declaration.get('edition')
        if args.collection=='seerah'and scope_edition!='new-adult':raise ValueError('Only new adult Seerah belongs in the current book')
        current_units=[json.loads(f.read_bytes())for f in(root/'books/units/current').rglob('*.json')]
        scoped_units=[u for u in current_units if(u.get('language'),u.get('collection'))==(args.language,args.collection)]
        publisher_coverage={(b['collection'],b['language'],str(b['id']))for u in scoped_units for b in u.get('catalogBindings',[])}
        expected_scope={(e['collection'],e['language'],str(e['id']))for e in edition_rows}
        # A source-publishing transaction already supplied every exact approved
        # reader snapshot. No collection-specific manual adapter is needed.
        if expected_scope.issubset(publisher_coverage) and scoped_units:
            normalized=[]
        elif declaration.get('adapter')=='published-reader-units-v1':
            normalized=[]  # The final coverage check explains missing units.
        elif declaration.get('adapter')=='arabic-articles-v1':
            from adapt_ar_articles import generate
            normalized=generate(root,catalog,declaration)
        elif declaration.get('adapter')=='arabic-new-seerah-v1':
            from adapt_ar_seerah import generate
            scope_edition=declaration.get('edition')
            if scope_edition!='new-adult':raise ValueError('Unexpected reviewed Seerah edition')
            normalized=generate(root,catalog,declaration)
        elif declaration.get('adapter')=='reviewed-ikhlas-v1':
            from adapt_ikhlas import generate
            normalized=generate(root,catalog,declaration)
        else:raise ValueError('No registered reviewed source adapter for scope')
        published_ids={u['id']for u in scoped_units}
        normalized=[u for u in normalized if u['id']not in published_ids]
        generation_sha=sha(json.dumps(normalized,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8'))
        destination=root/'books/units/generated'/(args.language+'-'+args.collection+'-'+generation_sha[:16]);destination.mkdir(parents=True,exist_ok=True)
        for unit in normalized:
            file=destination/(quote(unit['id'],safe='')+'.json');raw=(json.dumps(unit,ensure_ascii=False,indent=2)+'\n').encode('utf8')
            if file.exists():
                if file.read_bytes()!=raw:raise ValueError('Existing generated unit differs; preserve and review it: '+str(file))
            else:file.write_bytes(raw)
            generated.append(file)
    collectionmap=COLLECTION_MAP
    def within(e):return not args.language or (e.get('language')==args.language and collectionmap.get(e.get('collection'))==args.collection and (not scope_edition or e.get('edition')==scope_edition))
    expected={(e['collection'],e['language'],str(e['id'])) for e in (edition_rows if edition_rows is not None else catalog['entries']) if eligible(e) and within(e)}
    for file in sorted(list((root/'books/units/current').rglob('*.json'))+generated):
        raw=file.read_bytes();unit=json.loads(raw)
        if args.language and (unit.get('language')!=args.language or unit.get('collection')!=args.collection):continue
        record={k:unit[k] for k in ['language','collection','id']};record.update(path=file.relative_to(root).as_posix(),sha256=sha(raw))
        check_unit(unit,record)
        # Explicit live bindings make the reader snapshot reproducible and prevent
        # a corrected/withdrawn source from leaving an older book online as latest.
        if not unit.get('inputBindings'):raise ValueError('Missing live input bindings: '+str(file))
        if not unit.get('catalogBindings'):raise ValueError('Missing published catalogue bindings')
        bindings=unit['catalogBindings']
        for binding in bindings:
            if binding['language']!=unit['language']or COLLECTION_MAP.get(binding['collection'])!=unit['collection']:raise ValueError('Material assigned to the wrong language or book collection')
        # Withdrawn whole materials remain in history/current snapshots for
        # provenance; exclude them without blocking unrelated remaining lessons.
        if not any((b['collection'],b['language'],str(b['id']))in expected for b in bindings):continue
        if unit.get('publicationApproval'):
            for binding in bindings:
                matching=[e for e in catalog['entries']if(e['collection'],e['language'],str(e['id']))==(binding['collection'],binding['language'],str(binding['id']))]
                if len(matching)!=1 or matching[0].get('bookReaderUnit',{}).get('path')!=file.relative_to(root).as_posix()or matching[0]['bookReaderUnit'].get('sha256')!=sha(raw):raise ValueError('Published reader unit differs from its approved catalogue binding')
            approval=json.loads(inside(root,unit['publicationApproval']['path']).read_bytes())
            if approval.get('approval',{}).get('readerTextSHA256')!=unit['readerTextSHA256']:raise ValueError('Reader text differs from its explicit publication approval')
        for binding in unit['catalogBindings']:
            catalogkey=(binding['collection'],binding['language'],str(binding['id']))
            collectionmap={'tadabbur':'tadabbur-extended','articles':'articles','seerah':'seerah','hadith':'hadith','essential-hadith':'hadith','heart-reminder':'hadith'}
            if binding['language']!=unit['language'] or collectionmap.get(binding['collection'])!=unit['collection']:raise ValueError('Material assigned to the wrong language or book collection')
            if catalogkey not in expected or catalogkey in covered:raise ValueError('Duplicate, retired or unavailable catalogue binding')
            covered.add(catalogkey)
        for binding in unit['inputBindings']:
            material=inside(root,binding['path'])
            if sha(material.read_bytes())!=binding['sha256']:raise ValueError('Stale book unit; publisher must regenerate: '+binding['path'])
        key=(unit['language'],unit['collection'],unit['id'])
        if key in seen:raise ValueError('Duplicate current unit')
        seen.add(key);units.append(record)
    if not units:raise ValueError('No published normalized reader units are available')
    if covered!=expected:raise ValueError('New catalogue materials lack book reader units: '+repr(sorted(expected-covered)[:12]))
    result={'schema':'iman-book-manifest-v1','sourceCommit':args.commit,'previewOnly':not bool(catalog.get('languages')) or 'preview' in str(catalog.get('scope','')).lower(),'units':units,'scope':{'language':args.language,'collection':args.collection} if args.language else None}
    if production:
        result['catalogSHA256']=sha((root/'materials/catalog.json').read_bytes())
        result['reviewedBooksSHA256']=sha((root/'books/reviewed-books.json').read_bytes())
    if edition_report is not None:
        result['editionReconciliation']=edition_report
    (root/'books/manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'boundUnits':len(units)}))
if __name__=='__main__':main()
