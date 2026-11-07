"""Format the four source-owner-bound current Arabic sections, never mixed MD.

Only reference furniture moves: Quran identities stay beside quotations and
original Hadith/book identities become footnotes. Every prose/quote character
and meaningful source qualification remains literal.
"""
from copy import deepcopy
import hashlib,json,re,unicodedata
from build_books import inside,check_unit
from bibliography import native_text,expand_verse_key

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
def normalized(text):
    text=unicodedata.normalize('NFKD',text)
    return ''.join(c for c in text if not unicodedata.category(c).startswith('M') and not c.isspace()).translate(str.maketrans('أإآٱ','اااا'))
BOOKS={'البخاري':'bukhari','مسلم':'muslim','ابن ماجه':'ibnmajah','أبو داود':'abudawud','أحمد':'ahmad','الترمذي':'tirmidhi','النسائي':'nasai'}

def generate(root,catalog,declaration):
    if (declaration.get('language'),declaration.get('collection'),declaration.get('adapter'))!=('ar','tadabbur-extended','arabic-current-ikhlas-v1'):raise ValueError('Unsupported current Arabic source adapter')
    binding=declaration['arabicReaderBinding'];raw=inside(root,binding['path']).read_bytes()
    if sha(raw)!=binding['sha256']:raise ValueError('Arabic current-reader binding changed')
    bound=json.loads(raw)
    if bound.get('schema')!='iman-arabic-current-reader-source-binding-v1':raise ValueError('Wrong Arabic source binding schema')
    source_binding=bound['sourceJSON'];source_raw=inside(root,source_binding['path']).read_bytes()
    if sha(source_raw)!=source_binding['sha256']:raise ValueError('Arabic current JSON changed')
    source=json.loads(source_raw);keys=[x['key']for x in bound['sections']]
    if keys!=['112:1','112:2','112:3','112:4']:raise ValueError('Current whole Arabic Ikhlas section coverage changed')
    rows=[e for e in catalog['entries']if(e.get('collection'),e.get('language'),e.get('id'))==('tadabbur','ar','112:extended')]
    if len(rows)!=1 or rows[0].get('json')!=source_binding['path'] or bound['sourceOriginalSHA256']not in rows[0].get('sourceHashes',[]):raise ValueError('Current Arabic catalogue identity changed')
    conf=json.loads((root/'books/config.json').read_bytes());quran_binding=conf['quranText'];names_binding=conf['surahNames'];quran_raw=inside(root,quran_binding['path']).read_bytes();names_raw=inside(root,names_binding['path']).read_bytes()
    if sha(quran_raw)!=quran_binding['sha256'] or sha(names_raw)!=names_binding['sha256']:raise ValueError('Canonical Quran or native name asset changed')
    quran=json.loads(quran_raw);names=json.loads(names_raw)['ar'];surahs={normalized(name):n for n,name in enumerate(names,1)}
    sections=[];changes=[];source_commentary=[];formatted_commentary=[];source_refs=[];main_ayahs=[]
    for section_binding in bound['sections']:
        key=section_binding['key'];entry=source['entries'][key]
        if sha(canonical(entry))!=section_binding['entryCanonicalJSONSHA256']:raise ValueError('Arabic entry differs from source-owner binding')
        if len(entry['blocks'])!=len(section_binding['blocks']):raise ValueError('Arabic source block coverage changed')
        spans=[];original=''
        for block,check in zip(entry['blocks'],section_binding['blocks']):
            if sha(block['text'].encode())!=check['textSHA256'] or sha(canonical(block['runs647']))!=check['runsCanonicalJSONSHA256'] or ''.join(r['text']for r in block['runs647'])!=block['text']:raise ValueError('Arabic literal source/runs changed')
            if block['kind']=='ayah':
                literal=block['text'];number=int(key.split(':')[1]);canonical_ayah=quran[key]
                if not (literal.startswith('﴿') and literal.endswith('﴾')) or canonical_ayah!=literal[1:-1]+' '+'١٢٣٤'[number-1]:raise ValueError('Main ayah differs beyond its canonical verse-number presentation')
                main_ayahs.append({'verseKey':key,'sourceTextSHA256':sha(literal.encode('utf8')),'canonicalTextSHA256':sha(canonical_ayah.encode('utf8')),'presentation':'Source verse words with ornamental brackets replaced by the canonical verse number.'})
                continue
            if block['kind']!='paragraph':raise ValueError('Unexpected current Arabic block kind')
            original+=block['text'];source_commentary.append(block['text'])
            for run in block['runs647']:
                if run.get('color')not in {'202824','7C3AED','2563EB'}:raise ValueError('Unknown source formatting role')
                role='body' if run['color']=='202824' else ('current-ayah' if run['color']=='7C3AED' else ('quran' if '﴿'in run['text']or'﴾'in run['text']else'related'))
                for part in re.split(r'(\[[^\]]+\])',run['text']):
                    if not part:continue
                    if not(part.startswith('[')and part.endswith(']')):
                        spans.append({'text':part,'role':role,'bold':bool(run.get('bold'))});continue
                    # The exact reference is already present in the supplied
                    # current source; no website ID or related variant is used.
                    match=re.fullmatch(r'\[([^:]+):\s*(\d+(?:[–-]\d+)?)(?:؛\s*([^\]]+))?\]',part)
                    item={'text':'','role':'body'};presentation='source-book-footnote'
                    if match and normalized(match[1])in surahs:
                        verse=str(surahs[normalized(match[1])])+':'+match[2];expand_verse_key(verse);item['verseKeys']=[verse];presentation='native-Quran-reference-beside-quote'
                    elif match and match[1]in BOOKS:
                        citation={'type':'hadith','book':BOOKS[match[1]],'number':match[2]}
                        if match[3]:citation['qualification']={'language':'ar','text':match[3]}
                        item['citations']=[citation]
                    else:
                        # Named historical/source-book notes without a typed
                        # Hadith identity retain their complete literal wording.
                        item['noteTexts']=[native_text(part[1:-1],'ar')]
                    spans.append(item);source_refs.append(part);changes.append({'section':key,'sourceReference':part,'presentation':presentation,'formattedBinding':deepcopy(item)})
        formatted=''.join(s['text']for s in spans);expected=re.sub(r'\[[^\]]+\]','',original)
        if formatted!=expected:raise ValueError('Arabic prose/quote words changed while moving reference furniture')
        formatted_commentary.append(formatted)
        blocks=[{'kind':'ayah','verseKey':key,'text':quran[key],'role':'current-ayah'}];chunk=[];length=0
        for span in spans:
            chunk.append(span);length+=len(span['text'])
            if length>=700:
                blocks.append({'kind':'paragraph','text':''.join(x['text']for x in chunk),'spans':chunk});chunk=[];length=0
        if chunk:blocks.append({'kind':'paragraph','text':''.join(x['text']for x in chunk),'spans':chunk})
        sections.append({'heading':entry['heading'],'ayahKey':key,'blocks':blocks})
    text=''.join(b['text']for s in sections for b in s['blocks']);title='تدبر سورة '+names[111]
    inputs=[binding,source_binding,quran_binding,names_binding]
    unit={'schema':'iman-book-unit-v1','id':'112:extended','language':'ar','collection':'tadabbur-extended','surah':112,'title':native_text(title,'ar'),'complete':True,'reviewGate':'published-current','sourceHashes':[bound['sourceOriginalSHA256']],'inputBindings':[{'path':b['path'],'sha256':b['sha256']}for b in inputs],'catalogBindings':[{'collection':'tadabbur','language':'ar','id':'112:extended'}],'sections':sections,'readerTextSHA256':sha(text.encode()),'provenance':{'adapter':'arabic-current-ikhlas-v1','sourceOwnerBinding':binding,'wholeSurahAyahs':4,'sourceCommentarySHA256':sha(''.join(source_commentary).encode()),'formattedCommentarySHA256':sha(''.join(formatted_commentary).encode()),'allCommentaryProseAndQuoteCharactersPreserved':True,'mainAyahPresentation':main_ayahs,'referenceFurnitureTransformations':changes,'sourceReferenceCount':len(source_refs),'excludedIntroduction':True,'excludedMixedMarkdown':True,'canonicalMainAyahs':quran_binding,'existingIntegrationEvidence':bound['existingIntegrationEvidence'],'reviewScope':bound['scope'],'sourceConditions':bound['conditions']}}
    check_unit(unit,{'language':'ar','collection':'tadabbur-extended','id':unit['id']},quran)
    return [unit]
