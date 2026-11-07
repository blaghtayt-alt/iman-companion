"""Format exact reviewed structured readers; no translation or approval creation.

Supports current entries maps, whole-reader unit packets and per-verse indexes.
Review eligibility/current precedence comes from the source-owner inventory.
Unknown source/reference/credit schemas fail explicitly instead of omitting a
reviewed surah from a supposedly complete book.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,re,unicodedata
from book_edition_scope import pinned,review_catalog_id,canonical
from quran_scope import canonical_surah
from bibliography import native_text,expand_verse_key,digits
from locale_copy import locale
from build_books import check_unit
from book_references import project_block,reference
from book_scope_copy import AVAILABLE_AYAHS
from book_reference_projection import index_projection,place as place_reference_projection

def sha(raw):return hashlib.sha256(raw).hexdigest()
ROLES={'plain':'body','meaning':'body','example':'body','body':'body','note':'note','related':'related','related-ayah':'quran','current-ayah':'current-ayah','quran':'quran','hadith':'hadith','scholar':'scholar','heading':'heading'}

def reviewed_record(root,declaration,row):
    records=[]
    for binding in declaration.get('sourceReviewBindings',[]):
        data=json.loads(pinned(root,binding))
        if data.get('schema')!='iman-existing-source-review-bindings-v1':continue
        records += [(record,binding) for record in data.get('records',[]) if (record.get('collection'),record.get('language'),review_catalog_id(record))==('tadabbur',row['language'],str(row['id']))]
    if len(records)!=1:raise ValueError('Exact whole-reviewed current Quran record is missing or ambiguous: '+str(row['id']))
    return records[0]

def canonical_words(text):
    text=unicodedata.normalize('NFKD',text).translate(str.maketrans('أإآٱ','اااا'))
    return ''.join(c for c in text if not unicodedata.category(c).startswith('M') and not c.isspace() and not c.isdigit() and c not in '﴿﴾۝')

def verse_ranges(keys,language,label):
    numbers=[int(k.split(':')[1]) for k in keys];ranges=[]
    for number in numbers:
        if ranges and ranges[-1][-1]+1==number:ranges[-1].append(number)
        else:ranges.append([number])
    return label+' '+', '.join(digits(str(r[0]),language)+('–'+digits(str(r[-1]),language) if len(r)>1 else '') for r in ranges)

def normalize(root,row,record,evidence,config):
    language=row['language'];surah=canonical_surah(row);bindings={}
    approved={b['path']:b['sha256'] for b in record['sourceFiles']+record['sourceConditions']}
    def bound(binding):
        raw=pinned(root,binding);bindings[binding['path']]=binding['sha256'];return json.loads(raw) if binding['path'].endswith('.json') else raw
    for item in record['sourceFiles']+record['sourceConditions']:bound(item)
    bound(evidence)
    source_path=row['json']
    if source_path not in approved:raise ValueError('Current reader is not in the exact reviewed source files')
    payload=bound({'path':source_path,'sha256':approved[source_path]})
    reference_projection=index_projection(bound(record['referenceProjection']),source_path,approved[source_path]) if record.get('referenceProjection') else {}
    quran=bound(config['quranText']);names=bound(config['surahNames'])
    name=names[language][surah-1];native_text(name,language);lc=locale(language)
    title=payload.get('title') or (lc['surahLabel']+' '+name)
    native_text(title,language)
    source_sections=[];entries=payload.get('entries')
    if isinstance(entries,dict):source_sections=[(key,value) for key,value in entries.items()]
    elif isinstance(payload.get('units'),list):source_sections=[(value['id'],value) for value in payload['units']]
    elif isinstance(entries,list):
        for entry in entries:
            path=(Path(source_path).parent/entry['json']).as_posix()
            if path not in approved:raise ValueError('Whole-review inventory does not pin per-verse reader: '+path)
            value=bound({'path':path,'sha256':approved[path]})
            if value.get('key')!=entry['key'] or value.get('language')!=language or value.get('surah')!=surah:raise ValueError('Per-verse reader identity differs from its exact index')
            source_sections.append((entry['key'],value['unit']))
    else:raise ValueError('Unsupported exact reviewed Quran reader schema: '+source_path)
    if not source_sections:raise ValueError('Reviewed reader contains no source sections')
    source_keys=[key for key,_ in source_sections]
    if len(source_keys)!=len(set(source_keys)):raise ValueError('Duplicate reviewed source section')
    intro=[(key,value) for key,value in source_sections if key=='intro' or key.startswith('intro:')]
    verses=[(key,value) for key,value in source_sections if re.fullmatch(r'\d+:\d+',key)]
    if len(intro)+len(verses)!=len(source_sections):raise ValueError('Unrecognized source section identity; no content was omitted')
    if any(key not in quran or int(key.split(':')[0])!=surah for key,_ in verses):raise ValueError('Source ayah outside its canonical surah')
    verses.sort(key=lambda item:int(item[0].split(':')[1]))
    if not verses:raise ValueError('Reviewed Quran source has no ayah sections')
    expected_coverage=record.get('bookCoverage')
    if expected_coverage is not None and expected_coverage!={'ayahKeys':[key for key,_ in verses],'introductionSectionIds':[key for key,_ in intro]}:raise ValueError('Current reader coverage differs from the source-owner disposition')
    changes=[];source_prose=[];formatted_prose=[];used_notes=set();missing_references=[];mandatory_notes=[];mandatory_qualifications=[];scope_notes=[]
    source_by_key=dict(source_sections)
    for disposition in record.get('bookSpanDispositions',[]):
        span=source_by_key[disposition['section']]['blocks'][disposition['block']]['spans'][disposition['span']]
        if sha(span['text'].encode())!=disposition['textSHA256'] or span.get('verseKeys')!=disposition['originalVerseKeys']:raise ValueError('Source quote-identity disposition differs from its exact input')
        if any(key not in quran for key in disposition['verseKeys']):raise ValueError('Disposition points outside canonical Quran')
        span['verseKeys']=disposition['verseKeys'];changes.append({**disposition,'source':'source-owner-bounded-quote-identity','literalQuote':span['text']})
    removals={}
    for projection in record.get('bookPresentation',[]):
        entry=source_by_key[projection['section']];block=entry['blocks'][projection['block']]
        if sha(block['text'].encode())!=projection['textSHA256']:raise ValueError('Source furniture projection changed')
        if projection['kind']=='source-scope-note':
            if projection['beforeSection'] not in dict(verses):raise ValueError('Source-scope note has no actual target section')
            native_text(projection['label'],language)
            scope_notes.append({'beforeSection':projection['beforeSection'],'label':projection['label'],'text':native_text(block['text'],language),'sourceSection':projection['section'],'sourceBlock':projection['block'],'sourceTextSHA256':projection['textSHA256']})
        elif projection['kind']!='structural-source-title':raise ValueError('Unknown source furniture projection')
        changes.append({**projection,'originalLiteral':block['text'],'source':'source-owner-bounded-book-furniture'})
        removals.setdefault(projection['section'],set()).add(projection['block'])
    for key,indices in removals.items():source_by_key[key]['blocks']=[b for i,b in enumerate(source_by_key[key]['blocks']) if i not in indices]
    notes={}
    for note in payload.get('readerNotes',[]):
        if not isinstance(note,dict) or not isinstance(note.get('text'),str):raise ValueError('Unsupported published reader-note schema')
        ident=note.get('id') or sha(note['text'].encode())
        if ident in notes:raise ValueError('Duplicate source note ID')
        notes[ident]=note
    def note_text(ident):
        if ident not in notes:raise ValueError('Required source meaning/qualification note is missing: '+str(ident))
        used_notes.add(ident);return native_text(notes[ident]['text'],language)
    def convert(block,key,index):
        if block.get('kind')=='source' and language=='ar' and block['text']=='النص القرآني: مشروع تنزيل — Tanzil':
            # Bibliographic project name already occurs natively in this exact
            # source credit. Preserve the full bilingual source in the ledger;
            # the ordinary Arabic footnote uses that same native project name.
            native='النص القرآني: مشروع تنزيل'
            changes.append({'section':key,'block':index,'source':'native-source-project-credit','sourceLiteral':block['text'],'sourceTextSHA256':sha(block['text'].encode()),'visibleNativeCredit':native,'originalSourceCreditRetained':True})
            return {'kind':'note','text':native,'role':'note'}
        original=deepcopy(block);source_prose.append(block['text'])
        for field,value in block.items():
            if isinstance(value,dict) and value.get('mandatoryInEveryDetachedReadingAndExport')is True:
                if not value.get('text') or value['text'] not in block['text']:raise ValueError('Mandatory detached-reading qualification missing from its actual source block')
                mandatory_qualifications.append({'section':key,'block':index,'field':field,'id':value.get('id'),'textSHA256':sha(value['text'].encode())})
        block,moves=project_block(deepcopy(block),language,names,quran)
        changes.extend({'section':key,'block':index,**move} for move in moves)
        text=block['text']
        kind=block.get('kind','paragraph')
        if kind in {'qualification','source'}:kind='paragraph'
        if kind not in {'paragraph','heading','list-item','quotation','note'}:raise ValueError('Unsupported reviewed prose kind: '+str(kind))
        spans=deepcopy(block.get('spans') or [{'text':text,'role':block.get('role','body')}])
        if ''.join(s['text'] for s in spans)!=text:raise ValueError('Exact source span text differs from its paragraph')
        for span in spans:
            if span.get('role','body') not in ROLES:raise ValueError('Unrecognized source semantic role')
            span['role']=ROLES[span.get('role','body')]
            for verse in span.get('verseKeys',[]):
                if any(k not in quran for k in expand_verse_key(verse)):raise ValueError('Supporting Quran reference outside canonical text')
            for ident in span.pop('requiredPublishedNoteIds',[]):span.setdefault('noteTexts',[]).append(note_text(ident))
        for ident in block.get('requiredPublishedNoteIds',[])+block.get('requiredNonQuranPublishedNoteIds',[]):
            if ident not in used_notes:spans[-1].setdefault('noteTexts',[]).append(note_text(ident))
        # All existing typed identities and qualifications survive unchanged.
        # Unstructured source identities need a source-bound reference projection;
        # no website record slug is interpreted as a Hadith narration number.
        for citation in block.get('citations',[]):
            if citation.get('type')=='hadith':spans[-1].setdefault('citations',[]).append(deepcopy(citation))
            else:missing_references.append({'section':key,'block':index,'reference':citation})
        formatted_prose.append(''.join(s['text'] for s in spans))
        result={'kind':kind,'text':text,'spans':spans,'sourceBlockIndex':index}
        expected=source_prose[-1]
        for move in reversed(moves):expected=expected[:move['start']]+expected[move['end']:]
        if expected!=formatted_prose[-1]:raise ValueError('Source prose or quotation words changed')
        return result
    sections=[];main_changes=[]
    for key,entry in intro+verses:
        source_blocks=entry.get('blocks',[])
        if not source_blocks:raise ValueError('Empty reviewed section: '+key)
        converted=[]
        if key in quran:
            main=next((i for i,b in enumerate(source_blocks) if b.get('kind') in {'ayah','translation'}),None)
            if main is None:raise ValueError('Reviewed main verse/translation is missing: '+key)
            if main:
                # Some current schemas embed a literal introduction before the
                # first ayah inside that ayah's entry. Keep it in source order.
                sections.append({'blocks':[convert(b,key,i) for i,b in enumerate(source_blocks[:main])]})
            first=source_blocks[main]
            converted.append({'kind':'ayah','verseKey':key,'text':quran[key],'role':'current-ayah'})
            if language=='ar':
                if first.get('kind')!='ayah':raise ValueError('Arabic main ayah block is missing: '+key)
                main_changes.append({'verseKey':key,'sourceTextSHA256':sha(first['text'].encode()),'sourceText':first['text'],'canonicalTextSHA256':sha(quran[key].encode()),'sourceOrthographyEqual':canonical_words(first['text'])==canonical_words(quran[key]),'presentation':'Exact pinned canonical Arabic text for the current source section key. Reviewed source verse remains literal in the pinned input and this ledger; commentary words unchanged.'})
            else:
                credit=record.get('quranCredit') or payload.get('quranCredit')
                if not isinstance(credit,dict) or credit.get('language')!=language or not credit.get('text'):raise ValueError('Actual localized translator/edition credit is missing: '+str(row['id']))
                native_text(credit['text'],language)
                translated={'kind':'translation','text':first['text'],'role':'current-ayah','translationCredit':deepcopy(credit)}
                if first.get('spans'):translated['spans']=deepcopy(first['spans'])
                required=first.get('requiredPublishedNoteIds',[])+first.get('requiredNonQuranPublishedNoteIds',[])
                if required:
                    spans=translated.setdefault('spans',[{'text':translated['text'],'role':'current-ayah'}])
                    for ident in required:spans[-1].setdefault('noteTexts',[]).append(note_text(ident))
                converted.append(translated)
            tail=source_blocks[main+1:]
        else:tail=source_blocks
        tail_start=main+1 if key in quran else 0
        for i,block in enumerate(tail,start=tail_start):converted.append(convert(block,key,i))
        section={'blocks':converted}
        if entry.get('heading'):section['heading']=entry['heading']
        if key in quran:section['ayahKey']=key
        sections.append(section)
        last=converted[-1];last_span=lambda:last.setdefault('spans',[{'text':last['text'],'role':last.get('role','body')}])[-1]
        for note in entry.get('mandatoryReadingNotes',[]):
            if not isinstance(note,dict) or not isinstance(note.get('text'),str) or note.get('key',key)!=key:raise ValueError('Invalid mandatory reader-note identity')
            if note.get('textSHA256') and sha(note['text'].encode())!=note['textSHA256']:raise ValueError('Mandatory reader-note text hash differs')
            if note.get('anchorCommentarySHA256'):
                anchor=''.join(b['text'] for b in source_blocks[main+1:])
                if sha(anchor.encode())!=note['anchorCommentarySHA256']:raise ValueError('Mandatory reader-note whole-commentary anchor differs')
            last_span().setdefault('noteTexts',[]).append(native_text(note['text'],language))
            mandatory_notes.append({'section':key,'id':note.get('id'),'textSHA256':sha(note['text'].encode()),'anchorCommentarySHA256':note.get('anchorCommentarySHA256'),'placement':'native Word footnote at this section commentary end'})
        # The source's moved lecture/source lines are meaning-bearing metadata,
        # not discarded because they no longer occur in the displayed prose.
        if isinstance(entry.get('source'),str) and entry['source'].startswith('المصدر:'):
            last_span().setdefault('noteTexts',[]).append(native_text(entry['source'],language))
        known_citations={(c['book'],c['number']) for b in converted for span in b.get('spans',[]) for c in span.get('citations',[])}
        known_verses={v for b in converted for span in b.get('spans',[]) for v in span.get('verseKeys',[])}
        metadata=[('citations',i,value) for i,value in enumerate(entry.get('citations',[]))]+[('references',i,{'reference':value}) for i,value in enumerate(entry.get('references',[]))]
        for field,number,citation in metadata:
            if citation.get('reference')==key:continue
            projection=reference_projection.get((key,field,number))
            if projection:
                changes.append(place_reference_projection(projection,citation,entry,converted,language,names,quran,known_verses,known_citations));continue
            binding={'citations':[deepcopy(citation)]} if citation.get('type')=='hadith' else reference(citation.get('canonicalReference') or citation.get('reference') or citation.get('label'),language,names,quran)
            if binding and binding.get('citations'):
                fresh=[c for c in binding['citations'] if (c['book'],c['number']) not in known_citations]
                if fresh:
                    last_span().setdefault('citations',[]).extend(fresh);known_citations.update((c['book'],c['number']) for c in fresh)
            elif binding and binding.get('verseKeys') and set(binding['verseKeys']).issubset(known_verses):continue
            else:missing_references.append({'section':key,'reference':citation})
    # Unanchored meaning notes and glossary terms remain literal native Word
    # footnotes; no source note is silently dropped to make pagination easier.
    remaining=[native_text(note['text'],language) for ident,note in notes.items() if ident not in used_notes]
    for item in payload.get('glossary',[]):
        if not isinstance(item,dict) or not item.get('term') or not item.get('meaning'):raise ValueError('Unsupported reviewed glossary schema')
        remaining.append(native_text(item['term']+': '+item['meaning'],language))
    last=sections[-1]['blocks'][-1]
    if remaining:last.setdefault('spans',[{'text':last['text'],'role':last.get('role','body')}])[-1].setdefault('noteTexts',[]).extend(remaining)
    keys=[key for key,_ in verses];canonical_keys=sorted([key for key in quran if key.startswith(str(surah)+':')],key=lambda key:int(key.split(':')[1]))
    coverage={'schema':'iman-reviewed-quran-coverage-v1','surah':surah,'ayahKeys':keys,
      'introduction':{'state':'included','readerTextSHA256':sha(''.join(b['text'] for s in sections if not s.get('ayahKey') for b in s['blocks']).encode())} if any(not s.get('ayahKey') for s in sections) else {'state':'not-in-reviewed-material'}}
    if keys!=canonical_keys:
        coverage['scopeLabel']=AVAILABLE_AYAHS[language];title+=' · '+coverage['scopeLabel']
    reader=''.join(b['text'] for section in sections for b in section['blocks'])
    revision=row.get('sourceHashes') or [record.get('sourceRevisionSHA256') or approved[source_path]]
    semantic_spans=[span for s in sections for b in s['blocks'] if b['kind'] not in {'ayah','translation'} for span in b.get('spans',[])]
    unbound_quran=sum(span.get('role')=='quran' and not span.get('verseKeys') for span in semantic_spans)
    unbound_hadith=sum(span.get('role')=='hadith' and not span.get('citations') for span in semantic_spans)
    unbound_scholar=sum(span.get('role')=='scholar' and not (span.get('sourceCitationBound') or span.get('citations')) for span in semantic_spans)
    unit={'schema':'iman-book-unit-v1','id':str(row['id']),'language':language,'collection':'tadabbur-extended','surah':surah,'order':surah,
      'title':title,'complete':True,'reviewGate':'published-current','sourceHashes':revision,
      'inputBindings':[{'path':p,'sha256':h} for p,h in sorted(bindings.items())],
      'catalogBindings':[{'collection':'tadabbur','language':language,'id':row['id']}],'sections':sections,'reviewedCoverage':coverage,
      'coverageLabel':verse_ranges(keys,language,lc['ayahLabel']) if keys!=canonical_keys else None,
      'sourceScopeNotes':scope_notes,
      'readerTextSHA256':sha(reader.encode()),'referenceReadiness':{'unboundQuranSegments':unbound_quran,'unboundHadithSegments':unbound_hadith,'unboundScholarSegments':unbound_scholar,'unresolvedSourceReferenceCount':len(missing_references),'unresolvedSourceReferences':missing_references},
      'provenance':{'adapter':'reviewed-structured-quran-v1','sourceRecordSHA256':sha(canonical(record)),'sourceOwnerWholeReview':record['existingWholeReview'],
        'historicalPublication':record['historicalPublication'],'sourceConditions':record['sourceConditions'],'sourceJSON':source_path,
        'allProseAndQuotationCharactersPreserved':True,'sourceProseSHA256':sha(''.join(source_prose).encode()),'formattedProseSHA256':sha(''.join(formatted_prose).encode()),
        'mainAyahPresentation':main_changes,'referenceFurnitureTransformations':changes,'unanchoredSourceNotes':len(remaining),'mandatoryReadingNotes':mandatory_notes,'mandatoryDetachedQualifications':mandatory_qualifications,'sourceApprovalCreated':False}}
    check_unit(unit,{'id':unit['id'],'language':language,'collection':'tadabbur-extended'},quran)
    return unit

def generate(root,catalog,declaration):
    from book_edition_scope import select
    selected,_=select(root,catalog,declaration);output=[]
    config=json.loads((root/'books/config.json').read_bytes())
    for row in selected:
        if row.get('bookReaderUnit'):continue # exact publisher units are indexed directly
        if canonical_surah(row)==112:
            legacy=deepcopy(declaration)
            if declaration['language']=='ar':
                from adapt_ar_ikhlas import generate as old
                legacy['adapter']='arabic-current-ikhlas-v1'
            else:
                from adapt_ikhlas import generate as old
                legacy['adapter']='reviewed-ikhlas-v1'
            units=old(root,catalog,legacy)
            for unit in units:unit.setdefault('order',112)
            output.extend(units);continue
        record,evidence=reviewed_record(root,declaration,row)
        output.append(normalize(root,row,record,evidence,config))
    return output
