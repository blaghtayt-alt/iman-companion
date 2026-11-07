from pathlib import Path
import json,argparse,hashlib,zipfile
import pdfplumber
from docx import Document
from lxml import etree
from bibliography import native_text,digits
from locale_copy import locale,DOWNLOADS,NATIVE_DIGITS
from reader_xml import body_text
from urllib.parse import quote
from check_audio_qr import validate_audio_qr
from font_integrity import verify as verify_embedded_fonts
from toc_sync import reconcile as verify_toc_targets
from word_layout_check import verify_pair as verify_contents_pair
def require_complete_references(book):
    if book.get('collection')!='seerah':return
    check=book.get('referenceReadiness')
    if not isinstance(check,dict) or check.get('units')!=len(book.get('units',[])) or check.get('auditedUnits')!=len(book.get('units',[])) or not book.get('units') or check.get('unboundQuranSegments')!=0 or check.get('unboundHadithSegments')!=0:
        raise ValueError('Seerah source citations are incomplete; a layout proof cannot be published as a complete book')
def public_export_inputs(index,folder):
    allowed={'tadabbur-extended','articles','seerah','hadith'}
    if any(book.get('collection') not in allowed for book in index['books']):raise ValueError('Only public collection books can be checked for release')
    expected=set()
    for book in index['books']:
        file=Path(book['file'])
        if file.name!=book['file'] or file.suffix!='.docx':raise ValueError('Invalid public book filename')
        pair={file.name,file.with_suffix('.pdf').name}
        if expected.intersection(pair):raise ValueError('Duplicate public book asset')
        expected.update(pair)
    present={p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.docx','.pdf'}}
    if present!=expected:raise ValueError('Unindexed or missing book files cannot be released')

def validate_footnotes(notes,body,expected,lang):
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    tag=lambda n:'{'+W+'}'+n
    actual={}
    allowed_special={'separator','continuationSeparator','continuationNotice'}
    for note in notes.findall(tag('footnote')):
        kind=note.get(tag('type'))
        if kind in allowed_special:continue
        if kind not in (None,'normal'):raise ValueError('Unknown footnote type')
        raw=note.get(tag('id'))
        try:note_id=int(raw)
        except (TypeError,ValueError):raise ValueError('Invalid footnote ID')
        if note_id in actual:raise ValueError('Duplicate footnote ID')
        paragraphs=[]
        for p in note.findall('.//'+tag('p')):
            paragraphs.append(''.join((n.text or '') if n.tag==tag('t') else ('\n' if n.tag==tag('br') else '') for n in p.iter()))
        text='\n'.join(paragraphs)
        native_text(text,lang)
        if 'http://' in text or 'https://' in text or note.findall('.//'+tag('hyperlink')):raise ValueError('Reference links remain in footnotes')
        actual[note_id]=text
    refs=[]
    for ref in body.findall('.//'+tag('footnoteReference')):
        try:refs.append(int(ref.get(tag('id'))))
        except (TypeError,ValueError):raise ValueError('Invalid footnote reference')
    if len(refs)!=len(expected) or len(set(refs))!=len(refs) or set(refs)!=set(actual):raise ValueError('Broken or missing footnote anchors')
    # The generator deliberately inserts one space after the footnote marker.
    if any(actual[note_id]!=' '+text for note_id,text in zip(refs,expected)):raise ValueError('Footnote text changed or reordered during Word refresh')

def validate_toc(body,language,minimum_entries):
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    tag=lambda n:'{'+W+'}'+n
    bookmarks={n.get(tag('name')) for n in body.findall('.//'+tag('bookmarkStart'))}
    entries=[]
    for p in body.findall('.//'+tag('p')):
        style=p.find('./'+tag('pPr')+'/'+tag('pStyle'))
        if style is None or style.get(tag('val')) not in {'TOC1','TOC2','TOC 1','TOC 2'}:continue
        links=p.findall('.//'+tag('hyperlink'))
        if len(links)!=1 or links[0].get(tag('anchor')) not in bookmarks:raise ValueError('Broken contents link')
        nodes=list(p.iter());tabs=[i for i,n in enumerate(nodes) if n.tag==tag('tab')]
        if not tabs:raise ValueError('Contents entry has no page-number separator')
        tail=[n.text or '' for n in nodes[tabs[-1]+1:] if n.tag==tag('t') and (n.text or '').strip()]
        if len(tail)!=1:raise ValueError('Invalid contents page number')
        allowed=NATIVE_DIGITS[language] if language in {'ar','ur','fa'} else '0123456789'
        if not tail[0] or any(ch not in allowed for ch in tail[0]):raise ValueError('Contents page number is not in the expected digit set')
        entries.append(tail[0])
    if len(entries)<minimum_entries:raise ValueError('Missing contents entries')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--tag',required=True);ap.add_argument('--repo',required=True);ap.add_argument('--root',type=Path,default=Path('.'));ap.add_argument('--review-only',action='store_true');ap.add_argument('--prepare-only',action='store_true');args=ap.parse_args();folder=args.folder
    index=json.loads((folder/'index.json').read_text(encoding='utf-8'));index['previewOnly']=bool(index.get('previewOnly') or args.review_only);lines=['# 📚',''];pages={}
    public_export_inputs(index,folder)
    for book in index['books']:
        if not index['previewOnly'] and not args.prepare_only:require_complete_references(book)
        file=folder/book['file'];pdf=file.with_suffix('.pdf')
        checks=json.loads((folder/(file.name+'.reader-checks.json')).read_text(encoding='utf-8'))
        if isinstance(checks,list):checks={'body':checks,'footnotes':[]}
        rendered=body_text(Document(file).element.body)
        offset=0
        for text in checks['body']:
            location=rendered.find(text,offset)
            if location<0:raise ValueError('Reader text changed or reordered during Word refresh')
            offset=location+len(text)
        native_text(rendered,book['language'])
        with zipfile.ZipFile(file) as z:
            validate_toc(etree.fromstring(z.read('word/document.xml')),book['language'],len(book['units']))
            for name in z.namelist():
                if name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
                    node=etree.fromstring(z.read(name))
                    native_text(''.join(node.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})),book['language'])
        if checks['footnotes']:
            with zipfile.ZipFile(file) as z:
                notes=etree.fromstring(z.read('word/footnotes.xml'));W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
                body=etree.fromstring(z.read('word/document.xml'))
                validate_footnotes(notes,body,checks['footnotes'],book['language'])
        if not pdf.exists():raise ValueError('Missing rendered PDF')
        contents=verify_contents_pair(file,pdf,book['language']);book['pdfContentsVerification']=contents['pdf']
        if contents['word']:
            word=contents['word'];book['wordPages']=word['pages'];book['wordContentsVerification']=word
        doc=pdfplumber.open(pdf)
        if len(doc.pages)<3:raise ValueError('Unexpected short/empty book')
        if book['language'] in {'ar','ur','fa'} and len(doc.pages)>=10000:raise ValueError('Native pagination needs more than four digit positions')
        cover=doc.pages[0]
        if not any(i['x0']<=.5 and i['top']<=.5 and i['x1']>=cover.width-.5 and i['bottom']>=cover.height-.5 for i in cover.images):raise ValueError('Cover does not reach every page edge')
        for n,page in enumerate(doc.pages):
            if n==0:continue # illustrated cover
            if book['language'] in {'ar','ur','fa'}:
                footer=''.join(c['text'] for c in sorted((c for c in page.chars if c['top']>page.height-34),key=lambda c:c['x0'])).strip()
                if footer!=digits(str(n+1),book['language']):raise ValueError(f'Wrong native page number on physical page {n+1}: {footer!r}')
            if not (page.extract_text() or '').strip():raise ValueError(f'Unexpected blank page: {file.name}:{n+1}')
            for word in page.extract_words():
                if '\ufffd' in word['text']:raise ValueError('Replacement glyph in exported book')
                if word['x0'] < -1 or word['top'] < -1 or word['x1'] > page.width+1 or word['bottom'] > page.height+1:raise ValueError('Text outside page bounds')
        book['audioQRVerification']=validate_audio_qr(file,doc,book.get('audioPanels',[]))
        book['pages']=len(doc.pages);doc.close();book['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        font_conf=json.loads((args.root/'books/config.json').read_text(encoding='utf8'))
        verify_embedded_fonts(file,font_conf,book['language'])
        url=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(file.name,safe='')}"
        book['download']=url;download=f'[Word]({url})'
        book['pdfDownload']=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(pdf.name,safe='')}"
        book['pdfSha256']=hashlib.sha256(pdf.read_bytes()).hexdigest();book['exportVerified']=not args.prepare_only;book['preparationVerified']=True;book['previewOnly']=bool(index.get('previewOnly'))
        download+=f" · [PDF]({book['pdfDownload']})"
        lang=book['language'];lc=locale(lang);page=pages.setdefault(lang,['# '+book['languageLabel'],''])
        page+=['## '+book['collectionLabel'],'',f'[{DOWNLOADS[lang][0]}]({url})','']
        page+=[f'[{DOWNLOADS[lang][1]}]({book["pdfDownload"]})','']
    for lang,page in pages.items():
        # URLs are link targets, never visible source labels in a book or native page.
        for text in page:
            visible=text.split('](',1)[0].lstrip('[') if '](' in text else text
            native_text(visible,lang)
        filename='INDEX_'+lang+'.md';(folder/filename).write_text('\n'.join(page),encoding='utf-8')
        lines.append(f'[{locale(lang)["nativeName"]}](https://github.com/{args.repo}/releases/download/{args.tag}/{filename})\n')
    (folder/'INDEX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');(folder/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    assets=sorted(list(folder.glob('*.docx'))+list(folder.glob('*.pdf')))
    (folder/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets),encoding='utf-8')
if __name__=='__main__':main()
