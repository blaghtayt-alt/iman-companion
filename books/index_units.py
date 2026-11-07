"""Bind approved reader units to the material bytes in this checkout.

The publisher writes normalized reader units when a whole reviewed translation is
published. A changed material cannot reuse a stale normalized book unit.
"""
from pathlib import Path
import argparse,json,hashlib,sys
from build_books import check_unit,inside
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--commit',required=True);p.add_argument('--language');p.add_argument('--collection',choices=['tadabbur-extended','articles','seerah','hadith']);args=p.parse_args();root=args.root.resolve()
    if bool(args.language)!=bool(args.collection):raise ValueError('Select a language and collection together')
    units=[];seen=set();covered=set()
    catalog=json.loads((root/'materials/catalog.json').read_text(encoding='utf-8-sig'))
    production=bool(catalog.get('languages')) and 'preview' not in str(catalog.get('scope','')).lower()
    generated=[];scope_edition=None
    if production:
        if not args.language:raise ValueError('Production indexing held: select an independently reviewed book scope')
        declarations_path=root/'books/reviewed-books.json'
        if not declarations_path.is_file():raise ValueError('Production indexing held: no reviewed-book declarations')
        declarations=json.loads(declarations_path.read_text(encoding='utf8'))
        if declarations.get('schema')!='iman-reviewed-books-v1':raise ValueError('Invalid reviewed-book declarations')
        matches=[d for d in declarations.get('books',[]) if d.get('language')==args.language and d.get('collection')==args.collection]
        if len(matches)!=1 or matches[0].get('state')!='reviewed-current' or matches[0].get('automaticBuild') is not True:raise ValueError('Production indexing held: book scope has no current reviewed declaration')
        declaration=matches[0]
        if declaration.get('adapter')=='arabic-articles-v1':
            from adapt_ar_articles import generate
        elif declaration.get('adapter')=='arabic-new-seerah-v1':
            from adapt_ar_seerah import generate
            scope_edition=declaration.get('edition')
            if scope_edition!='new-adult':raise ValueError('Unexpected reviewed Seerah edition')
        else:raise ValueError('No registered reviewed source adapter for scope')
        normalized=generate(root,catalog,declaration)
        destination=root/'books/units/generated'/(args.language+'-'+args.collection+'-'+declaration['projectionSHA256'][:12]);destination.mkdir(parents=True,exist_ok=True)
        for unit in normalized:
            file=destination/(unit['id']+'.json');raw=(json.dumps(unit,ensure_ascii=False,indent=2)+'\n').encode('utf8')
            if file.exists():
                if file.read_bytes()!=raw:raise ValueError('Existing generated unit differs; preserve and review it: '+str(file))
            else:file.write_bytes(raw)
            generated.append(file)
    scope={'tadabbur','articles','seerah','essential-hadith'}
    def eligible(e):
        excluded={'held','withdrawn','archived','archive','source-archive','historical','superseded','not-currently-available','draft','work-in-progress'}
        return e.get('collection') in scope and (e.get('collection')!='tadabbur' or e.get('mode')=='extended') and not e.get('archived') and e.get('current',True) is not False and not any(str(e.get(k,'')).lower() in excluded for k in ['status','publicationStatus','translationStatus']) and not any('/source-archive/' in str(e.get(k,'')) for k in ['json','markdown'])
    collectionmap={'tadabbur':'tadabbur-extended','articles':'articles','seerah':'seerah','essential-hadith':'hadith'}
    def within(e):return not args.language or (e.get('language')==args.language and collectionmap.get(e.get('collection'))==args.collection and (not scope_edition or e.get('edition')==scope_edition))
    expected={(e['collection'],e['language'],str(e['id'])) for e in catalog['entries'] if eligible(e) and within(e)}
    for file in sorted(list((root/'books/units/current').rglob('*.json'))+generated):
        raw=file.read_bytes();unit=json.loads(raw)
        if args.language and (unit.get('language')!=args.language or unit.get('collection')!=args.collection):continue
        record={k:unit[k] for k in ['language','collection','id']};record.update(path=file.relative_to(root).as_posix(),sha256=sha(raw))
        check_unit(unit,record)
        # Explicit live bindings make the reader snapshot reproducible and prevent
        # a corrected/withdrawn source from leaving an older book online as latest.
        if not unit.get('inputBindings'):raise ValueError('Missing live input bindings: '+str(file))
        if not unit.get('catalogBindings'):raise ValueError('Missing published catalogue bindings')
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
    (root/'books/manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'boundUnits':len(units)}))
if __name__=='__main__':main()
