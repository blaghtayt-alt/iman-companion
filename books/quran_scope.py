"""Resolve public source metadata to canonical Quran order without changing IDs.

This recognizes legacy schema aliases only. It does not grant source approval,
select a competing edition, or infer canonical order from arbitrary filenames.
"""
import re

def canonical_surah(row):
    if row.get('collection')!='tadabbur':return None
    ident=str(row.get('id',''));mode=row.get('mode');number=row.get('surah',row.get('canonicalSurah'))
    if mode=='extended':
        match=re.fullmatch(r'(\d{1,3}):extended',ident)
        if number is None and match:number=int(match[1])
        if type(number)is not int or not 1<=number<=114:raise ValueError('Extended Quran material lacks explicit canonical surah metadata')
        if match and int(match[1])!=number:raise ValueError('Quran catalogue ID conflicts with canonical surah metadata')
        return number
    if mode is None and ident=='fatiha-extended':
        # Published1004 reader packet schema has neither mode nor surah. Its
        # exact catalogue identity/path establishes the recognized alias;
        # current review evidence still comes from the source owner.
        lang=row.get('language');prefix=f'materials/tadabbur/fatiha-extended/{lang}/'
        if row.get('status')!='current-app-edition' or row.get('json')!=prefix+'reading.json' or row.get('markdown')!=prefix+'reading.md':
            raise ValueError('Unrecognized legacy Fatiha packet identity')
        if number not in (None,1):raise ValueError('Fatiha alias conflicts with canonical surah metadata')
        return 1
    return None

def extended(row):return canonical_surah(row)is not None

def review_catalog_id(record):
    if 'catalogId'in record:return str(record['catalogId'])
    ident=str(record['materialId'])
    if record.get('collection')=='tadabbur' and record.get('mode')=='extended' and ident.isdigit():return ident+':extended'
    return ident
