"""Dynamic native-digit page fields, independent of a reader's Word preferences.

Use normal Word IF/formula/PAGE fields. The displayed digits are literal Unicode
characters in the document, so changing the app-wide Numeral option is unnecessary.
"""
from copy import deepcopy
from lxml import etree
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from locale_copy import NATIVE_DIGITS

def run(tag,attrs=None,text=None,font=None):
    r=OxmlElement('w:r')
    if font:
        pr=OxmlElement('w:rPr');r.append(pr)
        f=OxmlElement('w:rFonts')
        for key in ['ascii','hAnsi','cs','eastAsia']:f.set(qn('w:'+key),font)
        pr.append(f)
        for name,val in [('sz','20'),('szCs','20'),('rtl','0')]:
            e=OxmlElement('w:'+name);e.set(qn('w:val'),val);pr.append(e)
    e=OxmlElement(tag)
    for k,v in (attrs or {}).items():e.set(qn(k),v)
    if text is not None:e.text=text;e.set(qn('xml:space'),'preserve')
    r.append(e);return r

def field(parts,cache='',font=None):
    nodes=[run('w:fldChar',{'w:fldCharType':'begin'},font=font)]
    for part in parts:
        nodes.extend(deepcopy(part) if isinstance(part,list) else [run('w:instrText',text=part,font=font)])
    nodes.append(run('w:fldChar',{'w:fldCharType':'separate'},font=font))
    if cache:nodes.append(run('w:t',text=cache,font=font))
    nodes.append(run('w:fldChar',{'w:fldCharType':'end'},font=font));return nodes

def native_number_nodes(instruction,lang,font):
    if lang not in NATIVE_DIGITS:raise ValueError('No native digit set')
    native=NATIVE_DIGITS[lang];nodes=[]
    for power in [1000,100,10,1]:
        value=field([' = MOD(INT(',field([' '+instruction+' \\* Arabic '],cache='2',font=font),f' / {power}),10) '],cache='0',font=font)
        def choice(n):
            if n==9:return '"'+native[n]+'" '
            return field([' IF ',value,f' = {n} "{native[n]}" ',choice(n+1),' '],cache=native[0],font=font)
        selected=choice(0)
        if power>1:selected=field([' IF ',field([' '+instruction+' \\* Arabic '],cache='2',font=font),f' >= {power} ',selected,' "" '],font=font)
        nodes.extend(selected)
    return nodes

def append_native_number(paragraph,instruction,lang,font):
    for node in native_number_nodes(instruction,lang,font):paragraph._p.append(node)

def native_toc(input_file,output_file,lang,font):
    """Convert generated PAGEREF fields after TOC refresh; keep live link targets."""
    import zipfile,re
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':W}
    with zipfile.ZipFile(input_file) as z:parts={n:z.read(n) for n in z.namelist()}
    root=etree.fromstring(parts['word/document.xml']);changed=0
    for paragraph in root.findall('.//{'+W+'}p'):
        style=paragraph.find('./{'+W+'}pPr/{'+W+'}pStyle')
        if style is None or style.get('{'+W+'}val') not in {'TOC1','TOC2','TOC 1','TOC 2'}:continue
        nodes=list(paragraph.iter());tabs=[i for i,n in enumerate(nodes) if n.tag=='{'+W+'}tab']
        if not tabs:raise ValueError('TOC entry has no page-number separator')
        tail=[n for n in nodes[tabs[-1]+1:] if n.tag=='{'+W+'}t' and (n.text or '').strip()]
        if len(tail)!=1 or not (tail[0].text or '').strip().isdigit():raise ValueError('Unexpected TOC page-number structure')
        value=tail[0].text
        if not value.isascii() or not value.isdigit() or int(value)<1:raise ValueError('Unexpected TOC page number')
        tail[0].text=value.translate(str.maketrans('0123456789',NATIVE_DIGITS[lang]));changed+=1
    if not changed:raise ValueError('No refreshed TOC entries found')
    parts['word/document.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    settings=etree.fromstring(parts['word/settings.xml'])
    for e in settings.findall('{'+W+'}updateFields'):e.set('{'+W+'}val','false')
    parts['word/settings.xml']=etree.tostring(settings,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(output_file,'w',zipfile.ZIP_DEFLATED) as z:
        for name,body in parts.items():z.writestr(name,body)
    return changed

def main():
    from pathlib import Path
    import argparse,json,tempfile,os
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--folder',type=Path,required=True);args=ap.parse_args()
    config=json.loads((args.root/'books/config.json').read_text(encoding='utf-8'))
    index=json.loads((args.folder/'index.json').read_text(encoding='utf-8'))
    for book in index['books']:
        lang=book['language']
        if lang not in {'ar','ur','fa'}:continue
        font=config['fonts'][config['languages'][lang]['font']]['family'];file=args.folder/book['file']
        with tempfile.TemporaryDirectory(dir=args.folder) as tmp:
            target=Path(tmp)/file.name;native_toc(file,target,lang,font);os.replace(target,file)
if __name__=='__main__':main()
