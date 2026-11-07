"""Place exact source-owner reference classifications; never invent quote offsets."""
from copy import deepcopy
import re
from book_edition_scope import canonical,sha
from book_references import reference
from bibliography import native_text,digits,quran_reference

def index_projection(data,source_path,source_sha):
    if data.get('schema')!='iman-source-reference-projection-v1':raise ValueError('Unsupported source reference projection')
    snapshots=[r for r in data['sources'] if r['path']==source_path]
    if len(snapshots)!=1 or snapshots[0]['sha256']!=source_sha:raise ValueError('Reference classification belongs to another reader revision')
    result={}
    for row in data['references']:
        if row['sourcePath']!=source_path:continue
        field=row['source_reference_pointer'].rsplit('.',1)[-1]
        if field not in {'citations','references'}:raise ValueError('Unrecognized original reference field')
        for number in row['matching_source_indices_zero_based']:
            key=row['section'],field,number
            if key in result:raise ValueError('Duplicate source reference projection')
            result[key]=row
    return result

def binding(row,language,names,quran):
    kind=row['classification'];detail=row['classification_detail'];raw=row['reference_object']
    if kind in {'quran_reference','mixed_quran_and_scholar_source'}:
        keys=detail.get('verse_keys',[])
        if not keys:
            for part in re.split('[؛;]',raw['reference']):
                value=reference(part.strip(),language,names,quran)
                if not value or not value.get('verseKeys'):raise ValueError('Named source Quran reference remains unresolved')
                keys+=value['verseKeys']
        if any(key not in quran for key in keys):raise ValueError('Source reference points outside canonical Quran')
        result={'verseKeys':list(dict.fromkeys(keys))}
        if kind=='mixed_quran_and_scholar_source':
            value='؛ '.join(str(detail[k]) for k in ('report','source') if detail.get(k))
            result['noteTexts']=[native_text(digits(value,language),language)]
        return result
    if kind=='hadith_collection_and_explicit_number':
        collection=detail['collection'];number=str(detail['explicit_number'])
        result=reference(collection+' '+number,language,names,quran)
        if not result or not result.get('citations'):
            # A named additional original collection (e.g. al-Adab al-Mufrad)
            # must not be relabelled as the same author's Sahih collection.
            title=native_text(collection,language)
            result={'citations':[{'type':'hadith','book':'source-book-'+sha(title.encode())[:12],'localizedTitles':{language:title},'number':number}]}
        qualification=detail.get('qualification') or row.get('qualification')
        if qualification and re.search('[A-Za-z]',qualification):
            # Source-map analyst comments are provenance, not native publisher
            # wording. Recover the literal grade/attribution from the source.
            literal=raw.get('sourceReference') or raw.get('reference') or raw.get('label','')
            qualification=re.split('[؛;]',literal)[-1].strip() if re.search('[؛;]',literal) else None
        if qualification:result['citations'][0]['qualification']={'language':language,'text':native_text(qualification,language)}
        return result
    if kind=='named_scholar_book_or_commentary':return {'noteTexts':[native_text(digits(detail['literal_source'],language),language)]}
    if kind=='named_source_locator_ambiguous':
        # Exact book-only source credit, not a claim that "5" is a Hadith no.
        return {'noteTexts':[native_text(digits(raw['reference'],language),language)],'qualifiedBookOnlyLocator':{'source':detail['source'],'literalLocator':detail['literal_locator'],'locatorType':detail['locator_type']}}
    raise ValueError('Unresolved source reference classification: '+str(kind))

def annotate(block,start,end,selected,meta):
    if block['text'][start:end]!=selected:raise ValueError('Quote annotation does not match literal current text')
    out=[];cursor=0;inserted=False
    for original in block.get('spans') or [{'text':block['text'],'role':block.get('role','body')}]:
        text=original['text'];right=cursor+len(text)
        cuts=sorted({cursor,right,max(cursor,min(right,start)),max(cursor,min(right,end))})
        for a,b in zip(cuts,cuts[1:]):
            if a==b:continue
            span=deepcopy(original);span['text']=text[a-cursor:b-cursor]
            if b<right:
                for key in ['citations','noteTexts']:span.pop(key,None)
            if meta.get('verseKeys') and a<end and b>start:
                span['verseKeys']=meta['verseKeys'];span['explicitSourceReferencePlaced']=True
            out.append(span)
            if b==end and not inserted:out.append({'text':'','role':'body',**meta});inserted=True
        cursor=right
    if not inserted:raise ValueError('Quote annotation endpoint is not in current block')
    if ''.join(s['text'] for s in out)!=block['text']:raise ValueError('Quote/prose changed while attaching its exact source identity')
    block['spans']=out

def place(projected,citation,entry,converted,language,names,quran,known_verses,known_citations):
    if canonical(projected['reference_object'])!=canonical(citation):raise ValueError('Current source reference differs from its frozen classification')
    meta=binding(projected,language,names,quran);record={'classification':projected['classification'],'referenceObjectSHA256':sha(canonical(citation)),'section':projected['section'],'sourceIssues':projected['issues']}
    book_only=meta.pop('qualifiedBookOnlyLocator',None)
    if book_only:record['qualifiedBookOnlyLocator']=book_only
    fresh=deepcopy(meta)
    if fresh.get('verseKeys'):
        fresh['verseKeys']=[key for key in fresh['verseKeys'] if key not in known_verses]
        if not fresh['verseKeys']:fresh.pop('verseKeys')
    if fresh.get('citations'):
        fresh['citations']=[c for c in fresh['citations'] if (c['book'],c['number']) not in known_citations]
        if not fresh['citations']:fresh.pop('citations')
    if not fresh:record['placement']='already-bound native source identity';return record
    anchors=projected['literal_quote_anchors'];placed=False
    if len(anchors)==1:
        anchor=anchors[0];number=anchor['unit_block_index_zero_based'];source=entry['blocks'][number]
        if sha(source['text'].encode())!=anchor['unit_block_sha256']:raise ValueError('Original quote block changed after source classification')
        selected=citation.get('quote');start,end=anchor['cp']
        if not selected or source['text'][start:end]!=selected:raise ValueError('Source quote character anchor differs')
        candidates=[b for b in converted if b.get('sourceBlockIndex')==number]
        if len(candidates)==1 and candidates[0]['text'].count(selected)==1:
            block=candidates[0];position=block['text'].index(selected);annotate(block,position,position+len(selected),selected,fresh)
            record.update({'placement':'exact literal source quote','sourceCP':anchor['cp'],'currentBookCP':[position,position+len(selected)],'sourceBlockIndex':number});placed=True
    if not placed:
        # Explicit section attribution is honest when no exact quote anchor was
        # supplied. No fabricated position or whole-quotation identity is added.
        text=[]
        if fresh.get('verseKeys'):text.append('؛ '.join(quran_reference(key,language,names) for key in fresh['verseKeys']))
        text+=fresh.get('noteTexts',[])
        last=converted[-1];span=last.setdefault('spans',[{'text':last['text'],'role':last.get('role','body')}])[-1]
        if text:span.setdefault('noteTexts',[]).extend(text)
        if fresh.get('citations'):span.setdefault('citations',[]).extend(fresh['citations'])
        record['placement']='explicit source section attribution; no quote CP asserted'
    known_verses.update(meta.get('verseKeys',[]));known_citations.update((c['book'],c['number']) for c in meta.get('citations',[]))
    return record
