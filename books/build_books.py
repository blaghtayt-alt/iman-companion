"""Render approved, normalized reader units into one editable Word book per language/category.

No translation or editorial rewriting occurs here. Integration supplies the reader units
and source/review bindings; unsupported or incomplete input fails before publication.
"""
from pathlib import Path
import argparse,hashlib,json,re,sys,zipfile,uuid,datetime
from copy import deepcopy
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_LINE_SPACING
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.text.paragraph import Paragraph
from lxml import etree
from PIL import Image
from locale_copy import locale
from reader_xml import body_text
from material_audio import load_registry,add_audio_panel
from bibliography import native_text,digits,hadith_citation,quran_reference,edition_credit,expand_verse_key
from book_typography import SYMBOLS,SYMBOL_LTR,SYMBOL_RTL,quotation_mirrors,block_mirrors,span_mirrors
from script_fallbacks import FONT_FAMILIES,extra_font_keys,fallback_runs

SCHEMA='iman-book-unit-v1'
ROLES={'body':'000000','meaning':'000000','example':'000000','note':'000000','current-ayah':'7C3AED','quran':'7C3AED','related':'2563EB','hadith':'2563EB','scholar':'A95300','heading':'064534'}
RTL={'ar','ur','fa'}
KINDS={'paragraph','heading','ayah','translation','quotation','note','credit','list-item'}
COLLECTIONS={'tadabbur-extended','articles','seerah','hadith'}
ARABIC_RUN=r'[\u0600-\u06ff\u0750-\u077f\u0870-\u08ff\ufb50-\ufdff\ufe70-\ufeff]'
PAGE_LAYOUT={'schema':'iman-book-page-layout-v1','paper':'A4','widthMM':210,'heightMM':297,'contentMarginMM':18,'coverFit':'contain'}

def expected_page_layout():return dict(PAGE_LAYOUT)

def digest(data):return hashlib.sha256(data).hexdigest()
def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def el(parent,name,attrs=None):
    child=OxmlElement(name)
    for k,v in (attrs or {}).items():child.set(qn(k) if ':' in k else k,str(v))
    parent.append(child);return child
def inside(root,relative):
    file=(root/relative).resolve()
    if root.resolve() not in file.parents:raise ValueError('Input escapes repository: '+relative)
    return file

def checked_credit(credit, unit, root):
    if not credit.get('sourceLiteralProof'):
        return edition_credit(credit, unit['language'])
    if credit.get('language') != unit['language'] or not isinstance(credit.get('text'), str) or not credit['text'].strip():
        raise ValueError('Translation credit must preserve its actual language and text')
    from source_literal_text import check_bound_text
    return check_bound_text(root, credit['text'], unit, credit['sourceLiteralProof'])

def checked_source_links(unit, section, block, root):
    links = block.get('hyperlinks', [])
    if not links:
        return []
    if (section.get('sourceOnlyContext') is not True or block.get('sourceOnlyContext') is not True
            or block.get('kind') != 'paragraph' or block.get('spans') or block.get('citations')
            or not block.get('sourceLiteralProof') or not isinstance(links, list)):
        raise ValueError('Source credit links need a separate exact source-context paragraph')
    from source_literal_text import check_bound_text
    from urllib.parse import urlsplit
    previous = 0
    for link in links:
        start, end, url = link.get('start'), link.get('end'), link.get('url')
        if (type(start) is not int or type(end) is not int
                or not previous <= start < end <= len(block['text']) or not isinstance(url, str)):
            raise ValueError('Invalid or overlapping exact source credit link')
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Source credit link must retain an original public web address')
        check_bound_text(root, url, unit, link.get('sourceLiteralProof'), exact=True)
        previous = end
    from source_literal_text import check_link_associations
    check_link_associations(root, unit, block)
    return links

