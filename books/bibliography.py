import re,unicodedata
from locale_copy import locale,NON_LATIN,NATIVE_DIGITS,SURAH_OVERRIDES

# These exact supplied attribution paragraphs occur in the Arabic Essential
# Hadith chapter bibliographies. Preserve their published license names and
# source address verbatim; do not grant a general Latin-text exception.
ARABIC_SOURCE_CREDITS=(
    'نصوص الآيات بالرسم العثماني من مشروع تنزيل، مع عزو السورة والآية والمحافظة على النص القرآني كما نشره المشروع. Tanzil Quran Text — CC BY 3.0',
    'حقوق النص القرآني ©\u00a0\u202a2007–2026\u202c مشروع تنزيل. يُسمح بنسخه وتوزيعه كما هو، مع ذكر المصدر والمحافظة على النص دون تغيير. tanzil.net',
    'حقوق النص القرآني ©\u00a02007–2026\u202c مشروع تنزيل. يُسمح بنسخه وتوزيعه كما هو، مع ذكر المصدر والمحافظة على النص دون تغيير. tanzil.net',
)

def native_text(text,lang):
    if re.search(r'https?://|www\.|QuranEnc|HadeethEnc|sunnah\.com|[a-z]+_[a-z]+',text,re.I):raise ValueError('Website/internal edition label leaked into reader text')
    checked=text
    if lang=='ar':
        for credit in ARABIC_SOURCE_CREDITS:checked=checked.replace(credit,'')
    if lang in NON_LATIN and any(c.isalpha() and 'LATIN' in unicodedata.name(c,'') for c in checked):raise ValueError('Untranslated Latin-script text in '+lang+' book furniture or reader text')
    return text

def digits(value,lang):
    text=str(value)
    if lang in NATIVE_DIGITS:text=text.translate(str.maketrans('0123456789',NATIVE_DIGITS[lang]))
    return text

def hadith_citation(citation,lang):
    if citation.get('type')!='hadith':raise ValueError('Use original-book Hadith citations; Quran references belong beside the ayah')
    book=locale(lang)['hadithBooks'].get(citation.get('book'))
    if not book:book=citation.get('localizedTitles',{}).get(lang)
    if not book:raise ValueError('Missing native original collection title')
    number=str(citation.get('number',''))
    # Accept a source-verified collection number/range, not a website record slug.
    if not re.fullmatch(r'\d+(?:\s*[-–/:]\s*\d+)*',number):raise ValueError('Missing verified original-book narration number')
    result=book+' ('+digits(number,lang)+')'
    if citation.get('qualification'):result+=' '+edition_credit(citation['qualification'],lang)
    return native_text(result,lang)

def expand_verse_key(key):
    m=re.fullmatch(r'(\d{1,3}):(\d{1,3})(?:[-–](\d{1,3}))?',key)
    if not m:raise ValueError('Invalid Quran reference')
    s,a=map(int,m.groups()[:2]);end=int(m[3] or a)
    if not 1<=s<=114 or not 1<=a<=end<=286:raise ValueError('Invalid Quran range')
    return [str(s)+':'+str(n) for n in range(a,end+1)]

def quran_reference(key,lang,names):
    match=re.fullmatch(r'(\d{1,3}):(\d{1,3})(?:[-–](\d{1,3}))?',key)
    if not match:raise ValueError('Invalid Quran reference')
    expand_verse_key(key);s,a=map(int,match.groups()[:2]);end=int(match[3]) if match[3] else None;lc=locale(lang)
    ayah_text=str(a)+(('–'+str(end)) if end else '')
    if not 1<=s<=114 or a<1:raise ValueError('Invalid Quran chapter/ayah number')
    name=SURAH_OVERRIDES.get(lang,{}).get(s) or (names.get(lang,[])[s-1] if len(names.get(lang,[]))>=s else '')
    if lang in NON_LATIN and any(c.isalpha() and 'LATIN' in unicodedata.name(c,'') for c in name):name=''
    if not name:raise ValueError(f'Missing verified native surah name for {lang} chapter {s}; do not publish an English fallback')
    if lang=='ja':text=f'（{name} 第{s}章・第{ayah_text}節）' if name else f'（第{s}章・第{ayah_text}節）'
    elif lang=='zh-CN':text=f'（{name}，第{s}章第{ayah_text}节）' if name else f'（第{s}章第{ayah_text}节）'
    elif end and lang in {'ar','ur','fa'}:
        plural,to={'ar':('الآيات','إلى'),'ur':('آیات','تا'),'fa':('آیه‌های','تا')}[lang]
        text=f"({lc['surahLabel']} {name} {digits(s,lang)}، {plural} {digits(a,lang)} {to} {digits(end,lang)})"
    elif name:text=f"({lc['surahLabel']} {name}{'،' if lang in {'ar','ur','fa'} else ','} {digits(s,lang)}:{digits(ayah_text,lang)})"
    else:text=f"({lc['surahLabel']} {digits(s,lang)}، {lc['ayahLabel']} {digits(a,lang)})"
    # Keep a compact citation together when the quotation ends near a margin.
    return native_text(text,lang).replace(' ','\u00a0')

def edition_credit(credit,lang):
    if credit.get('language')!=lang:raise ValueError('Translation credit must be localized to the book language')
    text=credit.get('text','').strip()
    if not text:raise ValueError('Missing translator or edition credit')
    return native_text(text,lang)
