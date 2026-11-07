"""Give normal live Word PAGE fields pinned native numeral glyphs.

Run after the canonical PDF is rendered. A standard PAGE value stays numeric;
the embedded face displays Arabic/Persian shapes without global Word options.
"""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json,os,re,tempfile
from lxml import etree
from font_integrity import verify

FONT_KEYS={'ar':'DigitsArabic','ur':'DigitsPersian','fa':'DigitsPersian'}
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
q=lambda name:'{'+W+'}'+name

def prepare(file,root,language):
    if language not in FONT_KEYS:return None
    conf=json.loads((root/'books/config.json').read_bytes());definition=conf['fonts'][FONT_KEYS[language]];family=definition['family']
    verify(file,conf,language)
    before=hashlib.sha256(Path(file).read_bytes()).hexdigest()
    with ZipFile(file)as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate document parts; preserve input')
        parts={n:archive.read(n)for n in names}
    changed=[]
    for name,raw in list(parts.items()):
        if not(name.startswith('word/footer') and name.endswith('.xml')):continue
        body=etree.fromstring(raw)
        paragraphs=[p for p in body.findall(q('p')) if any(re.search(r'\bPAGE\b',n.text or '')for n in p.iter(q('instrText')))]
        for paragraph in paragraphs:
            if any((n.text or '').strip() and not (n.text or '').strip().isdecimal() for n in paragraph.iter(q('t'))):raise ValueError('Footer contains non-page text; preserve it')
            if any(n.tag in {q('drawing'),q('pict'),q('object'),q('hyperlink'),q('bookmarkStart'),q('bookmarkEnd')} for n in paragraph.iter()):raise ValueError('Footer contains additional content; preserve it')
            words={word.upper() for n in paragraph.iter(q('instrText')) for word in re.findall(r'[A-Za-z]+',n.text or '')}
            if words-{'IF','PAGE','MOD','INT','ARABIC','MERGEFORMAT'}:raise ValueError('Footer contains another field; preserve it')
            for node in list(paragraph):paragraph.remove(node)
            prop=etree.SubElement(paragraph,q('pPr'));etree.SubElement(prop,q('jc'),{q('val'):'center'});etree.SubElement(prop,q('spacing'),{q('before'):'0',q('after'):'0',q('line'):'240',q('lineRule'):'exact'})
            def run(tag,attrs=None,text=None):
                item=etree.SubElement(paragraph,q('r'));pr=etree.SubElement(item,q('rPr'));etree.SubElement(pr,q('rFonts'),{q(k):family for k in ('ascii','hAnsi','cs','eastAsia')})
                for key,value in (('sz','20'),('szCs','20'),('rtl','0')):etree.SubElement(pr,q(key),{q('val'):value})
                node=etree.SubElement(item,q(tag),{q(k):v for k,v in (attrs or {}).items()});node.text=text
            run('fldChar',{'fldCharType':'begin'});run('instrText',text=' PAGE ');run('fldChar',{'fldCharType':'separate'});run('t',text='٢' if language=='ar' else '۲');run('fldChar',{'fldCharType':'end'})
        if paragraphs:parts[name]=etree.tostring(body,xml_declaration=True,encoding='UTF-8',standalone=True);changed.append(name)
    if not changed:raise ValueError('No live numbered Word footer found')
    fd,temporary=tempfile.mkstemp(dir=Path(file).parent,suffix='.docx');os.close(fd)
    try:
        with ZipFile(temporary,'w',ZIP_DEFLATED)as archive:
            for name,raw in parts.items():archive.writestr(name,raw)
        verify(Path(temporary),conf,language)
        if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=before:raise ValueError('Input changed during footer preparation')
        os.replace(temporary,file)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return {'method':'ordinary-PAGE-with-pinned-native-glyphs','font':family,'fontSHA256':definition['sha256'],'parts':changed,'wordGlobalOptionsChanged':False,'fieldValuesRemainNumeric':True}

def verify_rendered_footer(pdf,root,language):
    """Verify real Word output values AND its embedded native glyph outlines."""
    import hashlib,io
    import pdfplumber
    from pypdf import PdfReader
    from fontTools.ttLib import TTFont
    conf=json.loads((root/'books/config.json').read_bytes());definition=conf['fonts'][FONT_KEYS[language]]
    expected=TTFont(root/definition['files']['Regular']);start=0x660 if language=='ar' else 0x6f0
    def geometry(font,code):
        glyph=font['glyf'][font.getBestCmap()[code]];coords,ends,flags=glyph.getCoordinates(font['glyf'])
        return font['head'].unitsPerEm,list(coords),list(ends),list(flags)
    outlines=[geometry(expected,start+n)for n in range(10)];reader=PdfReader(pdf);matched=set();checked=[];seen={}
    for page in reader.pages:
        for reference in page.get('/Resources',{}).get('/Font',{}).values():
            font=reference.get_object();name=str(font.get('/BaseFont','')).lstrip('/')
            descriptor=font.get('/FontDescriptor')
            if descriptor is None or '/FontFile2' not in descriptor:continue
            raw=descriptor['/FontFile2'].get_data();digest=hashlib.sha256(raw).hexdigest()
            if name in seen:
                if seen[name]!=digest:raise ValueError('Ambiguous Word PDF font identity')
                continue
            seen[name]=digest;actual=TTFont(io.BytesIO(raw))
            try:
                if all(geometry(actual,48+n)==outlines[n]for n in range(10)):matched.add(name)
            except (KeyError,TypeError):pass
            finally:actual.close()
    expected.close()
    if not matched:raise ValueError('Actual Word output lacks the pinned native numeral outlines')
    with pdfplumber.open(pdf)as document:
        for index,page in enumerate(document.pages):
            if index==0:continue
            chars=sorted((c for c in page.chars if c['top']>page.height-34 and not c['text'].isspace()),key=lambda c:c['x0'])
            text=''.join(c['text']for c in chars)
            if not text.isdecimal() or int(text)!=index+1 or any(c['fontname']not in matched for c in chars):raise ValueError('Wrong native Word footer at physical page '+str(index+1))
            if any(c['x0']<0 or c['x1']>page.width or c['top']<0 or c['bottom']>page.height for c in chars):raise ValueError('Native Word footer outside page')
            checked.append(index+1)
            page.close()  # Release rendered-page caches before processing the next page.
    return {'proofSHA256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'pagesChecked':checked,'allTenNativeGlyphOutlinesExact':True,'allPrintedValuesMatchPhysicalPage':True}
