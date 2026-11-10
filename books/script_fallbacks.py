"""Explicit pinned-font assignments for glyph gaps observed in current books.

These are source characters, not replacements. Keep each character unchanged
and isolate only the demonstrated gaps so an operating-system fallback cannot
spread to adjacent native-script text. Do not infer fallback across scripts.
"""
from itertools import groupby
from hashlib import sha256

FONT_FAMILIES={'Latin':'Iman Book Inter','Arabic':'Iman Book Naskh','Japanese':'Iman Book Japanese',
               'FiqhSymbols':'Iman Book Fiqh Symbols'}
# The source PDF's AGAArabesque face assigns these private-use characters to
# two honorifics. They are not Unicode-wide meanings: require the exact
# accepted English source paragraph before assigning the supplemental face.
# Evidence and reproducible OFL glyph derivation live in
# assets/ornaments/fiqh-symbol-derivation.json. The source characters stay intact.
FIQH_SOURCE_PARAGRAPH_SHA256='1dc04f17def1ab8a735bc44fcb520bff61b6912835da527351fe26496badc6ef'
FIQH_SOURCE_CHARACTERS='\uf065\uf074'
CJK_BRACKETS='〈〉〔〕'
CJK_LANGUAGES={'th','fil','vi'}
LATIN_GAPS={
    # The pinned Thai face contains Thai letters/numerals, but no printable
    # ASCII other than the hyphen. All these Latin source characters are in
    # the already embedded Inter face, including the literal note locators.
    'th':''.join(chr(code) for code in range(0x21,0x7f) if code!=0x2d)+'·“”«»ʿā–ʾṣ',
    'bn':'·«»',
    'hi':'·«»',
    'zh-CN':'ʿʾṣ',
    'vi':'ʿʾṣ',
}
ARABIC_GAPS={'ur':'ﻻﹲﺬ'}


def fallback_key(language,character,source_text=None):
    if (language=='en' and character in FIQH_SOURCE_CHARACTERS
            and isinstance(source_text,str)
            and sha256(source_text.encode('utf8')).hexdigest()==FIQH_SOURCE_PARAGRAPH_SHA256):
        return 'FiqhSymbols'
    if language in CJK_LANGUAGES and character in CJK_BRACKETS:return 'Japanese'
    if character in LATIN_GAPS.get(language,''):return 'Latin'
    if character in ARABIC_GAPS.get(language,''):return 'Arabic'
    return None


def fallback_runs(text,language,source_text=None):
    """Yield unchanged, consecutive text pieces and their optional font key."""
    for key,characters in groupby(text,key=lambda character:fallback_key(language,character,source_text)):
        yield ''.join(characters),key


def extra_font_keys(language):
    # Latin and canonical Arabic are already embedded in every book.
    if language in CJK_LANGUAGES:return ('Japanese',)
    return ('FiqhSymbols',) if language=='en' else ()


def has_fallbacks(language):
    return language in CJK_LANGUAGES or language in LATIN_GAPS or language in ARABIC_GAPS or language=='en'
