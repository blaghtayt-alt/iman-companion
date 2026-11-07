"""Explicit reviewed commentary coverage, distinct from an entire Quran surah."""
import hashlib
from bibliography import native_text

def validate(unit,quran,approval=None):
    surah=unit['order'];sections=unit['sections']
    actual=[s['ayahKey'] for s in sections if s.get('ayahKey')]
    canonical=sorted((k for k in quran if k.split(':')[0]==str(surah)),key=lambda k:int(k.split(':')[1]))
    if not canonical or not actual or actual!=sorted(set(actual),key=lambda k:tuple(map(int,k.split(':')))) or any(k not in canonical for k in actual):
        raise ValueError('Quran coverage has duplicate, out-of-order or out-of-bounds ayahs')
    coverage=unit.get('reviewedCoverage')
    if coverage is None:
        if actual!=canonical:raise ValueError('Selected ayahs need exact declared reviewed coverage')
        return
    if coverage.get('schema')!='iman-reviewed-quran-coverage-v1' or coverage.get('surah')!=surah or coverage.get('ayahKeys')!=actual:
        raise ValueError('Reader sections differ from declared reviewed Quran coverage')
    if approval is not None and approval.get('coverage')!=coverage:raise ValueError('Coverage is not bound to the actual whole-material review')
    intro=coverage.get('introduction',{});intro_text=''.join(b['text'] for s in sections if not s.get('ayahKey') for b in s['blocks'])
    if intro.get('state')=='included':
        if not intro_text or intro.get('readerTextSHA256')!=hashlib.sha256(intro_text.encode('utf8')).hexdigest():raise ValueError('Reviewed introduction differs or is missing')
        seen_ayah=False
        for section in sections:
            if section.get('ayahKey'):seen_ayah=True
            elif seen_ayah:raise ValueError('Introduction must precede ayahs')
    elif intro.get('state')!='not-in-reviewed-material' or intro_text:raise ValueError('Introduction coverage must be explicit')
    if actual!=canonical:
        label=coverage.get('scopeLabel','');native_text(label,unit['language'])
        if not label.strip() or label not in unit['title']:raise ValueError('A selected-ayah edition needs its reviewed native scope label in the title')
