"""Normalize the existing reviewed whole Ikhlas source units without translation.

Current target words and published notes are retained. A pinned shared original
revision supplies citation identities; it never supplies target-language prose.
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib,json,re,unicodedata
from build_books import check_unit,inside
from bibliography import native_text,expand_verse_key

REVISION='12cf622c81771c36561eb3b7112f4ff88d6f6f16530041eed3f69f1475cacda8'
MASTER='materials/tadabbur/sources/112/ja/IKHLAS-JA-PUBLIC-SOURCES745.json'
BOOKS={'Bukhari':'bukhari','Muslim':'muslim','IbnMajah':'ibnmajah','AbuDawud':'abudawud','Ahmad':'ahmad','Tirmidhi':'tirmidhi','Nasai':'nasai'}
# Verified against the named full publisher record and the original collection.
# These identify an actual selected target parent, not a generic website ID.
PARENT_CITATIONS={
    'HE:65261':{'type':'hadith','book':'bukhari','number':'5013'},
    'HadeethEnc:5541':{'type':'hadith','book':'bukhari','number':'5742'},
}
NUMBERING={'en':'numbering in the translation source','ur':'ترجمے کے ماخذ کی نمبرنگ','id':'penomoran sumber terjemahan','ms':'penomboran sumber terjemahan','bn':'অনুবাদের উৎসের নম্বরায়ন','tr':'çeviri kaynağındaki numaralandırma','fr':'numérotation de la source traduite','pt-BR':'numeração da fonte da tradução','hi':'अनुवाद के स्रोत की क्रम संख्या','ru':'нумерация источника перевода','es':'numeración de la fuente de traducción','fa':'شماره‌گذاری منبع ترجمه','de':'Nummerierung der Übersetzungsquelle','zh-CN':'译文来源编号','uz':'tarjima manbasidagi raqamlanish','th':'หมายเลขตามแหล่งคำแปล','vi':'số theo nguồn bản dịch','ja':'翻訳出典での番号','fil':'bilang sa pinagmulan ng salin'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_bytes())

def common_bindings(root,expected_hash):
    file=inside(root,MASTER);raw=file.read_bytes()
    if sha(raw)!=expected_hash:raise ValueError('Shared original citation map changed')
    data=json.loads(raw)
    if data.get('Arabic_revision')!=REVISION:raise ValueError('Shared citation map belongs to a different original')
    result={}
    for row in data['current67_exact_bindings']['occurrences']:
        ident=row['binding']
        if ident in result:raise ValueError('Ambiguous shared citation identity')
        if ident.startswith('Q:'):
            reference=row['reference'];expand_verse_key(reference);result[ident]={'verseKeys':[reference]}
        else:
            identity=data['nonQ_selected17'][ident]['actual_identity']
            citations=[]
            for match in re.finditer(r'(Bukhari|Muslim|IbnMajah|AbuDawud|Ahmad|Tirmidhi)\s*(\d+)([a-z]?)',identity):
                item={'type':'hadith','book':BOOKS[match[1]],'number':match[2]}
                if item not in citations:citations.append(item)
            if citations:result[ident]={'citations':citations}
            elif ident in {'N:34','N:49','N:131'}:
                # Historical report, lexical example and anonymous proverb are
                # explicitly not promoted to Prophetic Hadith.
                result[ident]={'nonHadith':True}
            else:raise ValueError('Original quotation lacks verified collection/number: '+ident)
    if len(result)!=67:raise ValueError('Original quotation map coverage changed')
    return result

def sentence_text(sentence):
    text=''.join(s['text'] for s in sentence['segments'])
    if sentence.get('text') is not None and sentence['text']!=text:raise ValueError('Published sentence segments differ from its text')
    return text
def paragraph_text(paragraph):
    if paragraph.get('text') is not None:return paragraph['text']
    return ' '.join(sentence_text(s) for s in paragraph.get('sentences',[]))

def native_credit(value,language):
    if not isinstance(value,str) or not value.strip():raise ValueError('Published translation attribution is missing')
    # Remove retrieval-service furniture, retaining actual translator/publisher
    # names. This never touches a Quran translation, prose or publisher note.
    value=re.sub(r'\s*[/،,;]?\s*QuranEnc(?:\.com)?(?:\s+\d+(?:\.\d+)*)?', '', value,flags=re.I)
    if language=='hi':value=value.split('हदीसों')[0].rstrip()
    return native_text(value.strip(),language)

def binding_aliases(paragraphs,common):
    order=[]
    for paragraph in paragraphs:
        for sentence in paragraph.get('sentences',[]):
            for segment in sentence['segments']:
                ident=segment.get('binding')
                if ident and ident not in order:order.append(ident)
    aliases={ident:common[ident] for ident in order if ident in common}
    split_q=[i for i in order if re.fullmatch(r'Q:103(?::\d+|[ab])',i)]
    if split_q:
        if len(split_q)!=2:raise ValueError('Split Maryam quotation coverage changed')
        for ident,key in zip(split_q,['19:90','19:91']):aliases[ident]={'verseKeys':[key]}
    for ident in order:
        if ident in aliases:continue
        match=re.fullmatch(r'(N:\d+)(?::\d+|[ab])',ident)
        if not match or match[1] not in common:raise ValueError('Unknown original quotation identity: '+ident)
        aliases[ident]=common[match[1]]
    return aliases

def note_rows(units):
    notes={}
    for unit in units:
        for key in ['publisherNotes','contextNotes']:
            for row in unit.get(key,[]):
                if not isinstance(row,dict) or not row.get('text'):raise ValueError('Invalid published note')
                ident=row.get('id') or sha(row['text'].encode())
                if ident in notes and notes[ident]['text']!=row['text']:raise ValueError('Conflicting published note identity')
                if ident not in notes:notes[ident]=deepcopy(row)
    return notes

def note_display_text(row):
    """Render the one source-declared break sequence without parsing HTML.

    The reviewed French note explicitly identifies its three ``<br />``
    tokens as paragraph-break metadata. Keep its original row and every word
    intact, and turn only those exact tokens into native Word breaks. The
    complete text and metadata pins prevent this exception from applying to
    another note, a changed qualification, or arbitrary publisher markup.
    """
    text=row['text']
    if row.get('id')!='quran-2-3-fullnote':return text
    metadata={'id':'quran-2-3-fullnote','type':'publisher_meaning_note','verse':'2:3',
        'required_for':[{'binding':'Q:74','sentence':'p08.s36'}],
        'scope':'Complete original single note field, verse-local marker; embedded <br /> is inert explicit paragraph-break metadata, never arbitrary HTML. No note text omitted.'}
    if ({key:value for key,value in row.items() if key!='text'}!=metadata
            or sha(text.encode())!='e259c0a50b6d4b559b9d4c01dc35c3e9d259f5f42f5c8fe71b8877e35652ed3c'
            or text.count('<br />')!=3 or '\n' in text):
        raise ValueError('Source-declared French note breaks differ from their exact reviewed binding')
    display=text.replace('<br />','\n')
    if display.replace('\n','<br />')!=text:
        raise ValueError('Source note break projection is not reversible')
    return display

def target_citation_rows(payloads,paragraphs,language,native_books):
    """Use explicit target-source bindings for published parallel report identities.

    Only a typed binding/inventory record with the selected target text qualifies.
    Arbitrary numbers in source narratives or website record IDs are never used.
    """
    wanted={}
    for p in paragraphs:
        for s in p.get('sentences',[]):
            for seg in s['segments']:
                ident=seg.get('binding','')
                if ident.startswith('N:'):wanted.setdefault(re.match(r'N:\d+',ident)[0],[]).append(seg)
    found={}
    def add(ident,record,path):
        reference=record.get('actual_identity') or record.get('reference') or record.get('sourceReference')
        if not isinstance(reference,str):return
        text=record.get('text')
        if text and not all(s['text'] in text or text in s['text'] for s in wanted[ident]):return
        citations=[];parent=str(record.get('parent',''))
        # A selected parallel is not silently relabelled as the original Arabic
        # report. Source records explicitly distinguish the two identities.
        selected_reference=re.split(r'\boriginal(?=[A-Z\s])',reference,flags=re.I)[0]
        for match in re.finditer(r'(Bukhari|Muslim|Ibn\s*Majah|Abu\s*Dawud|Ahmad|Tirmidhi|Nasai)\s*:?[ ]*(\d+)([a-z](?![a-z]))?',selected_reference):
            name=match[1].replace(' ','');number=match[2];tail=selected_reference[match.end():]
            standard=re.match(r'publisher(?:number)?\s*/\s*(\d+)(?:standard|original|currentArabic)',tail)
            if standard:number=standard[1]
            cite={'type':'hadith','book':BOOKS[name],'number':number}
            if parent.startswith('INDEX:') and not standard:
                cite['qualification']={'language':language,'text':NUMBERING[language]}
            citations.append(cite)
        if not citations and parent in PARENT_CITATIONS:citations.append(deepcopy(PARENT_CITATIONS[parent]))
        if not citations:
            work=re.search(r'Riyad(?:ussalihin)?(\d+)',parent+' '+selected_reference)
            title=next((name for name in native_books if re.search('Riyoz|Riyad|Riyadh',unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode(),re.I)),None)
            if work and title:
                citations.append({'type':'hadith','book':'riyad','localizedTitles':{language:native_text(title,language)},'number':work[1]})
        if citations:
            row=found.setdefault(ident,{'citations':[],'evidence':[]})
            for cite in citations:
                if not any((c['book'],c['number'])==(cite['book'],cite['number'])for c in row['citations']):row['citations'].append(cite)
            row['evidence'].append({'path':path,'reference':reference})
        if any(s.get('type')=='quran_quoted_in_report'for s in wanted[ident]):
            match=re.search(r'Quran\s*(\d+:\d+(?:[-–]\d+)?)',parent)
            if match:
                expand_verse_key(match[1]);found.setdefault(ident,{'citations':[],'evidence':[]})['verseKeys']=[match[1]]
    def walk(value,path='',identity=None):
        if isinstance(value,dict):
            ident=value.get('binding',value.get('id',identity))
            if isinstance(ident,str):
                match=re.match(r'N:\d+',ident);ident=match[0] if match else None
            else:ident=None
            if ident in wanted:add(ident,value,path)
            number=value.get('inventory_index',value.get('index'))
            if type(number)is int and re.search('nonq|all26',path,re.I) and 'N:'+str(number) in wanted:
                ident='N:'+str(number)
                for key,row in value.items():
                    if isinstance(row,dict) and any(word in key.lower() for word in ['selection','selected','decision']):add(ident,row,path+'.'+key)
            for key,row in value.items():walk(row,path+'.'+key,key if key in wanted else None)
        elif isinstance(value,list):
            for i,row in enumerate(value):walk(row,path+f'[{i}]')
    for name,payload in payloads.items():walk(payload,name)
    for ident,segments in wanted.items():
        if any('parallel' in s.get('type','')for s in segments) and not found.get(ident,{}).get('citations'):raise ValueError('Published parallel quotation lacks target-specific original collection metadata: '+ident)
    return found

def preservation_evidence(paragraphs,rendered_paragraphs,aliases,notes,sections):
    """Audit actual output against the already-verified current source reading.

    A split quotation shares one report citation, while each explicit Quran
    binding retains its verse keys. Non-Hadith examples remain ordinary prose.
    This reports the existing source proof; it creates no editorial approval.
    """
    source_paragraphs={p['id']:paragraph_text(p) for p in paragraphs}
    if len(source_paragraphs)!=len(paragraphs) or source_paragraphs!=rendered_paragraphs:
        raise ValueError('Current Ikhlas paragraphs were not completely preserved')
    def reference_keys(ident,meta):
        if meta.get('verseKeys'):
            yield ('quran',ident),json.dumps(meta['verseKeys'],sort_keys=True,ensure_ascii=False)
        if meta.get('citations'):
            family=re.match(r'N:\d+',ident)
            if not family:raise ValueError('Hadith citation has no original quotation binding')
            yield ('hadith',family[0]),json.dumps(meta['citations'],sort_keys=True,ensure_ascii=False)
    expected={key:value for ident,meta in aliases.items() for key,value in reference_keys(ident,meta)}
    rendered={};rendered_notes=[]
    for section in sections:
        for block in section['blocks']:
            for span in block.get('spans',[]):
                rendered_notes.extend(span.get('noteTexts',[]))
                ident=span.get('sourceBinding')
                if ident:
                    for key,value in reference_keys(ident,span):
                        if key in rendered and rendered[key]!=value:raise ValueError('Conflicting rendered Ikhlas source identity')
                        rendered[key]=value
    if expected!=rendered:raise ValueError('Current Ikhlas source references were not completely preserved')
    if Counter(note_display_text(row) for row in notes.values())!=Counter(rendered_notes):
        raise ValueError('Current Ikhlas publisher or contextual notes were not completely preserved')
    return {'schema':'iman-source-reference-preservation-v1',
            'auditMode':'literal-source-and-qualification-fidelity',
            'referenceIdentityBasis':'Existing verified quotation bindings and original collection/verse identities; split report fragments share their citation.',
            'sourceParagraphs':len(source_paragraphs),'preservedParagraphs':len(rendered_paragraphs),
            'sourceReferences':len(expected),'preservedReferences':len(rendered),
            'sourceQualifications':len(notes),'preservedQualifications':len(rendered_notes),
            'lostParagraphs':0,'lostReferences':0,'lostQualifications':0}

def generate(root,catalog,declaration):
    language=declaration['language']
    if declaration.get('adapter')!='reviewed-ikhlas-v1' or declaration.get('collection')!='tadabbur-extended' or language=='ar':raise ValueError('Unsupported reviewed Ikhlas scope')
    matches=[e for e in catalog['entries'] if (e.get('collection'),e.get('language'),e.get('surah'),e.get('mode'))==('tadabbur',language,112,'extended') and not e.get('archived') and e.get('current',True) is not False]
    if len(matches)!=1 or matches[0].get('translationStatus')!='independently-reviewed-whole-surah-translation' or matches[0].get('sourceHashes')!=[REVISION]:raise ValueError('Current reviewed whole Ikhlas publication is missing or changed')
    record=matches[0];bindings={}
    def bound(relative):
        file=inside(root,relative);raw=file.read_bytes();bindings[file.relative_to(root).as_posix()]=sha(raw);return json.loads(raw) if file.suffix=='.json' else raw
    common=common_bindings(root,declaration['citationMapSHA256']);bound(MASTER)
    prefix=f'materials/tadabbur/sources/112/{language}'
    source_units=[bound(f'{prefix}/112-{n:03d}.json') for n in range(1,5)];source_payloads={}
    quran=bound(declaration['quranText']['path'])
    if bindings[declaration['quranText']['path']]!=declaration['quranText']['sha256']:raise ValueError('Pinned Arabic Quran changed')
    allparagraphs=[];paths=set();credits=[]
    for n,unit in enumerate(source_units,1):
        if (unit.get('schema'),unit.get('language'),unit.get('verseKey'),unit.get('sourceRevision'))!=('ikhlas-reviewed-unit-v1',language,f'112:{n}',REVISION):raise ValueError('Reviewed source unit identity changed')
        allparagraphs.extend(unit['paragraphs'])
        credit=native_credit(unit['credits']['quran'],language)
        if credit not in credits:credits.append(credit)
        for name in unit['sourceFiles']:
            relative=(Path(prefix)/name).as_posix();payload=bound(relative)
            if isinstance(payload,(dict,list)):source_payloads[relative]=payload
        fullpath=inside(root,(Path(prefix)/unit['fullReading']).as_posix()).relative_to(root).as_posix();paths.add(fullpath)
    if paths!={record['json']}:raise ValueError('Source units do not identify the current published reading')
    full=bound(record['json']);published={p['id']:p for p in full['paragraphs']}
    if len(published)!=len(full['paragraphs']):raise ValueError('Duplicate published paragraph identity')
    # Several published reading schemas identify the locale and rely on their
    # canonical path plus the four reviewed verse units for the surah identity.
    allowed_locales={'es':{'es','es-ES'}}.get(language,{language})
    if full.get('locale',full.get('language')) not in allowed_locales or full.get('surah',112)!=112:raise ValueError('Current published reading identity changed')
    for p in allparagraphs:
        if p['id'] in published and paragraph_text(p)!=paragraph_text(published[p['id']]):raise ValueError('Reviewed unit differs from current published paragraph: '+p['id'])
    if not set(published).issubset({p['id']for p in allparagraphs}):raise ValueError('Reviewed units omit current published paragraphs')
    aliases=binding_aliases(allparagraphs,common);target_citations=target_citation_rows(source_payloads,allparagraphs,language,source_units[0]['credits'].get('books',[]))
    for ident in list(aliases):
        if not ident.startswith('N:'):continue
        family=re.match(r'N:\d+',ident)[0];target=target_citations.get(family)
        if target:
            base=aliases[ident];merged=deepcopy(target['citations'])
            if not merged:merged=deepcopy(base.get('citations',[]))
            aliases[ident]={**base,'citations':merged}
            if target.get('verseKeys'):aliases[ident]['verseKeys']=target['verseKeys']
    notes=note_rows(source_units);used=set();note_anchors=[];source_sentences=[];rendered_sentences=[];last_family={};rendered_paragraphs={}
    for p in allparagraphs:
        for s in p.get('sentences',[]):
            for seg in s['segments']:
                ident=seg.get('binding')
                if ident and ident.startswith('N:'):last_family[re.match(r'N:\d+',ident)[0]]=ident
    def matching_notes(sentence,segment):
        out=[];ident=segment.get('binding');keys=aliases.get(ident,{}).get('verseKeys',[])
        for key,row in notes.items():
            if key in used:continue
            required=row.get('required_for_bindings',row.get('required_for',[]))
            if isinstance(required,str):required=[required]
            exact=any((r==ident if isinstance(r,str) else r.get('binding')==ident and r.get('sentence',sentence)==sentence) for r in required)
            exact=exact or (row.get('binding') is not None and row['binding']==ident and row.get('sentence',sentence)==sentence)
            contextual=row.get('sentence')==sentence and not required and not row.get('binding')
            verse=(row.get('verse') or row.get('reference')) in keys and not required and not row.get('sentence') and not row.get('binding')
            if exact or contextual or verse:
                out.append(native_text(note_display_text(row),language));used.add(key)
                note_anchors.append({'id':key,'sentence':sentence,'binding':ident,'basis':'explicit-binding' if exact else 'explicit-sentence' if contextual else 'explicit-verse'})
        return out
    def convert(paragraph):
        text=paragraph_text(paragraph);spans=[];cursor=0;chunks=[];length=0
        for sentence in paragraph.get('sentences',[]):
            exact=sentence_text(sentence);position=text.find(exact,cursor)
            if position<cursor or text[cursor:position].strip():raise ValueError('Paragraph/sentence order changed')
            if position>cursor:spans.append({'text':text[cursor:position],'role':'body'})
            for segment in sentence['segments']:
                ident=segment.get('binding');meta=deepcopy(aliases.get(ident,{}));kind=segment.get('type','commentary')
                span={'text':segment['text'],'role':'quran' if (ident and ident.startswith('Q:') and 'grammar' not in kind) or kind=='quran_quoted_in_report' else 'hadith' if meta.get('citations') else 'body'}
                if ident:span['sourceBinding']=ident
                if meta.get('verseKeys'):span['verseKeys']=meta['verseKeys']
                if meta.get('citations') and ident==last_family[re.match(r'N:\d+',ident)[0]]:span['citations']=meta['citations']
                ns=matching_notes(sentence['id'],segment)
                if ns:span['noteTexts']=ns
                spans.append(span)
            cursor=position+len(exact);source_sentences.append(exact);rendered_sentences.append(''.join(x['text']for x in sentence['segments']));length+=len(exact)
            # Existing sentence boundaries produce book paragraphs without losing
            # a single source character or dividing protected quoted segments.
            if length>=700:
                chunks.append({'kind':'paragraph','text':''.join(x['text']for x in spans),'spans':spans});spans=[];length=0
        if text[cursor:].strip():raise ValueError('Unrepresented paragraph suffix')
        if text[cursor:]:spans.append({'text':text[cursor:],'role':'body'})
        if spans:chunks.append({'kind':'paragraph','text':''.join(x['text']for x in spans),'spans':spans})
        if ''.join(b['text']for b in chunks)!=text:raise ValueError('Source paragraph changed during book formatting')
        rendered_paragraphs[paragraph['id']]=''.join(b['text']for b in chunks)
        return chunks
    first=source_units[0]['paragraphs'];title=paragraph_text(first[0]);native_text(title,language);sections=[]
    subtitle=paragraph_text(first[1]);native_text(subtitle,language)
    rendered_paragraphs[first[0]['id']]=title;rendered_paragraphs[first[1]['id']]=subtitle
    if subtitle!=title:sections.append({'blocks':[{'kind':'paragraph','text':subtitle,'role':'body'}]})
    for index,unit in enumerate(source_units,1):
        ps=unit['paragraphs'];main=next((i for i,p in enumerate(ps) if p.get('kind')=='quran_heading'),None)
        if main is None or main==0:raise ValueError('Published main verse translation is missing')
        heading=paragraph_text(ps[main-1]);translation_blocks=convert(ps[main])
        rendered_paragraphs[ps[main-1]['id']]=heading
        if len(translation_blocks)!=1:raise ValueError('Main Quran translation was unexpectedly split')
        translation=translation_blocks[0];translation['kind']='translation';translation['translationCredit']={'language':language,'text':native_credit(unit['credits']['quran'],language)}
        blocks=[{'kind':'ayah','verseKey':f'112:{index}','text':quran[f'112:{index}'],'role':'current-ayah'},translation]
        for p in ps[main+1:]:
            if p.get('kind')!='commentary':raise ValueError('Unknown current source paragraph kind')
            blocks.extend(convert(p))
        sections.append({'heading':heading,'ayahKey':f'112:{index}','blocks':blocks})
    # Contextual/publisher notes with no explicit quote anchor remain real Word
    # footnotes on the final source sentence, never ordinary text below a lesson.
    remaining=[native_text(note_display_text(row),language) for ident,row in notes.items() if ident not in used]
    if remaining:sections[-1]['blocks'][-1]['spans'][-1].setdefault('noteTexts',[]).extend(remaining)
    reader=''.join(b['text']for s in sections for b in s['blocks'])
    unit={'schema':'iman-book-unit-v1','id':record['id'],'language':language,'collection':'tadabbur-extended','surah':112,'title':title,'complete':True,'reviewGate':'published-current','sourceHashes':[REVISION],'inputBindings':[{'path':p,'sha256':h}for p,h in sorted(bindings.items())],'catalogBindings':[{'collection':'tadabbur','language':language,'id':record['id']}],'translationCredits':[{'language':language,'text':c}for c in credits],'sections':sections,'readerTextSHA256':sha(reader.encode()),'provenance':{'adapter':'reviewed-ikhlas-v1','sourceSentences':len(source_sentences),'exactSentenceWordsPreserved':source_sentences==rendered_sentences,'sourceNotes':len(notes),'explicitlyAnchoredNotes':len(used),'lessonLevelNotes':len(remaining),'fullCurrentReading':record['json'],'wholeSurahAyahs':4,'originalCitationMap':{'path':MASTER,'sha256':declaration['citationMapSHA256']}}}
    unit['provenance']['targetCitationBindings']={ident:row['evidence']for ident,row in target_citations.items()}
    unit['provenance']['noteAnchors']=note_anchors
    presentation=[{'id':ident,'sourceTextSHA256':sha(row['text'].encode()),
        'displayTextSHA256':sha(note_display_text(row).encode()),
        'sourceSemantics':row['scope'],'sourceToken':'<br />',
        'nativeWordBreaks':3,'exactSourceReconstruction':True}
        for ident,row in notes.items() if note_display_text(row)!=row['text']]
    if presentation:unit['provenance']['sourceNotePresentation']=presentation
    unit['sourceReferencePreservation']=preservation_evidence(allparagraphs,rendered_paragraphs,aliases,notes,sections)
    check_unit(unit,{'id':record['id'],'language':language,'collection':'tadabbur-extended'},quran)
    return [unit]
