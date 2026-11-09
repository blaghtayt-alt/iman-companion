from pathlib import Path
from collections import Counter
import json,argparse,hashlib,zipfile
import pdfplumber
from docx import Document
from lxml import etree
from bibliography import native_text,digits
from locale_copy import locale,NATIVE_DIGITS
from download_tables import download_labels,native_download_text
from reader_xml import body_text
from urllib.parse import quote
from check_audio_qr import validate_audio_qr
from font_integrity import verify as verify_embedded_fonts
from toc_sync import reconcile as verify_toc_targets
from word_layout_check import verify_pair as verify_contents_pair
def require_complete_references(book):
    preservation=book.get('sourceReferencePreservation')
    if preservation is not None:
        if not isinstance(preservation,dict) or preservation.get('schema')!='iman-source-reference-preservation-v1' or preservation.get('auditMode')!='literal-source-and-qualification-fidelity':raise ValueError('Invalid source-reference preservation evidence')
        units=len(book.get('units',[]))
        if not units or preservation.get('units')!=units or preservation.get('auditedUnits',0)+preservation.get('approvedPublisherUnits',0)!=units:raise ValueError('Source-reference preservation omits a reader unit')
        for source,preserved,lost in (('sourceReferences','preservedReferences','lostReferences'),('sourceQualifications','preservedQualifications','lostQualifications'),('sourceParagraphs','preservedParagraphs','lostParagraphs')):
            values=[preservation.get(field) for field in (source,preserved,lost)]
            if any(type(value) is not int or value<0 for value in values) or values[0]!=values[1] or values[2]!=0:raise ValueError('Supplied source references, qualifications or paragraphs were not completely preserved')
    if book.get('collection')!='seerah' and book.get('referenceReadiness')is None:return
    check=book.get('referenceReadiness')
    if not isinstance(check,dict) or check.get('units')!=len(book.get('units',[])) or check.get('auditedUnits')!=len(book.get('units',[])) or not book.get('units') or check.get('unboundQuranSegments')!=0 or check.get('unboundHadithSegments')!=0:
        label={'seerah':'Seerah','hadith':'Hadith','articles':'Article'}.get(book.get('collection'),'Book')
        raise ValueError(label+' source citations are incomplete; a layout proof cannot be published as a complete book')
    if any(check.get(field,0) for field in ['unboundScholarSegments','unresolvedSourceReferenceCount']):raise ValueError('Original source references are not completely mapped; preparation cannot be released yet')
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

def validate_footnotes(notes,body,expected,lang,*,preserved_identifiers=(),source_literal_proofs=(),root=None):
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
        if note.findall('.//'+tag('hyperlink')):raise ValueError('Reference links remain in footnotes')
        actual[note_id]=text
    refs=[]
    for ref in body.findall('.//'+tag('footnoteReference')):
        try:refs.append(int(ref.get(tag('id'))))
        except (TypeError,ValueError):raise ValueError('Invalid footnote reference')
    if len(refs)!=len(expected) or len(set(refs))!=len(refs) or set(refs)!=set(actual):raise ValueError('Broken or missing footnote anchors')
    if not isinstance(preserved_identifiers,(list,tuple)):raise ValueError('Invalid footnote identifier bindings')
    if preserved_identifiers:
        if len(preserved_identifiers)!=len(expected):raise ValueError('Footnote identifier bindings do not match the notes')
    else:preserved_identifiers=[[] for _ in expected]
    if not isinstance(source_literal_proofs,(list,tuple)):raise ValueError('Invalid footnote literal bindings')
    if source_literal_proofs:
        if len(source_literal_proofs)!=len(expected):raise ValueError('Footnote literal bindings do not match the notes')
    else:source_literal_proofs=[[] for _ in expected]
    for note_id,identifiers,proofs in zip(refs,preserved_identifiers,source_literal_proofs):
        if proofs:
            from source_literal_text import check_text,proof_list
            check_text(root,actual[note_id],lang,proof_list(proofs))
        else:
            if 'http://' in actual[note_id] or 'https://' in actual[note_id]:raise ValueError('Reference links remain in footnotes')
            native_text(actual[note_id],lang,preserved_identifiers=identifiers)
    # The generator deliberately inserts one space after the footnote marker.
    if any(actual[note_id]!=' '+text for note_id,text in zip(refs,expected)):raise ValueError('Footnote text changed or reordered during Word refresh')

