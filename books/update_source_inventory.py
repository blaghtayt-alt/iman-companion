"""Refresh descriptive numbered-source counts; this never grants approval."""
from pathlib import Path
import re

LABELS={'ar':'Arabic','en':'English','fr':'French','tr':'Turkish','id':'Indonesian','ms':'Malay',
        'pt-BR':'Brazilian Portuguese','ur':'Urdu','bn':'Bengali','hi':'Hindi','ru':'Russian',
        'es':'Spanish','fa':'Persian','de':'German','zh-CN':'Simplified Chinese','uz':'Uzbek',
        'th':'Thai','vi':'Vietnamese','ja':'Japanese','fil':'Filipino'}

def refresh(root):
    path=root/'materials/README.md'
    if not path.exists():return []
    text=original=path.read_text(encoding='utf8')
    for language,label in LABELS.items():
        folder=root/'materials/hadith'/('essential-'+language)
        files=[p for p in folder.rglob('*.json') if re.fullmatch(r'\d{3}',p.stem)
               and (p.parent==folder or (p.parent.parent==folder and re.fullmatch(r'\d{2}',p.parent.name)))]
        def replace(match):
            chapters={1 if p.parent==folder else int(p.parent.name) for p in files}
            suffix=re.sub(r'\d+ chapters',str(len(chapters))+' chapters',match[2])
            return match[1]+str(len(files))+suffix
        text=re.sub(r'(^\| essential-hadith \| '+re.escape(label)+r' \| )\d+( lessons?(?: pages, \d+ chapters)? \|$)',replace,text,flags=re.MULTILINE)
    if text==original:return []
    path.write_text(text,encoding='utf8');return ['materials/README.md']
