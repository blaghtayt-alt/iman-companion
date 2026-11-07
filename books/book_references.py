"""Project explicitly written original-source references into native furniture.

Only named collections with an actual narration number become Hadith citations.
URL record IDs are never parsed. Protected quotation/prose words are not edited.
"""
import re,unicodedata
from locale_copy import locale
from bibliography import native_text

ALIASES={
'bukhari':['البخاري','صحيح البخاري','Bukhari','al-Bukhari','Sahih al-Bukhari'],
'muslim':['مسلم','صحيح مسلم','Muslim','Sahih Muslim'],
'ahmad':['أحمد','مسند أحمد','Ahmad','Musnad Ahmad'],
'abudawud':['أبو داود','أبي داود','سنن أبي داود','Abu Dawud','Abi Dawud','Sunan Abi Dawud'],
'tirmidhi':['الترمذي','جامع الترمذي','Tirmidhi','at-Tirmidhi','al-Tirmidhi','Jami al-Tirmidhi'],
'nasai':['النسائي','سنن النسائي','Nasai','al-Nasai','an-Nasai'],
'ibnmajah':['ابن ماجه','سنن ابن ماجه','Ibn Majah'],
'ibnhibban':['ابن حبان','صحيح ابن حبان','Ibn Hibban'],
'malik':['موطأ مالك','الموطأ','Muwatta','Al-Muwatta']}

def folded(text):
    chars=[];positions=[]
    for i,char in enumerate(text):
        for part in unicodedata.normalize('NFKD',char).casefold():
            if unicodedata.category(part).startswith('M'):continue
            if part in 'أإآٱ':part='ا'
            if part.isdigit():part=str(unicodedata.digit(part))
            chars.append(part);positions.append(i)
    return ''.join(chars),positions

def reference(text,language,names,quran):
    if not isinstance(text,str) or re.search(r'https?://|www[.]',text,re.I):return None
    value,positions=folded(text);aliases={}
    for book,labels in ALIASES.items():
        for label in labels+[locale(language)['hadithBooks'][book]]:aliases[folded(label)[0]]=book
    books='|'.join(re.escape(label) for label in sorted(aliases,key=len,reverse=True))
    pattern=re.compile(r'(?<!\w)('+books+r')\s*[:،,№#(（]?\s*(\d+(?:\s*[-–/:]\s*\d+)*)(?!\d)',re.I)
    matches=list(pattern.finditer(value));citations=[]
    if matches:
        residual=[];cursor=0
        for match in matches:
            start=positions[match.start()];end=positions[match.end()-1]+1
            residual.append(text[cursor:start]);cursor=end
            cite={'type':'hadith','book':aliases[match[1]],'number':re.sub(r'\s+','',match[2])}
            if cite not in citations:citations.append(cite)
        residual.append(text[cursor:]);qualification=''.join(residual)
        qualification=re.sub(r'\b(?:رواه|أخرجه|اخرجه)\b','',qualification).strip(' []()（）؛;،,:. ').strip()
        if qualification:citations[0]['qualification']={'language':language,'text':native_text(qualification,language)}
        return {'citations':citations}
    # A standalone, explicitly named surah reference is a Quran identity.
    # A scholar/tafsir/book prefix is retained as a source note instead.
    surahs={}
    for lang in {'ar',language}:
        for number,name in enumerate(names.get(lang,[]),1):
            if name:surahs[folded(name)[0]]=number
    for name in sorted(surahs,key=len,reverse=True):
        match=re.fullmatch(r'\s*(?:سورة\s+)?'+re.escape(name)+r'\s*[:،,]\s*(\d+(?:\s*[-–]\s*\d+)?(?:\s*[،,]\s*\d+(?:\s*[-–]\s*\d+)?)*)\s*[.،,]?\s*',value)
        if not match:continue
        keys=[]
        for item in re.split('[،,]',match[1]):
            pieces=re.split('[-–]',item);start=int(pieces[0]);end=int(pieces[-1])
            if end<start:return None
            for ayah in range(start,end+1):
                key=f'{surahs[name]}:{ayah}'
                if key not in quran:return None
                keys.append(key)
        return {'verseKeys':keys}
    return None

def project_block(block,language,names,quran):
    """Reinstate source's already-moved reference anchors, or move literal ones."""
    text=block['text'];spans=block.get('spans') or [{'text':text,'role':block.get('role','body')}]
    if ''.join(s['text'] for s in spans)!=text:raise ValueError('Source spans differ before reference formatting')
    moves=[];presentation=block.get('bibliographyPresentation')
    if presentation:
        original=presentation['originalText'];ranges=presentation['removedRanges'];cursor=0;rebuilt='';shift=0
        for start,end in ranges:
            if type(start)is not int or type(end)is not int or not cursor<=start<end<=len(original):raise ValueError('Invalid original bibliography range')
            rebuilt+=original[cursor:start];literal=original[start:end];binding=reference(literal.strip(' []()（）'),language,names,quran)
            if binding is None:binding={'noteTexts':[native_text(literal.strip(' []()（）'),language)]}
            moves.append({'start':len(rebuilt),'end':len(rebuilt),'literal':literal,'binding':binding,'source':'already-moved-bibliography'})
            cursor=end
        rebuilt+=original[cursor:]
        if rebuilt!=text:raise ValueError('Bibliography presentation does not reconstruct exact current prose')
    else:
        for match in re.finditer(r'\[[^\]\n]{1,260}\]|\([^()\n]{1,260}\)|（[^（）\n]{1,260}）',text):
            binding=reference(match[0][1:-1],language,names,quran)
            if binding:moves.append({'start':match.start(),'end':match.end(),'literal':match[0],'binding':binding,'source':'literal-reference-furniture'})
    if not moves:return block,[]
    projected=[];cursor=0
    boundaries=[];offset=0
    for span in spans:boundaries.append((offset,offset+len(span['text']),span));offset+=len(span['text'])
    overridden={}
    for move in moves:
        explicit=move['binding'].get('verseKeys')
        if not explicit:continue
        candidates=[]
        for left,right,span in boundaries:
            if not span.get('verseKeys') or left>=move['start']:continue
            gap=text[min(right,move['start']):move['start']]
            if not gap.strip(' \t\r\n،؛,:.!?؟”“«»﴿﴾()（）[]'):
                candidates.append((min(right,move['start']),left,span))
        if candidates:
            _,left,span=max(candidates,key=lambda item:(item[0],item[1]));overridden[left]=list(explicit)
            move['originalAdjacentSpanVerseKeys']=list(span['verseKeys'])
            move['referencePlacement']='one exact original source reference; adjacent automatic/fuzzy span identities retained in provenance only'
    def copy_range(start,end):
        from copy import deepcopy
        for left,right,span in boundaries:
            a=max(start,left);b=min(end,right)
            if a<b:
                value=deepcopy(span);value['text']=span['text'][a-left:b-left]
                if left in overridden:value['verseKeys']=overridden[left];value['explicitSourceReferencePlaced']=True
                # Existing typed metadata remains on the final surviving part.
                if b<right:
                    for name in ['citations','noteTexts']:value.pop(name,None)
                projected.append(value)
    for move in moves:
        copy_range(cursor,move['start']);projected.append({'text':'','role':'body',**move['binding']});cursor=move['end']
    copy_range(cursor,len(text))
    result=dict(block);result['spans']=projected;result['text']=''.join(s['text'] for s in projected)
    expected=text
    for move in reversed(moves):expected=expected[:move['start']]+expected[move['end']:]
    if result['text']!=expected:raise ValueError('Prose changed beyond its exact source reference furniture')
    return result,moves