def check_unit(unit,record,quran=None,*,root=None):
    if unit.get('schema')!=SCHEMA:raise ValueError('Unsupported book input schema')
    for key in ['language','collection','id']:
        if unit[key]!=record[key]:raise ValueError('Manifest identity mismatch: '+key)
    if not isinstance(unit['id'],str) or not unit['id'].strip():raise ValueError('Reader unit needs a nonempty string identity')
    if unit['collection'] not in COLLECTIONS:raise ValueError('Unknown collection')
    if unit['collection']=='hadith' and (type(unit.get('order')) is not int or unit['order']<=0):raise ValueError('Hadith unit needs its canonical positive source order')
    if unit.get('sourceLessonNumber') is not None and (unit['collection']!='hadith' or type(unit['sourceLessonNumber']) is not int or unit['sourceLessonNumber']<1 or unit['sourceLessonNumber']!=unit.get('lesson')):raise ValueError('Visible Hadith lesson number must match its explicit source position')
    if unit['collection']=='hadith' and (unit.get('hadithEdition')!='new-extended' or any(b.get('collection')!='essential-hadith' for b in unit.get('catalogBindings',[]))):raise ValueError('Only the new extended Essential Iman Hadith lessons belong in this book; reject the legacy short collection')
    if unit.get('complete') is not True or unit.get('reviewGate')!='published-current':raise ValueError('Unit not cleared for current publication')
    if not unit.get('sourceHashes') or not all(re.fullmatch('[a-f0-9]{64}',x) for x in unit['sourceHashes']):raise ValueError('Missing source binding')
    if not unit.get('title') or not unit.get('sections'):raise ValueError('Empty reader unit')
    if not unit.get('titleIsReference'):native_text(unit['title'],unit['language'])
    for credit in unit.get('translationCredits',[]):checked_credit(credit,unit,root)
    alltext=[]
    for section in unit['sections']:
        if section.get('heading') and not section.get('titleIsReference'):native_text(section['heading'],unit['language'])
        blocks=section['blocks']
        if not blocks:raise ValueError('Empty section')
        if unit['collection']=='tadabbur-extended' and section.get('ayahKey'):
            expected=['ayah'] if unit['language']=='ar' else ['ayah','translation']
            if [b['kind'] for b in blocks[:len(expected)]]!=expected:raise ValueError('Required Arabic → translation → tadabbur sequence missing')
            if blocks[0].get('verseKey')!=section['ayahKey']:raise ValueError('Arabic ayah key mismatch')
            if quran is not None and blocks[0]['text']!=quran.get(section['ayahKey']):raise ValueError('Arabic ayah differs from approved canonical text')
            if unit['language']!='ar' and not (blocks[1].get('translationCredit') or unit.get('translationCredits')):raise ValueError('Published translator/edition credit missing')
        for b in blocks:
            checked_source_links(unit,section,b,root)
            if b['kind'] not in KINDS:raise ValueError('Unknown reader block: '+b['kind'])
            if not isinstance(b.get('text'),str):raise ValueError('Non-text reader block')
            if b.get('spans') and ''.join(s['text'] for s in b['spans'])!=b['text']:raise ValueError('Span text differs from reader text')
            if b.get('role','body') not in ROLES or any(s.get('role','body') not in ROLES for s in b.get('spans',[])):raise ValueError('Unknown semantic color role')
            if b.get('sourceCredit'):raise ValueError('Replace legacy website sourceCredit with original-book citations or a localized translationCredit')
            if b.get('preservedIdentifiers') and b['kind']!='note':raise ValueError('Source identifiers may only exempt literal reference notes')
            if b.get('sourceLiteralProof'):
                if b['kind'] not in {'paragraph','quotation','list-item','translation','note','heading'}:raise ValueError('Source-literal exceptions are limited to exact reader text')
                from source_literal_text import check_bound_text
                check_bound_text(root,b['text'],unit,b['sourceLiteralProof'],exact=True)
            elif b['kind'] not in {'ayah','credit'}:native_text(b['text'],unit['language'],preserved_identifiers=b.get('preservedIdentifiers',()) if b['kind']=='note' else ())
            for span in b.get('spans',[]):
                note_texts=span.get('noteTexts',[]);note_identifiers=span.get('noteIdentifiers',[[] for _ in note_texts])
                if not isinstance(note_identifiers,list) or len(note_identifiers)!=len(note_texts):raise ValueError('Source note identifier bindings do not match the notes')
                note_proofs=span.get('noteLiteralProofs',[None for _ in note_texts])
                if not isinstance(note_proofs,list) or len(note_proofs)!=len(note_texts):raise ValueError('Source note literal bindings do not match the notes')
                for note,identifiers,proofs in zip(note_texts,note_identifiers,note_proofs):
                    if proofs:
                        from source_literal_text import check_bound_text
                        check_bound_text(root,note,unit,proofs)
                    else:native_text(note,unit['language'],preserved_identifiers=identifiers)
            if b.get('translationCredit'):checked_credit(b['translationCredit'],unit,root)
            for citation in b.get('citations',[]):hadith_citation(citation,unit['language'])
            if b['kind']=='credit' and not b.get('citations'):raise ValueError('Reference needs original collection and narration number')
            if quran is not None:
                for span in b.get('spans',[]):
                    if any(key not in quran for value in span.get('verseKeys',[]) for key in expand_verse_key(value)):raise ValueError('Invalid supporting Quran reference')
                    for citation in span.get('citations',[]):hadith_citation(citation,unit['language'])
            alltext.append(b['text'])
    if digest(''.join(alltext).encode())!=unit['readerTextSHA256']:raise ValueError('Reader fidelity check failed')

def fonts_for(conf,lang,root):
    f=conf['fonts'][conf['languages'][lang]['font']]
    ar=conf['fonts']['Arabic']
    result={}
    extra=[conf['fonts'][k]for k in['SymbolsLTR','SymbolsRTL']if k in conf['fonts']]
    extra.extend(conf['fonts'][key] for key in extra_font_keys(lang))
    native={'ar':'DigitsArabic','ur':'DigitsPersian','fa':'DigitsPersian'}.get(lang)
    if native and native in conf['fonts']:extra.append(conf['fonts'][native])
    for family in [f,ar,conf['fonts']['Latin'],*extra]:
        styles={}
        for style,relative in family['files'].items():
            p=inside(root,relative)
            if digest(p.read_bytes())!=family['sha256'][style]:raise ValueError('Font hash mismatch')
            styles[style]=p
        result[family['family']]=styles
    return f['family'],ar['family'],result

def embed_fonts(file,fonts,footnotes=None):
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';P='http://schemas.openxmlformats.org/package/2006/relationships'
    with zipfile.ZipFile(file) as z:parts={n:z.read(n) for n in z.namelist()}
    table=etree.Element('{'+W+'}fonts',nsmap={'w':W,'r':R});rels=etree.Element('{'+P+'}Relationships',nsmap={None:P})
    for i,(family,styles) in enumerate(fonts.items()):
        node=etree.SubElement(table,'{'+W+'}font',{'{'+W+'}name':family})
        etree.SubElement(node,'{'+W+'}family',{'{'+W+'}val':'swiss'})
        for style,p in styles.items():
            key=uuid.uuid5(uuid.NAMESPACE_URL,'iman-book:'+family+style+digest(p.read_bytes()));mask=key.bytes[::-1];data=bytearray(p.read_bytes())
            for j in range(32):data[j]^=mask[j%16]
            target=f'fonts/book-{i}-{style}.odttf';rid=f'bookfont-{i}-{style}';parts['word/'+target]=bytes(data)
            etree.SubElement(node,'{'+W+'}embed'+style,{'{'+R+'}id':rid,'{'+W+'}fontKey':'{'+str(key).upper()+'}'})
            etree.SubElement(rels,'{'+P+'}Relationship',{'Id':rid,'Type':R+'/font','Target':target})
    parts['word/fontTable.xml']=etree.tostring(table,xml_declaration=True,encoding='UTF-8',standalone=True);parts['word/_rels/fontTable.xml.rels']=etree.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
    ct=etree.fromstring(parts['[Content_Types].xml']);ns='http://schemas.openxmlformats.org/package/2006/content-types'
    if not any(x.get('Extension')=='odttf' for x in ct):etree.SubElement(ct,'{'+ns+'}Default',{'Extension':'odttf','ContentType':'application/vnd.openxmlformats-officedocument.obfuscatedFont'})
    if footnotes is not None:
        parts['word/footnotes.xml']=etree.tostring(footnotes,xml_declaration=True,encoding='UTF-8',standalone=True)
        rel=etree.fromstring(parts['word/_rels/document.xml.rels'])
        if not any(x.get('Type')==R+'/footnotes' for x in rel):etree.SubElement(rel,'{'+P+'}Relationship',{'Id':'rIdBookFootnotes','Type':R+'/footnotes','Target':'footnotes.xml'})
        parts['word/_rels/document.xml.rels']=etree.tostring(rel,xml_declaration=True,encoding='UTF-8',standalone=True)
        if not any(x.get('PartName')=='/word/footnotes.xml' for x in ct):etree.SubElement(ct,'{'+ns+'}Override',{'PartName':'/word/footnotes.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'})
    parts['[Content_Types].xml']=etree.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)