def source_link_destination(url):
    from urllib.parse import urlsplit
    if not isinstance(url,str):return url
    parsed=urlsplit(url)
    # Word/PDF exporters may add the equivalent root slash. Do not normalize
    # scheme/host spelling, query, fragment, encoding or a nonempty path.
    if parsed.scheme in {'http','https'} and parsed.netloc and not parsed.path:
        position=len(parsed.scheme)+3+len(parsed.netloc)
        return url[:position]+'/'+url[position:]
    return url

def validate_source_hyperlinks(body, relationships, expected, language, root):
    if not expected:return
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    from source_literal_text import check_text,proof_list
    required=Counter()
    for link in expected:
        check_text(root,link['url'],language,proof_list(link.get('sourceLiteralProof')),exact=True)
        required[(link['text'],source_link_destination(link['url']))]+=1
    targets={item.get('Id'):item.get('Target') for item in relationships
             if item.get('Type')==R+'/hyperlink' and item.get('TargetMode')=='External'}
    actual=Counter((''.join(node.itertext('{'+W+'}t')),source_link_destination(targets.get(node.get('{'+R+'}id'))))
                   for node in body.iter('{'+W+'}hyperlink'))
    if required-actual:raise ValueError('Required original source credit links changed or disappeared')

def validate_pdf_source_hyperlinks(actual, expected):
    required=Counter(source_link_destination(link['url']) for link in expected)
    if required-Counter(source_link_destination(url) for url in actual):raise ValueError('Required original source credit links are missing from PDF')

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

