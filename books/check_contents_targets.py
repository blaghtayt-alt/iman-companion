"""Compare the editable contents cache with the real PDF destinations."""
from pathlib import Path
import re,zipfile
from lxml import etree
from pypdf import PdfReader

def check(docx,pdf):
    with zipfile.ZipFile(docx)as archive:body=etree.fromstring(archive.read('word/document.xml'))
    W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    expected=[]
    for paragraph in body.iter(W+'p'):
        style=paragraph.find('./'+W+'pPr/'+W+'pStyle')
        if style is not None and re.fullmatch(r'TOC\s*[1-9]',style.get(W+'val','')):
            text=''.join(n.text or ''for n in paragraph.iter(W+'t'));expected.append(text)
    if not expected:raise ValueError('Missing editable contents entries')
    reader=PdfReader(pdf);pages={(p.indirect_reference.idnum,p.indirect_reference.generation):n+1 for n,p in enumerate(reader.pages)};checked={}
    for page in reader.pages:
        for ref in page.get('/Annots',[]):
            annotation=ref.get_object()
            if annotation.get('/Subtype')!='/Link':continue
            destination=annotation.get('/Dest')
            action=annotation.get('/A')
            if destination is None and action and action.get('/S')=='/GoTo':destination=action.get('/D')
            content=str(annotation.get('/Contents',''));match=re.search(r'\t\s*(\d+)\s*$',content)
            if destination is None or not match:continue
            if not isinstance(destination,list)or not hasattr(destination[0],'idnum'):raise ValueError('Unknown PDF contents destination')
            actual=pages[(destination[0].idnum,destination[0].generation)]
            if int(match[1])!=actual:raise ValueError(f'Contents displays {match[1]} but opens physical page {actual}')
            # A wrapped heading can produce several annotation rectangles.
            key=(content,destination[0].idnum,tuple(str(x)for x in destination[1:]))
            checked[key]={'displayedPage':match[1],'actualPage':actual}
    if len(checked)!=len(expected):raise ValueError('Missing or duplicated PDF contents links')
    return {'matchedEntries':len(checked)}