def add_text(p,text,lang,family,arabic,size=11,color='body',bold=False,ornament_mirrors=None):
    # Split script runs explicitly so embedded fonts travel with the file.
    number=r'[0-9\u0660-\u0669\u06f0-\u06f9]+(?:[:/–\-][0-9\u0660-\u0669\u06f0-\u06f9]+)*'
    # Keep a literal citation marker in the same LTR run as its number. Mixing
    # RTL brackets with an LTR number lets the brackets break onto another line.
    numeric=r'\['+number+r'(?:\s*[,،]\s*'+number+r')*\]|'+number
    pieces=[];offset=0
    mirrors=quotation_mirrors(text,lang)if ornament_mirrors is None else ornament_mirrors
    for segment in re.split('('+numeric+')',text):
        if re.fullmatch(numeric,segment):pieces.append((segment,True,offset));offset+=len(segment)
        else:
            for token in re.split('(['+SYMBOLS+'])',segment):
                if token in SYMBOLS and token:pieces.append((token,False,offset));offset+=len(token)
                else:
                    for piece in re.split('('+ARABIC_RUN+'+(?:\\s+'+ARABIC_RUN+'+)*)',token):pieces.append((piece,False,offset));offset+=len(piece)
    selected=[]
    for piece,is_number,position in pieces:
        for fragment,key in fallback_runs(piece,lang):
            selected.append((fragment,is_number,position,key));position+=len(fragment)
    for piece,is_number,position,fallback in selected:
        if not piece:continue
        is_ar=bool(re.search(ARABIC_RUN,piece));font=family if lang in RTL else (arabic if is_ar else family)
        if piece in SYMBOLS and piece:font=SYMBOL_LTR if piece!='\ufdfa'and mirrors.get(position,lang not in RTL)else SYMBOL_RTL
        if lang in RTL and re.search('[A-Za-z]',piece) and not is_ar:font='Iman Book Inter'
        # A grouped citation also needs one face covering every glyph. The
        # Arabic app face lacks ASCII brackets; renderer fallback can split
        # the marker again. These already embedded faces cover the whole run.
        if is_number and piece.startswith('['):font=arabic if is_ar else 'Iman Book Inter'
        if fallback:font=FONT_FAMILIES[fallback]
        r=p.add_run(piece);r.font.name=font;r.font.size=Pt(size);r.bold=bold;r.font.color.rgb=RGBColor.from_string(ROLES.get(color,ROLES['body']))
        rp=r._r.get_or_add_rPr();rf=rp.find(qn('w:rFonts'))
        if rf is None:rf=el(rp,'w:rFonts')
        for a in ['ascii','hAnsi','eastAsia','cs']:rf.set(qn('w:'+a),font)
        el(rp,'w:szCs',{'w:val':round(size*2)});el(rp,'w:bCs',{'w:val':int(bold)})
        # The exceptional ornate parentheses are neutral punctuation, even though
        # their codepoints belong to Arabic Presentation Forms. Keep the book's
        # neutral-run direction; the selected symbol face handles glyph painting.
        is_ornament=piece in {'\ufd3e','\ufd3f'}
        run_rtl=(lang in RTL) if is_ornament else (is_ar or (lang in RTL and not re.search('[A-Za-z]',piece)))
        el(rp,'w:rtl',{'w:val':0 if is_number else int(run_rtl)})
        el(rp,'w:lang',{'w:val':lang,'w:eastAsia':lang,'w:bidi':'ar-SA' if is_ar else lang})

def direction(p,lang,center=False):
    pp=p._p.get_or_add_pPr();old=pp.find(qn('w:jc'))
    if old is not None:pp.remove(old)
    bidi=pp.find(qn('w:bidi'))
    if bidi is None:bidi=el(pp,'w:bidi')
    bidi.set(qn('w:val'),'1' if lang in RTL else '0')
    # Logical start is physical right for Arabic, Urdu and Persian.
    el(pp,'w:jc',{'w:val':'center' if center else 'start'})

def add_bookmark(paragraph,name,ident):
    start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(ident));start.set(qn('w:name'),name)
    paragraph._p.insert(1 if paragraph._p.find(qn('w:pPr'))is not None else 0,start)
    el(paragraph._p,'w:bookmarkEnd',{'w:id':ident})

def reference_text(text):
    text=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)
    text=re.sub(r'https?://\S+|\bwww\.\S+','',text)
    text=re.sub(r'\s*[·|]\s*(?=[·|]|$)',' ',text)
    text=re.sub(r'[ \t]+',' ',text).strip(' ·|\n')
    if not text:raise ValueError('Reference needs a readable source name after removal of web links')
    return text