def validate_page_layout(word,pdf,book):
    """Check physical paper size and complete, proportionate cover placement."""
    layout=book.get('pageLayout')
    cover=pdf.pages[0]
    if layout is None:
        # Historical verified editions used a full-bleed 6-by-9-inch cover.
        if not any(i['x0']<=.5 and i['top']<=.5 and i['x1']>=cover.width-.5 and i['bottom']>=cover.height-.5 for i in cover.images):
            raise ValueError('Cover does not reach every page edge')
        return
    if not isinstance(layout,dict) or layout.get('schema')!='iman-book-page-layout-v1' or (layout.get('paper'),layout.get('widthMM'),layout.get('heightMM'),layout.get('coverFit'))!=('A4',210,297,'contain'):
        raise ValueError('Unsupported physical book page layout')
    for section in word.sections:
        if abs(section.page_width.mm-210)>.1 or abs(section.page_height.mm-297)>.1:
            raise ValueError('Editable Word book is not on A4 paper')
    for page in pdf.pages:
        if abs(page.width-210*72/25.4)>1 or abs(page.height-297*72/25.4)>1:
            raise ValueError('Rendered PDF book is not on A4 paper')
    for item in cover.images:
        width=item['x1']-item['x0'];height=item['bottom']-item['top']
        if not width or not height:continue
        source_size=item.get('srcsize')
        if not source_size or len(source_size)!=2 or not source_size[1]:continue
        centered=abs(item['x0']+item['x1']-cover.width)<=2 and abs(item['top']+item['bottom']-cover.height)<=2
        contained=min(item['x0'],item['top'])>=-1 and item['x1']<=cover.width+1 and item['bottom']<=cover.height+1
        fitted=abs(width-cover.width)<=2 or abs(height-cover.height)<=2
        proportional=abs(width/height-source_size[0]/source_size[1])<=.002
        if centered and contained and fitted and proportional:return
    raise ValueError('A4 cover is cropped, distorted or incorrectly positioned')

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
        if checks.get('sourceLiteralProofs'):
            from source_literal_text import check_text
            check_text(args.root,rendered,book['language'],checks['sourceLiteralProofs'])
        else:native_text(rendered,book['language'])
        with zipfile.ZipFile(file) as z:
            validate_source_hyperlinks(etree.fromstring(z.read('word/document.xml')),
                                      etree.fromstring(z.read('word/_rels/document.xml.rels')),
                                      checks.get('sourceHyperlinks',[]),book['language'],args.root)
            validate_toc(etree.fromstring(z.read('word/document.xml')),book['language'],len(book['units']))
            for name in z.namelist():
                if name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
                    node=etree.fromstring(z.read(name))
                    native_text(''.join(node.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})),book['language'])
        if checks['footnotes']:
            with zipfile.ZipFile(file) as z:
                notes=etree.fromstring(z.read('word/footnotes.xml'));W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
                body=etree.fromstring(z.read('word/document.xml'))
                validate_footnotes(notes,body,checks['footnotes'],book['language'],preserved_identifiers=checks.get('footnoteIdentifiers',()),source_literal_proofs=checks.get('footnoteLiteralProofs',()),root=args.root)
        if not pdf.exists():raise ValueError('Missing rendered PDF')
        contents=verify_contents_pair(file,pdf,book['language']);book['pdfContentsVerification']=contents['pdf']
        if contents['word']:
            word=contents['word'];book['wordPages']=word['pages'];book['wordContentsVerification']=word
        doc=pdfplumber.open(pdf)
        if len(doc.pages)<3:raise ValueError('Unexpected short/empty book')
        if book['language'] in {'ar','ur','fa'} and len(doc.pages)>=10000:raise ValueError('Native pagination needs more than four digit positions')
        validate_page_layout(Document(file),doc,book)
        source_link_targets=[]
        for n,page in enumerate(doc.pages):
            if checks.get('sourceHyperlinks'):
                source_link_targets.extend(link.get('uri') for link in page.hyperlinks if link.get('uri'))
            if n==0:continue # illustrated cover
            if book['language'] in {'ar','ur','fa'}:
                footer=''.join(c['text'] for c in sorted((c for c in page.chars if c['top']>page.height-34),key=lambda c:c['x0'])).strip()
                if footer!=digits(str(n+1),book['language']):raise ValueError(f'Wrong native page number on physical page {n+1}: {footer!r}')
            if not (page.extract_text() or '').strip():raise ValueError(f'Unexpected blank page: {file.name}:{n+1}')
            for word in page.extract_words():
                if '\ufffd' in word['text']:raise ValueError('Replacement glyph in exported book')
                if word['x0'] < -1 or word['top'] < -1 or word['x1'] > page.width+1 or word['bottom'] > page.height+1:raise ValueError('Text outside page bounds')
            page.close()  # Release per-page rendering caches during long-book validation.
        validate_pdf_source_hyperlinks(source_link_targets,checks.get('sourceHyperlinks',[]))
        book['audioQRVerification']=validate_audio_qr(file,doc,book.get('audioPanels',[]))
        book['pages']=len(doc.pages);doc.close();book['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        font_conf=json.loads((args.root/'books/config.json').read_text(encoding='utf8'))
        verify_embedded_fonts(file,font_conf,book['language'])
        url=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(file.name,safe='')}"
        book['download']=url;download=f'[Word]({url})'
        book['pdfDownload']=f"https://github.com/{args.repo}/releases/download/{quote(args.tag,safe='')}/{quote(pdf.name,safe='')}"
        book['pdfSha256']=hashlib.sha256(pdf.read_bytes()).hexdigest();book['exportVerified']=not args.prepare_only;book['preparationVerified']=True;book['previewOnly']=bool(index.get('previewOnly'))
        download+=f" · [PDF]({book['pdfDownload']})"
        lang=book['language'];lc=locale(lang);labels=download_labels(lang);page=pages.setdefault(lang,['# '+book['languageLabel'],''])
        page+=['## '+book['collectionLabel'],'',f'[{labels["docx"]}]({url})','']
        page+=[f'[{labels["pdf"]}]({book["pdfDownload"]})','']
    for lang,page in pages.items():
        # URLs are link targets, never visible source labels in a book or native page.
        for text in page:
            visible=text.split('](',1)[0].lstrip('[') if '](' in text else text
            native_download_text(visible,lang)
        filename='INDEX_'+lang+'.md';(folder/filename).write_text('\n'.join(page),encoding='utf-8')
        lines.append(f'[{locale(lang)["nativeName"]}](https://github.com/{args.repo}/releases/download/{args.tag}/{filename})\n')
    (folder/'INDEX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');(folder/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    assets=sorted(list(folder.glob('*.docx'))+list(folder.glob('*.pdf')))
    (folder/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets),encoding='utf-8')
if __name__=='__main__':main()
