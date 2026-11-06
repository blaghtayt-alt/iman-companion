from pathlib import Path
import json,argparse,hashlib,zipfile
import pdfplumber
from docx import Document
from lxml import etree
from bibliography import native_text,digits
from locale_copy import locale,DOWNLOADS
from urllib.parse import quote
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--tag',required=True);ap.add_argument('--repo',required=True);args=ap.parse_args();folder=args.folder
    index=json.loads((folder/'index.json').read_text(encoding='utf-8'));lines=['# 📚',''];pages={}
    for book in index['books']:
        file=folder/book['file'];pdf=file.with_suffix('.pdf')
        checks=json.loads((folder/(file.name+'.reader-checks.json')).read_text(encoding='utf-8'))
        if isinstance(checks,list):checks={'body':checks,'footnotes':[]}
        rendered=''.join(Document(file).element.body.xpath('.//w:t/text()'))
        offset=0
        for text in checks['body']:
            location=rendered.find(text,offset)
            if location<0:raise ValueError('Reader text changed or reordered during Word refresh')
            offset=location+len(text)
        native_text(rendered,book['language'])
        with zipfile.ZipFile(file) as z:
            for name in z.namelist():
                if name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
                    node=etree.fromstring(z.read(name))
                    native_text(''.join(node.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})),book['language'])
        if checks['footnotes']:
            with zipfile.ZipFile(file) as z:
                notes=etree.fromstring(z.read('word/footnotes.xml'));W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
                visible='\n'.join(''.join((n.text or '') if n.tag=='{'+W+'}t' else ('\n' if n.tag=='{'+W+'}br' else '') for n in p.iter()) for p in notes.findall('.//{'+W+'}p'))
                if any(t not in visible for t in checks['footnotes']):raise ValueError('Footnote text changed during Word refresh')
                native_text(visible,book['language'])
                if 'http://' in visible or 'https://' in visible or notes.findall('.//{'+W+'}hyperlink'):raise ValueError('Reference links remain in footnotes')
                ids={int(n.get('{'+W+'}id')) for n in notes.findall('{'+W+'}footnote') if int(n.get('{'+W+'}id'))>0}
                body=etree.fromstring(z.read('word/document.xml'));refs=[int(n.get('{'+W+'}id')) for n in body.findall('.//{'+W+'}footnoteReference')]
                if ids!=set(refs) or len(refs)!=len(checks['footnotes']):raise ValueError('Broken or missing footnote anchors')
        if not pdf.exists():raise ValueError('Missing rendered PDF')
        doc=pdfplumber.open(pdf)
        if len(doc.pages)<3:raise ValueError('Unexpected short/empty book')
        if book['language'] in {'ar','ur','fa'} and len(doc.pages)>=10000:raise ValueError('Native pagination needs more than four digit positions')
        cover=doc.pages[0]
        if not any(abs(i['x0'])<.5 and abs(i['top'])<.5 and abs(i['x1']-cover.width)<.5 and abs(i['bottom']-cover.height)<.5 for i in cover.images):raise ValueError('Cover does not reach every page edge')
        for n,page in enumerate(doc.pages):
            if n==0:continue # illustrated cover
            if book['language'] in {'ar','ur','fa'}:
                footer=''.join(c['text'] for c in sorted((c for c in page.chars if c['top']>page.height-34),key=lambda c:c['x0'])).strip()
                if footer!=digits(str(n+1),book['language']):raise ValueError(f'Wrong native page number on physical page {n+1}: {footer!r}')
            if not (page.extract_text() or '').strip():raise ValueError(f'Unexpected blank page: {file.name}:{n+1}')
            for word in page.extract_words():
                if '\ufffd' in word['text']:raise ValueError('Replacement glyph in exported book')
                if word['x0'] < -1 or word['top'] < -1 or word['x1'] > page.width+1 or word['bottom'] > page.height+1:raise ValueError('Text outside page bounds')
        book['pages']=len(doc.pages);doc.close();book['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        with zipfile.ZipFile(file) as z:
            if not any(n.endswith('.odttf') for n in z.namelist()):raise ValueError('Embedded fonts lost during render')
        url=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(file.name,safe='')}"
        book['download']=url;download=f'[Word]({url})'
        book['pdfDownload']=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(pdf.name,safe='')}"
        book['pdfSha256']=hashlib.sha256(pdf.read_bytes()).hexdigest();book['exportVerified']=True;book['previewOnly']=bool(index.get('previewOnly'))
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