def add_source_link_text(paragraph, text, links, lang, family, arabic, size=11, *, ornament_mirrors=None):
    """Keep source credit words exact while retaining required clickable URLs."""
    mirrors = quotation_mirrors(text, lang) if ornament_mirrors is None else ornament_mirrors
    cursor = 0
    for link in [*links, {'start': len(text), 'end': len(text), 'url': None}]:
        start, end = link['start'], link['end']
        if cursor < start:
            add_text(paragraph, text[cursor:start], lang, family, arabic, size,
                     ornament_mirrors={pos-cursor:value for pos,value in mirrors.items() if cursor <= pos < start})
        if start < end:
            count = len(paragraph._p)
            add_text(paragraph, text[start:end], lang, family, arabic, size,
                     ornament_mirrors={pos-start:value for pos,value in mirrors.items() if start <= pos < end})
            hyperlink = OxmlElement('w:hyperlink')
            hyperlink.set(qn('r:id'), paragraph.part.relate_to(link['url'], RT.HYPERLINK, is_external=True))
            for run in list(paragraph._p)[count:]:
                hyperlink.append(run)
            paragraph._p.append(hyperlink)
        cursor = end

class Footnotes:
    def __init__(self,doc,lang,family,arabic,*,source_root=None):
        self.doc=doc;self.lang=lang;self.family=family;self.arabic=arabic;self.texts=[];self.identifiers=[];self.literal_proofs=[];self.source_root=source_root;self.anchors={};self.root=OxmlElement('w:footnotes')
        for number,kind in [(-1,'separator'),(0,'continuationSeparator')]:
            note=el(self.root,'w:footnote',{'w:id':number,'w:type':kind});el(el(note,'w:p'),'w:r');el(note[0][0],'w:'+kind)
    def add(self,anchor,text,group=None,*,preserved_identifiers=(),source_literal_proofs=None):
        from source_literal_text import proof_list,check_text
        proofs=proof_list(source_literal_proofs)
        if proofs:check_text(self.source_root,text,self.lang,proofs)
        else:text=native_text(reference_text(text),self.lang,preserved_identifiers=preserved_identifiers)
        key=(anchor._p,group)
        if key in self.anchors:
            index,note=self.anchors[key];paragraph=Paragraph(note[-1],self.doc._body);separator='؛ ' if self.lang in RTL else '; ';add_text(paragraph,separator+text,self.lang,self.family,self.arabic,9,'note');self.texts[index]+=separator+text;self.identifiers[index]=list(dict.fromkeys([*self.identifiers[index],*preserved_identifiers]));self.literal_proofs[index].extend(proofs);return
        number=len(self.texts)+1;self.texts.append(text);self.identifiers.append(list(preserved_identifiers));self.literal_proofs.append(proofs)
        r=anchor.add_run();r.font.size=Pt(9);rp=r._r.get_or_add_rPr();el(rp,'w:vertAlign',{'w:val':'superscript'});el(rp,'w:rtl',{'w:val':0});el(rp,'w:rFonts',{'w:ascii':'Iman Book Inter','w:hAnsi':'Iman Book Inter','w:cs':'Iman Book Inter'});el(r._r,'w:footnoteReference',{'w:id':number})
        note=el(self.root,'w:footnote',{'w:id':number});p=self.paragraph(note)
        run=p.add_run();run.font.name='Iman Book Inter';run.font.size=Pt(9);el(run._r.get_or_add_rPr(),'w:vertAlign',{'w:val':'superscript'});el(run._r,'w:footnoteRef')
        add_text(p,' '+text,self.lang,self.family,self.arabic,9,'note')
        self.anchors[key]=(number-1,note)
    def paragraph(self,note):
        node=el(note,'w:p');p=Paragraph(node,self.doc._body);direction(p,self.lang)
        p.paragraph_format.line_spacing_rule=WD_LINE_SPACING.AT_LEAST;p.paragraph_format.line_spacing=Pt(18 if self.lang=='ur' else 12);p.paragraph_format.space_after=Pt(3)
        return p
    def wrap_trailing_markers(self):
        """Let dense Bengali/Urdu marker tails paginate without changing source text."""
        if self.lang not in {'bn','ur'}:return 0
        changed=0
        for paragraph in dict.fromkeys(anchor for anchor,group in self.anchors):
            markers=[]
            for run in reversed(list(paragraph)):
                content=[node for node in run if node.tag!=qn('w:rPr')]
                if run.tag!=qn('w:r') or len(content)!=1 or content[0].tag!=qn('w:footnoteReference'):break
                markers.append(run)
            markers.reverse()
            # Bengali/Urdu source notes can cluster dozens of first lines at
            # one anchor, demanding more footnote space than a page provides.
            # Break only generated marker tails, after all source words; no
            # reference moves to a different paragraph or changes identity.
            for index in range(7,len(markers)-1,8):
                el(markers[index],'w:br');changed+=1
        return changed

def canonical_key(unit):
    nums=[int(x) for x in re.findall(r'\d+',unit['id'])]
    if unit['collection']=='tadabbur-extended':
        n=unit.get('surah',unit.get('order',nums[0] if nums else None))
        if type(n)is not int or not 1<=n<=114:raise ValueError('Quran unit needs a valid surah number')
        if unit.get('order',n)!=n or (nums and nums[0]!=n):raise ValueError('Conflicting canonical surah order')
        return (n,nums[1] if len(nums)>1 else 0)
    from material_order import position
    _,value=position(unit)
    return (*value,unit['id'])

def cover_page(doc,cover,width,height):
    """Center the complete, untouched cover on the page without cropping it."""
    sec=doc.sections[0];sec.page_width=width;sec.page_height=height
    sec.top_margin=sec.bottom_margin=sec.left_margin=sec.right_margin=0
    sec.header_distance=sec.footer_distance=0
    p=doc.add_paragraph();p.paragraph_format.space_before=p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(1)
    with Image.open(cover) as image:pixel_width,pixel_height=image.size
    scale=min(width/pixel_width,height/pixel_height)
    picture_width=round(pixel_width*scale);picture_height=round(pixel_height*scale)
    inline=p.add_run().add_picture(str(cover),width=picture_width,height=picture_height)._inline
    anchor=OxmlElement('wp:anchor')
    for k,v in {'distT':0,'distB':0,'distL':0,'distR':0,'simplePos':0,'relativeHeight':0,'behindDoc':1,'locked':0,'layoutInCell':1,'allowOverlap':1}.items():anchor.set(k,str(v))
    el(anchor,'wp:simplePos',{'x':0,'y':0})
    for axis in ['H','V']:
        offset=(width-picture_width)/2 if axis=='H' else (height-picture_height)/2
        pos=el(anchor,'wp:position'+axis,{'relativeFrom':'page'});el(pos,'wp:posOffset').text=str(round(offset))
    for tag in ['wp:extent','wp:effectExtent']:
        item=inline.find(qn(tag))
        if item is not None:anchor.append(deepcopy(item))
    el(anchor,'wp:wrapNone')
    for tag in ['wp:docPr','wp:cNvGraphicFramePr','a:graphic']:
        item=inline.find(qn(tag))
        if item is not None:anchor.append(deepcopy(item))
    inline.getparent().replace(inline,anchor)
    return doc.add_section(WD_SECTION.NEW_PAGE)

