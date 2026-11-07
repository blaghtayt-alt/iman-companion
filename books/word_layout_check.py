"""Check a real Word readback bound to the exact final editable file.

Word and PDF may paginate differently. Each format must point to its own actual
pages. A receipt never substitutes for independent PDF destination validation.
"""
from pathlib import Path
from zipfile import ZipFile
import hashlib,json,re
from lxml import etree
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def contents(root):
    bookmarks={n.get(W+'name')for n in root.iter(W+'bookmarkStart')};rows=[]
    for p in root.iter(W+'p'):
        style=p.find('./'+W+'pPr/'+W+'pStyle')
        if style is None or not re.fullmatch(r'TOC\s*[1-9]',style.get(W+'val','')):continue
        links=p.findall('.//'+W+'hyperlink')
        if len(links)!=1 or links[0].get(W+'anchor')not in bookmarks:raise ValueError('Invalid Word contents bookmark')
        nodes=list(links[0].iter());tabs=[i for i,n in enumerate(nodes)if n.tag==W+'tab']
        if not tabs:raise ValueError('Word contents row has no page separator')
        values=[n for n in nodes[tabs[-1]+1:]if n.tag==W+'t'and(n.text or'').strip()]
        if len(values)!=1 or not values[0].text.strip().isdecimal():raise ValueError('Invalid Word contents page number')
        rows.append({'anchor':links[0].get(W+'anchor'),'cachedPage':int(values[0].text.strip())})
    if not rows:raise ValueError('Word contents is empty')
    return rows

def verify(docx,receipt_file):
    receipt=json.loads(Path(receipt_file).read_bytes());raw=Path(docx).read_bytes()
    if receipt.get('schema')!='iman-word-layout-readback-v1'or receipt.get('docxSHA256')!=hashlib.sha256(raw).hexdigest():raise ValueError('Word readback is not for this exact final file')
    engine=receipt.get('engine',{})
    if engine.get('application')!='Microsoft Word'or not engine.get('version')or not engine.get('build')or receipt.get('readOnly')is not True or receipt.get('savedByWord')is not False:raise ValueError('Missing actual read-only Word engine verification')
    pages=receipt.get('pages');checked=receipt.get('contents')
    if type(pages)is not int or pages<3 or not isinstance(checked,list):raise ValueError('Invalid actual Word page data')
    with ZipFile(docx)as z:rows=contents(etree.fromstring(z.read('word/document.xml')))
    if len(rows)!=len(checked):raise ValueError('Word readback omits contents targets')
    for row,actual in zip(rows,checked):
        if actual.get('anchor')!=row['anchor']or actual.get('cachedPage')!=row['cachedPage']or actual.get('actualPage')!=row['cachedPage']:raise ValueError('Word contents cache differs from actual Word target')
        if type(actual.get('actualPage'))is not int or type(actual.get('physicalPage'))is not int or not 1<=actual['physicalPage']<=pages or actual['actualPage']<1:raise ValueError('Word bookmark page is outside the checked document')
    return {'pages':pages,'matchedEntries':len(rows),'docxSHA256':receipt['docxSHA256'],'receiptSHA256':hashlib.sha256(Path(receipt_file).read_bytes()).hexdigest(),'engine':engine}

def visible_pdf_contents(pdf,language):
    """Verify painted page-number glyphs, in addition to PDF link metadata."""
    import pdfplumber
    from pypdf import PdfReader
    reader=PdfReader(pdf);page_ids={p.indirect_reference.idnum:i+1 for i,p in enumerate(reader.pages)};groups={}
    with pdfplumber.open(pdf)as visual:
        for page_index,page in enumerate(reader.pages):
            for ref in page.get('/Annots',[]):
                item=ref.get_object();dest=item.get('/Dest');action=item.get('/A')
                if dest is None and action and action.get('/S')=='/GoTo':dest=action.get('/D')
                content=str(item.get('/Contents',''));label=re.search(r'\t\s*(\d+)\s*$',content)
                if item.get('/Subtype')!='/Link'or not isinstance(dest,list)or not dest or not label:continue
                target=page_ids.get(getattr(dest[0],'idnum',None));rect=item.get('/Rect')
                if not target or not rect or int(label[1])!=target:raise ValueError('PDF contents label or destination is invalid')
                key=(page_index,content,target);chars=groups.setdefault(key,{})
                for c in visual.pages[page_index].chars:
                    x=(c['x0']+c['x1'])/2;y=(c['y0']+c['y1'])/2
                    # Nastaliq digit cells extend below the link rectangle;
                    # require real glyph-box overlap rather than its centre.
                    if float(rect[0])-1<=x<=float(rect[2])+1 and c['y1']>=float(rect[1])-2 and c['y0']<=float(rect[3])+2 and c['text'].isdecimal():chars[(c['x0'],c['y0'],c['text'])]=c
        for(_,_,target),by_position in groups.items():
            numbers=[]
            for c in sorted(by_position.values(),key=lambda c:(round((c['y0']+c['y1'])/2),c['x0'])):
                if numbers and abs(numbers[-1]['y']-(c['y0']+c['y1'])/2)<2 and c['x0']-numbers[-1]['end']<=c['size']*.6:
                    numbers[-1]['text']+=c['text'];numbers[-1]['end']=c['x1']
                else:numbers.append({'text':c['text'],'x':c['x0'],'end':c['x1'],'y':(c['y0']+c['y1'])/2})
            if not numbers:raise ValueError('No painted PDF contents page number')
            number=min(numbers,key=lambda n:n['x'])if language in{'ar','ur','fa'}else max(numbers,key=lambda n:n['end'])
            if int(number['text'])!=target:raise ValueError('Painted PDF page number differs from its own link destination')
    if not groups:raise ValueError('PDF contents links are missing')
    return {'visibleLabelsMatched':len(groups)}

def verify_pair(docx,pdf,language):
    from check_contents_targets import check as pdf_check
    from toc_sync import reconcile
    result={'pdf':pdf_check(docx,pdf),'word':None};sidecar=Path(docx).with_name(Path(docx).name+'.word-layout.json')
    if sidecar.exists():
        result['word']=verify(docx,sidecar);visible=visible_pdf_contents(pdf,language)
        if visible['visibleLabelsMatched']!=result['pdf']['matchedEntries']:raise ValueError('Not every PDF contents entry has a verified painted label')
        result['pdf'].update(visible)
    elif reconcile(docx,pdf,language)['mismatches']:raise ValueError('Contents page numbers do not match PDF link targets')
    return result
