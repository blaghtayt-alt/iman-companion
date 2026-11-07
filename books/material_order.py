"""Source-declared order; never use the last digits of a compound identifier."""
import re

def positive(value):return type(value)is int and value>0

def position(unit):
    explicit=unit.get('ordering')
    if explicit is not None:
        if explicit.get('kind')=='global-sequence':
            n=explicit.get('sequence')
            if not positive(n) or n!=unit.get('order'):raise ValueError('Global sequence differs from declared canonical order')
            return 'global',(n,0)
        if explicit.get('kind')!='chapter-lesson':raise ValueError('Unknown source ordering scheme')
        chapter,lesson=explicit.get('chapter'),explicit.get('lesson')
        if not positive(chapter) or not positive(lesson):raise ValueError('Chapter and lesson must be positive integers')
        if any(unit.get(k,v)!=v for k,v in [('chapter',chapter),('lesson',lesson)]):raise ValueError('Conflicting source hierarchy')
        return 'hierarchy',(chapter,lesson)
    if 'chapter'in unit and 'lesson'in unit:
        if not positive(unit['chapter']) or not positive(unit['lesson']):raise ValueError('Invalid source hierarchy')
        return 'hierarchy',(unit['chapter'],unit['lesson'])
    n=unit.get('chapter',unit.get('number',unit.get('order')))
    if not positive(n):raise ValueError('Missing positive canonical source order')
    if unit.get('order',n)!=n:raise ValueError('Conflicting canonical source number and order')
    return 'global',(n,0)

def validate_publication(unit,ident):
    scheme,_=position(unit)
    if unit.get('ordering')is not None or scheme=='hierarchy':return
    numbers=re.findall(r'\d+',str(ident))
    if len(numbers)!=1 or int(numbers[0])!=unit['order']:
        raise ValueError('Ambiguous lesson ID needs explicit chapter-lesson or global-sequence ordering')

def validate_group(units):
    if not units or units[0]['collection'] not in {'hadith','seerah','articles'}:return
    positions=[position(u) for u in units]
    if len({p[0] for p in positions})!=1:raise ValueError('Mixed source ordering schemes need an explicit global sequence')
    if len(set(positions))!=len(positions):raise ValueError('Duplicate canonical chapter/lesson position')