def build_book(root,out,conf,lang,collection,units,commit,edition_report=None):
    if collection not in COLLECTIONS:raise ValueError('Only public collection books can be built')
    lc={**conf['languages'][lang],**locale(lang)};family,arabic,fonts=fonts_for(conf,lang,root)
    audio_registry=load_registry(root,conf);audio_panels=[]
    names=load(inside(root,conf['surahNames']['path']))
    if digest(inside(root,conf['surahNames']['path']).read_bytes())!=conf['surahNames']['sha256']:raise ValueError('Surah name source hash mismatch')
    for field in ['brand','notice','contents','hadithLabel','creditsTitle']:native_text(lc[field],lang)
    native_text(lc['titles'][collection],lang)
    credits=[];credit_literal_proofs=[]
    for unit in units:
        entries=list(unit.get('translationCredits',[]))
        entries.extend(b['translationCredit'] for section in unit['sections'] for b in section['blocks'] if b.get('translationCredit'))
        for item in entries:
            text=checked_credit(item,unit,root)
            if text not in credits:
                credits.append(text)
                if item.get('sourceLiteralProof'):
                    from source_literal_text import proof_list
                    credit_literal_proofs.extend(proof_list(item['sourceLiteralProof']))
    title=lc['titles'][collection];size=13 if lang=='ur' else (12 if lang in RTL|{'bn','hi','th'} else 11);line=28 if lang=='ur' else (22 if lang in RTL else 18)
    cover=inside(root,lc['covers'][collection]);expected=lc['coverHashes'][collection]
    if digest(cover.read_bytes())!=expected:raise ValueError('Cover hash mismatch')
    doc=Document();sec=cover_page(doc,cover,Mm(210),Mm(297))
    sec.page_width=Mm(210);sec.page_height=Mm(297)
    sec.top_margin=sec.bottom_margin=Mm(18);sec.left_margin=sec.right_margin=Mm(18);sec.header_distance=sec.footer_distance=Mm(8)
    sec.header.is_linked_to_previous=False;sec.footer.is_linked_to_previous=False;sec.different_first_page_header_footer=False
    for name in ['TOC 1','TOC 2']:
        if name not in doc.styles:doc.styles.add_style(name,1)
    for style in doc.styles:
        if style.type==1:
            style.font.name=family;style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
            rf=style._element.get_or_add_rPr().find(qn('w:rFonts'))
            if rf is None:rf=el(style._element.rPr,'w:rFonts')
            for a in list(rf.attrib):
                if a.endswith('Theme'):del rf.attrib[a]
            for a in ['ascii','hAnsi','eastAsia','cs']:rf.set(qn('w:'+a),family)
            # Generated TOC/PAGE text has no authored runs to split. Thai
            # letters use the native complex-script face; generated ASCII
            # digits and punctuation use the pinned Latin style slots.
            if lang=='th':
                for a in ['ascii','hAnsi']:rf.set(qn('w:'+a),FONT_FAMILIES['Latin'])
            if lang in RTL and style.name in {'Normal','TOC 1','TOC 2'}:
                pp=style._element.get_or_add_pPr()
                bidi=pp.find(qn('w:bidi'))
                if bidi is None:bidi=el(pp,'w:bidi')
                bidi.set(qn('w:val'),'1')
                old=pp.find(qn('w:jc'))
                if old is not None:pp.remove(old)
                el(pp,'w:jc',{'w:val':'start'})
    for border in doc.styles.element.xpath('.//w:pBdr'):border.getparent().remove(border)
    ct=doc.styles.add_style('BookContentsTitle',1);ct.base_style=doc.styles['Title'];el(ct._element.get_or_add_pPr(),'w:outlineLvl',{'w:val':9})
    normal=doc.styles['Normal'];normal.paragraph_format.line_spacing_rule=WD_LINE_SPACING.AT_LEAST;normal.paragraph_format.line_spacing=Pt(line);normal.paragraph_format.space_after=Pt(7);normal.paragraph_format.widow_control=True
    for name,n in [('Title',26),('Heading 1',22),('Heading 2',17),('Heading 3',13)]:
        style=doc.styles[name];style.font.size=Pt(n);style.font.bold=True;style.font.color.rgb=RGBColor.from_string(ROLES['heading']);style.paragraph_format.keep_with_next=True
    scope_titles=[u['title'] for u in units] if edition_report else []
    multi_surah=collection=='tadabbur-extended' and len(units)>1
    scope_summary=(scope_titles[0]+(f' (+{len(scope_titles)-1})' if len(scope_titles)>1 else '')) if scope_titles else ''
    if multi_surah:scope_summary=''
    scoped_label=title+(' · '+scope_summary if scope_summary else '')
    p=sec.header.paragraphs[0];direction(p,lang);add_text(p,lc['brand']+' · '+scoped_label,lang,family,arabic,8,'heading')
    p=sec.footer.paragraphs[0];direction(p,'en',True)
    if lang in RTL:
        from native_pagination import append_native_number
        append_native_number(p,'PAGE',lang,family)
    else:
        r=p.add_run()
        if lang=='th':
            rf=el(r._r.get_or_add_rPr(),'w:rFonts')
            for a in ['ascii','hAnsi','eastAsia','cs']:rf.set(qn('w:'+a),FONT_FAMILIES['Latin'])
        el(r._r,'w:fldChar',{'w:fldCharType':'begin'});el(r._r,'w:instrText').text=' PAGE ';el(r._r,'w:fldChar',{'w:fldCharType':'end'})
    p=doc.add_paragraph(style='Title');direction(p,lang);add_text(p,title,lang,family,arabic,26,'heading',True)
    if scope_summary:
        p=doc.add_paragraph();direction(p,lang);add_text(p,scope_summary,lang,family,arabic,17,'heading',True)
    p=doc.add_paragraph();direction(p,lang);add_text(p,lc['brand'],lang,family,arabic,size)
    if lang!='ar':
        p=doc.add_paragraph();direction(p,lang);add_text(p,lc['notice'],lang,family,arabic,10)
    if credits:
        p=doc.add_paragraph();direction(p,lang);add_text(p,lc['creditsTitle'],lang,family,arabic,11,'heading',True)
        for text in credits:
            p=doc.add_paragraph();direction(p,lang);add_text(p,text,lang,family,arabic,10)
    p=doc.add_paragraph(style='BookContentsTitle');direction(p,lang);add_text(p,lc['contents'],lang,family,arabic,22,'heading',True)
    if lang=='ur':p.paragraph_format.page_break_before=True
    contents_levels='1-1' if multi_surah else '1-2'
    contents_extra='' if multi_surah else '\\u '
    p=doc.add_paragraph();direction(p,lang);r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'begin'});r=p.add_run();el(r._r,'w:instrText').text=' TOC \\o "'+contents_levels+'" \\h \\z '+contents_extra;r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'separate'});r=p.add_run(' ');r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'end'})
    preserved=[];notes=Footnotes(doc,lang,family,arabic,source_root=root);hadith_count=0;last_chapter=None
    for unit_index,unit in enumerate(units):
        unit_mirrors=block_mirrors(unit,lang)
        allow_numbered_surah=False
        if lang in {'bn','hi'}:
            from current_reviewed_quran import ADAPTER as current_quran_adapter
            allow_numbered_surah=unit.get('provenance',{}).get('adapter')==current_quran_adapter
        aggregate_hadith=unit['collection']=='hadith' and any(s.get('hadith') is True for s in unit['sections'])
        display_title=unit['title']
        if unit['collection']=='hadith' and not aggregate_hadith:
            hadith_count+=1;display_title=f"{lc['hadithLabel']} {digits(unit.get('sourceLessonNumber',hadith_count),lang)}"
        new_page=unit_index==0 or unit['collection']!='hadith' or (unit.get('chapter') is not None and unit.get('chapter')!=last_chapter)
        chapter_title=unit.get('chapterTitle') if unit['collection']=='hadith' else None
        audio_heading_paragraphs=[]
        if chapter_title and (unit_index==0 or unit.get('chapter')!=last_chapter):
            native_text(chapter_title,lang);p=doc.add_paragraph(style='Heading 1');p.paragraph_format.page_break_before=True;direction(p,lang);add_text(p,chapter_title,lang,family,arabic,20,'heading',True);audio_heading_paragraphs.append(p);new_page=False
        p=doc.add_paragraph(style='Heading 2' if chapter_title else 'Heading 1');p.paragraph_format.page_break_before=new_page;direction(p,lang);add_text(p,display_title,lang,family,arabic,18 if unit['collection']=='hadith' else 22,'heading',True)
        audio_heading_paragraphs.append(p)
        if unit['collection']=='tadabbur-extended':add_bookmark(p,'surah_'+str(unit['surah']).zfill(3),1000000+unit['surah'])
        if unit.get('coverageLabel'):
            native_text(unit['coverageLabel'],lang);coverage_paragraph=doc.add_paragraph();direction(coverage_paragraph,lang)
            coverage_paragraph.paragraph_format.keep_with_next=True;add_text(coverage_paragraph,unit['coverageLabel'],lang,family,arabic,11,'body')
        if unit['collection']=='hadith' and not aggregate_hadith and not unit.get('titleIsReference') and unit['title']!=lc['hadithLabel']:
            p=doc.add_paragraph(style='Heading 3' if chapter_title else 'Heading 2');direction(p,lang);add_text(p,unit['title'],lang,family,arabic,15,'heading',True)
            audio_heading_paragraphs.append(p)
        panel=add_audio_panel(doc,unit,audio_registry,family,arabic,add_text,direction,heading_paragraphs=audio_heading_paragraphs,fonts=fonts,cache_root=root/'books/.cache/audio-cards')
        if panel:audio_panels.append(panel)
        last_chapter=unit.get('chapter')
        last_content=p
        for section in unit['sections']:
            for scope_note in unit.get('sourceScopeNotes',[]):
                if scope_note['beforeSection']!=section.get('ayahKey'):continue
                p=doc.add_paragraph();direction(p,lang);p.paragraph_format.keep_with_next=True
                add_text(p,scope_note['label']+'\n',lang,family,arabic,11,'heading',True);add_text(p,scope_note['text'],lang,family,arabic,11,'body');preserved.append(scope_note['text'])
            section_title=section.get('heading','')
            if aggregate_hadith and section.get('hadith') is True:
                hadith_count+=1;section_title=f"{lc['hadithLabel']} {digits(hadith_count,lang)}"
            if section_title and section_title.strip()!=unit['title'].strip():
                p=doc.add_paragraph(style='Heading 2');direction(p,lang);add_text(p,section_title,lang,family,arabic,17,'heading',True);last_content=p
                if section.get('ayahKey'):
                    surah_number,ayah_number=map(int,section['ayahKey'].split(':'));add_bookmark(p,f'ayah_{surah_number:03d}_{ayah_number:03d}',1100000+surah_number*1000+ayah_number)
                if aggregate_hadith and section.get('hadith') is True and section.get('heading') and not section.get('titleIsReference'):
                    p=doc.add_paragraph(style='Heading 3');direction(p,lang);add_text(p,section['heading'],lang,family,arabic,14,'heading',True);last_content=p
            for b in section['blocks']:
                kind=b['kind']
                if kind=='credit':
                    if not b.get('citations'):raise ValueError('Reference block needs structured original-book citations')
                    for citation in b['citations']:notes.add(last_content,hadith_citation(citation,lang))
                    continue
                if kind=='note':
                    notes.add(last_content,b['text'],preserved_identifiers=b.get('preservedIdentifiers',()),source_literal_proofs=b.get('sourceLiteralProof'));continue
                p=doc.add_paragraph(style='Heading 3' if kind=='heading' else None);direction(p,'ar' if kind=='ayah' else lang,kind=='ayah');last_content=p
                blocksize=21 if kind=='ayah' else (10 if kind in {'note','credit'} else size)
                if kind in {'ayah','translation','heading'}:p.paragraph_format.keep_with_next=True
                if b.get('hyperlinks'):
                    add_source_link_text(p,b['text'],b['hyperlinks'],lang,family,arabic,blocksize,ornament_mirrors=unit_mirrors[id(b)])
                    preserved.append(b['text']);continue
                spans=b.get('spans') or [{'text':b['text'],'role':b.get('role','current-ayah' if kind in {'ayah','translation'} else ('related' if kind=='quotation' else 'body'))}]
                if collection=='seerah' and kind=='paragraph' and any(s.get('role')=='quran' for s in spans) and all(s.get('role')=='quran' or not s.get('text','').strip() for s in spans):direction(p,'ar',True)
                mirror_maps=span_mirrors(spans,unit_mirrors[id(b)])
                for span_index,span in enumerate(spans):
                    add_text(p,span['text'],'ar' if kind=='ayah' else lang,arabic if kind=='ayah' else family,arabic,blocksize,span.get('role','body'),kind=='heading' or span.get('bold',False),ornament_mirrors=mirror_maps[span_index]);preserved.append(span['text'])
                    if kind not in {'ayah','translation'}:
                        keys=span.get('verseKeys',[])
                        if span.get('explicitSourceReferencePlaced'):keys=[]
                        if not keys and span.get('role')=='current-ayah' and section.get('ayahKey') and not span.get('explicitSourceReferencePlaced'):keys=[section['ayahKey']]
                        if keys:add_text(p,' '+'؛ '.join(quran_reference(key,lang,names,allow_numbered=allow_numbered_surah) for key in keys),lang,family,arabic,10,'body')
                    for citation in span.get('citations',[]):notes.add(p,hadith_citation(citation,lang),group='span-'+str(span_index))
                    for note_index,note in enumerate(span.get('noteTexts',[])):
                        notes.add(p,note,group='source-note-'+str(span_index)+'-'+str(note_index),preserved_identifiers=span.get('noteIdentifiers',[[] for _ in span.get('noteTexts',[])])[note_index],source_literal_proofs=span.get('noteLiteralProofs',[None for _ in span.get('noteTexts',[])])[note_index])
                if kind=='ayah':
                    ref=quran_reference(b['verseKey'],lang,names,allow_numbered=allow_numbered_surah)
                    if lang not in RTL:ref='\u200e'+ref+'\u200e'
                    add_text(p,' '+ref,lang,family,arabic,10,'body')
                for citation in b.get('citations',[]):notes.add(p,hadith_citation(citation,lang))
    notes.wrap_trailing_markers()
    settings=doc.settings.element;el(settings,'w:updateFields',{'w:val':'true'});el(settings,'w:embedTrueTypeFonts',{'w:val':'true'})
    target=out/f'Iman_Companion_{lang}_{collection}.docx';doc.save(target);embed_fonts(target,fonts,notes.root if notes.texts else None)
    rendered=body_text(Document(target).element.body)
    offset=0
    for text in preserved:
        index=rendered.find(text,offset)
        if index<0:raise ValueError('Reader text lost or reordered in Word serialization')
        offset=index+len(text)
    source_literal_proofs=credit_literal_proofs+[b['sourceLiteralProof'] for unit in units for section in unit['sections'] for b in section['blocks'] if b.get('sourceLiteralProof') and b['kind']!='note']
    source_hyperlinks=[{'text':b['text'][link['start']:link['end']],'url':link['url'],'sourceLiteralProof':link['sourceLiteralProof']} for unit in units for section in unit['sections'] for b in section['blocks'] for link in b.get('hyperlinks',[])]
    (out/(target.name+'.reader-checks.json')).write_text(json.dumps({'body':preserved,'footnotes':notes.texts,'footnoteIdentifiers':notes.identifiers,'footnoteLiteralProofs':notes.literal_proofs,'sourceLiteralProofs':source_literal_proofs,'sourceHyperlinks':source_hyperlinks},ensure_ascii=False),encoding='utf-8')
    public_units=[]
    for i,u in enumerate(units,1):
        label=f"{lc['hadithLabel']} {digits(i,lang)}" if u['collection']=='hadith' and u.get('titleIsReference') else u['title']
        native_text(label,lang)
        public_units.append({'id':u['id'],'title':label,'sourceHashes':u['sourceHashes'],'readerTextSHA256':u['readerTextSHA256']})
    result={'language':lang,'languageLabel':lc['nativeName'],'collection':collection,'collectionLabel':title,'file':target.name,'sha256':digest(target.read_bytes()),'units':public_units,'sourceCommit':commit,'bodyColor':'#000000','rtl':lang in RTL,'arabicAyahs':'centered','quranReferences':'directly after quoted ayah','referencePresentation':'original Hadith collection and number in footnotes; no retrieval-site labels','footnoteCount':len(notes.texts),'hadithCount':hadith_count,'audioPanels':audio_panels,'pageLayout':expected_page_layout()}
    if edition_report:
        result['collectionLabel']=scoped_label
        result['editionScope']={'policy':edition_report['policy'],'includedMaterialTitles':scope_titles,'includedMaterialIds':[u['id'] for u in units]}
    if collection=='tadabbur-extended' and any(u.get('referenceReadiness')is not None for u in units):
        checks=[]
        for u in units:
            check=u.get('referenceReadiness')
            if check is None and u.get('provenance',{}).get('adapter') in {'reviewed-ikhlas-v1','arabic-current-ikhlas-v1'}:
                # These existing adapters validate their complete source-bound
                # quotation maps/original-book identities, not arbitrary rows.
                check={'unboundQuranSegments':0,'unboundHadithSegments':0,'unboundScholarSegments':0,'unresolvedSourceReferenceCount':0}
            checks.append(check)
        result['referenceReadiness']={'units':len(units),'auditedUnits':sum(isinstance(c,dict) for c in checks)}
        for field in ['unboundQuranSegments','unboundHadithSegments','unboundScholarSegments','unresolvedSourceReferenceCount']:
            result['referenceReadiness'][field]=sum(c.get(field,0) for c in checks if isinstance(c,dict))
    if collection=='seerah':
        checks=[u.get('referenceReadiness') for u in units]
        result['referenceReadiness']={'units':len(units),'auditedUnits':sum(isinstance(x,dict) for x in checks),'unboundQuranSegments':sum(x.get('unboundQuranSegments',0) for x in checks if isinstance(x,dict)),'unboundHadithSegments':sum(x.get('unboundHadithSegments',0) for x in checks if isinstance(x,dict))}
        if result['referenceReadiness']['auditedUnits']!=len(units) or result['referenceReadiness']['unboundQuranSegments'] or result['referenceReadiness']['unboundHadithSegments']:
            result['quranReferences']='source references incomplete';result['referencePresentation']='source references incomplete; review candidate only'
    if collection in {'hadith','tadabbur-extended'} and any(u.get('sourceReferencePreservation') is not None for u in units):
        checks=[u.get('sourceReferencePreservation') for u in units]
        if any(c is not None and (not isinstance(c,dict) or c.get('schema')!='iman-source-reference-preservation-v1' or c.get('auditMode')!='literal-source-and-qualification-fidelity') for c in checks):raise ValueError('Unsupported source-reference preservation evidence')
        preservation={'schema':'iman-source-reference-preservation-v1','auditMode':'literal-source-and-qualification-fidelity',
          'units':len(units),'auditedUnits':sum(isinstance(c,dict) for c in checks),
          'approvedPublisherUnits':sum(c is None and bool(u.get('publicationApproval')) for u,c in zip(units,checks))}
        for field in ('sourceReferences','preservedReferences','sourceQualifications','preservedQualifications',
                      'sourceParagraphs','preservedParagraphs','lostReferences','lostQualifications','lostParagraphs'):
            preservation[field]=sum(c.get(field,0) for c in checks if isinstance(c,dict))
        result['sourceReferencePreservation']=preservation
        diagnostics={'auditMode':'parser-placement-only-not-source-validity'}
        for field in ('quranGroupsWithoutImmediateTypedReference','quotationGroupsWithoutImmediateReference','literalReferencesWithoutTypedClassification'):
            diagnostics[field]=sum(u.get('sourceReferenceDiagnostics',{}).get(field,0) for u in units)
        result['sourceReferenceDiagnostics']=diagnostics
        result['quranReferences']='supplied reference positions preserved; recognized explicit labels formatted canonically'
        result['referencePresentation']='supplied original source references and qualifications preserved; structured identities only when unambiguous'
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--commit',required=True);args=ap.parse_args()
    root=args.root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    conf=load(root/'books/config.json');manifest=load(root/'books/manifest.json')
    quranfile=inside(root,conf['quranText']['path'])
    if digest(quranfile.read_bytes())!=conf['quranText']['sha256']:raise ValueError('Canonical Arabic text hash mismatch')
    quran=load(quranfile)
    if manifest['sourceCommit']!=args.commit:raise ValueError('Manifest not bound to checked-out source commit')
    if not manifest.get('previewOnly'):
        if digest((root/'materials/catalog.json').read_bytes())!=manifest.get('catalogSHA256') or digest((root/'books/reviewed-books.json').read_bytes())!=manifest.get('reviewedBooksSHA256'):raise ValueError('Reviewed source scope changed after indexing')
        if manifest.get('editionReconciliation'):
            from book_edition_scope import select
            scope=manifest['scope'];declarations=load(root/'books/reviewed-books.json')['books']
            declaration=next(d for d in declarations if (d['language'],d['collection'])==(scope['language'],scope['collection']))
            _,report=select(root,load(root/'materials/catalog.json'),declaration)
            if report!=manifest['editionReconciliation']:raise ValueError('Reviewed edition evidence changed after indexing')
    groups={};identities=set()
    for record in manifest['units']:
        identity=(record['language'],record['collection'],record['id'])
        if identity in identities:raise ValueError('Duplicate book unit')
        identities.add(identity);source=inside(root,record['path']);raw=source.read_bytes()
        if digest(raw)!=record['sha256']:raise ValueError('Manifest input hash mismatch')
        unit=load(source);check_unit(unit,record,quran,root=root)
        for binding in unit.get('inputBindings',[]):
            if digest(inside(root,binding['path']).read_bytes())!=binding['sha256']:raise ValueError('Book source changed after indexing: '+binding['path'])
        groups.setdefault(identity[:2],[]).append(unit)
    if not groups:raise ValueError('No approved complete units; no empty books will be published')
    result=[]
    for (lang,collection),units in sorted(groups.items()):
        from material_order import validate_group
        validate_group(units)
        units.sort(key=canonical_key);result.append(build_book(root,out,conf,lang,collection,units,args.commit,manifest.get('editionReconciliation')))
    coverage=[{'language':l,'collection':c,'available':(l,c) in groups} for l in conf['languages'] for c in sorted(COLLECTIONS)]
    for book in result:
        book['previewOnly']=bool(manifest.get('previewOnly'))
        if book['collection']=='hadith':book['hadithEdition']='new-extended'
    (out/'index.json').write_text(json.dumps({'sourceCommit':args.commit,'previewOnly':bool(manifest.get('previewOnly')),'builtAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'books':result,'coverage':coverage},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'books':len(result),'sourceCommit':args.commit,'manifestBound':True}))
if __name__=='__main__':main()
