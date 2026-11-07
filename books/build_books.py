"""Render approved, normalized reader units into one editable Word book per language/category.

No translation or editorial rewriting occurs here. Integration supplies the reader units
and source/review bindings; unsupported or incomplete input fails before publication.
"""
from pathlib import Path
import argparse,hashlib,json,re,sys,zipfile,uuid,datetime
from copy import deepcopy
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_LINE_SPACING
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree
from locale_copy import locale
from reader_xml import body_text
from material_audio import load_registry,add_audio_panel
from bibliography import native_text,digits,hadith_citation,quran_reference,edition_credit,expand_verse_key
from book_typography import SYMBOLS,SYMBOL_LTR,SYMBOL_RTL,quotation_mirrors,block_mirrors,span_mirrors

SCHEMA='iman-book-unit-v1'
ROLES={'body':'000000','meaning':'000000','example':'000000','note':'000000','current-ayah':'7C3AED','quran':'7C3AED','related':'2563EB','hadith':'2563EB','scholar':'A95300','heading':'064534'}
RTL={'ar','ur','fa'}
KINDS={'paragraph','heading','ayah','translation','quotation','note','credit','list-item'}
COLLECTIONS={'tadabbur-extended','articles','seerah','hadith'}
ARABIC_RUN=r'[\u0600-\u06ff\u0750-\u077f\u0870-\u08ff\ufb50-\ufdff\ufe70-\ufeff]'

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
def check_unit(unit,record,quran=None):
    if unit.get('schema')!=SCHEMA:raise ValueError('Unsupported book input schema')
    for key in ['language','collection','id']:
        if unit[key]!=record[key]:raise ValueError('Manifest identity mismatch: '+key)
    if unit['collection'] not in COLLECTIONS:raise ValueError('Unknown collection')
    if unit['collection']=='hadith' and (type(unit.get('order')) is not int or unit['order']<=0):raise ValueError('Hadith unit needs its canonical positive source order')
    if unit['collection']=='hadith' and (unit.get('hadithEdition')!='new-extended' or any(b.get('collection')!='essential-hadith' for b in unit.get('catalogBindings',[]))):raise ValueError('Only the new extended Essential Iman Hadith lessons belong in this book; reject the legacy short collection')
    if unit.get('complete') is not True or unit.get('reviewGate')!='published-current':raise ValueError('Unit not cleared for current publication')
    if not unit.get('sourceHashes') or not all(re.fullmatch('[a-f0-9]{64}',x) for x in unit['sourceHashes']):raise ValueError('Missing source binding')
    if not unit.get('title') or not unit.get('sections'):raise ValueError('Empty reader unit')
    if not unit.get('titleIsReference'):native_text(unit['title'],unit['language'])
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
            if b['kind'] not in KINDS:raise ValueError('Unknown reader block: '+b['kind'])
            if not isinstance(b.get('text'),str):raise ValueError('Non-text reader block')
            if b.get('spans') and ''.join(s['text'] for s in b['spans'])!=b['text']:raise ValueError('Span text differs from reader text')
            if b.get('role','body') not in ROLES or any(s.get('role','body') not in ROLES for s in b.get('spans',[])):raise ValueError('Unknown semantic color role')
            if b.get('sourceCredit'):raise ValueError('Replace legacy website sourceCredit with original-book citations or a localized translationCredit')
            if b['kind'] not in {'ayah','credit'}:native_text(b['text'],unit['language'])
            for span in b.get('spans',[]):
                for note in span.get('noteTexts',[]):native_text(note,unit['language'])
            if b.get('translationCredit'):edition_credit(b['translationCredit'],unit['language'])
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
    pieces=[];offset=0
    mirrors=quotation_mirrors(text,lang)if ornament_mirrors is None else ornament_mirrors
    for segment in re.split('('+number+')',text):
        if re.fullmatch(number,segment):pieces.append((segment,True,offset));offset+=len(segment)
        else:
            for token in re.split('(['+SYMBOLS+'])',segment):
                if token in SYMBOLS and token:pieces.append((token,False,offset));offset+=len(token)
                else:
                    for piece in re.split('('+ARABIC_RUN+'+(?:\\s+'+ARABIC_RUN+'+)*)',token):pieces.append((piece,False,offset));offset+=len(piece)
    for piece,is_number,position in pieces:
        if not piece:continue
        is_ar=bool(re.search(ARABIC_RUN,piece));font=family if lang in RTL else (arabic if is_ar else family)
        if piece in SYMBOLS and piece:font=SYMBOL_LTR if piece!='\ufdfa'and mirrors.get(position,lang not in RTL)else SYMBOL_RTL
        if lang in RTL and re.search('[A-Za-z]',piece) and not is_ar:font='Iman Book Inter'
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

def reference_text(text):
    text=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)
    text=re.sub(r'https?://\S+|\bwww\.\S+','',text)
    text=re.sub(r'\s*[·|]\s*(?=[·|]|$)',' ',text)
    text=re.sub(r'[ \t]+',' ',text).strip(' ·|\n')
    if not text:raise ValueError('Reference needs a readable source name after removal of web links')
    return text

class Footnotes:
    def __init__(self,doc,lang,family,arabic):
        self.doc=doc;self.lang=lang;self.family=family;self.arabic=arabic;self.texts=[];self.anchors={};self.root=OxmlElement('w:footnotes')
        for number,kind in [(-1,'separator'),(0,'continuationSeparator')]:
            note=el(self.root,'w:footnote',{'w:id':number,'w:type':kind});el(el(note,'w:p'),'w:r');el(note[0][0],'w:'+kind)
    def add(self,anchor,text,group=None):
        text=reference_text(text)
        key=(anchor._p,group)
        if key in self.anchors:
            index,note=self.anchors[key];paragraph=Paragraph(note[-1],self.doc._body);separator='؛ ' if self.lang in RTL else '; ';add_text(paragraph,separator+text,self.lang,self.family,self.arabic,9,'note');self.texts[index]+=separator+text;return
        number=len(self.texts)+1;self.texts.append(text)
        r=anchor.add_run();r.font.size=Pt(9);rp=r._r.get_or_add_rPr();el(rp,'w:vertAlign',{'w:val':'superscript'});el(rp,'w:rtl',{'w:val':0});el(rp,'w:rFonts',{'w:ascii':'Iman Book Inter','w:hAnsi':'Iman Book Inter','w:cs':'Iman Book Inter'});el(r._r,'w:footnoteReference',{'w:id':number})
        note=el(self.root,'w:footnote',{'w:id':number});p=self.paragraph(note)
        run=p.add_run();run.font.name='Iman Book Inter';run.font.size=Pt(9);el(run._r.get_or_add_rPr(),'w:vertAlign',{'w:val':'superscript'});el(run._r,'w:footnoteRef')
        add_text(p,' '+text,self.lang,self.family,self.arabic,9,'note')
        self.anchors[key]=(number-1,note)
    def paragraph(self,note):
        node=el(note,'w:p');p=Paragraph(node,self.doc._body);direction(p,self.lang)
        p.paragraph_format.line_spacing_rule=WD_LINE_SPACING.AT_LEAST;p.paragraph_format.line_spacing=Pt(18 if self.lang=='ur' else 12);p.paragraph_format.space_after=Pt(3)
        return p

def canonical_key(unit):
    nums=[int(x) for x in re.findall(r'\d+',unit['id'])]
    if unit['collection']=='tadabbur-extended':
        n=unit.get('surah',nums[0] if nums else None)
        if not isinstance(n,int) or not 1<=n<=114:raise ValueError('Quran unit needs a valid surah number')
        return (n,nums[1] if len(nums)>1 else 0)
    if unit['collection'] in {'seerah','articles'}:
        n=unit.get('chapter',unit.get('number',unit.get('order',0)))
        if not isinstance(n,int) or n<=0:raise ValueError('Article/Seerah unit needs its actual source number')
        return (int(n),unit['id'])
    return (int(unit.get('order',0)),int(unit.get('chapter',0)),int(unit.get('lesson',unit.get('number',nums[-1] if nums else 0))),unit['id'])

def cover_page(doc,cover,width,height):
    """Place the untouched cover at the page edges using its original 2:3 ratio."""
    sec=doc.sections[0];sec.page_width=width;sec.page_height=height
    sec.top_margin=sec.bottom_margin=sec.left_margin=sec.right_margin=0
    sec.header_distance=sec.footer_distance=0
    p=doc.add_paragraph();p.paragraph_format.space_before=p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(1)
    # LibreOffice can round a custom 9-inch page up by about 1.2 pt. Keep the
    # source image's 2:3 ratio and add a small centered bleed so it still covers
    # the entire rendered page without stretching the artwork.
    inline=p.add_run().add_picture(str(cover),width=width+Pt(4/3),height=height+Pt(2))._inline
    anchor=OxmlElement('wp:anchor')
    for k,v in {'distT':0,'distB':0,'distL':0,'distR':0,'simplePos':0,'relativeHeight':0,'behindDoc':1,'locked':0,'layoutInCell':1,'allowOverlap':1}.items():anchor.set(k,str(v))
    el(anchor,'wp:simplePos',{'x':0,'y':0})
    for axis in ['H','V']:
        pos=el(anchor,'wp:position'+axis,{'relativeFrom':'page'});el(pos,'wp:posOffset').text=str(-Pt(2/3) if axis=='H' else 0)
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
    credits=[]
    for unit in units:
        entries=list(unit.get('translationCredits',[]))
        entries.extend(b['translationCredit'] for section in unit['sections'] for b in section['blocks'] if b.get('translationCredit'))
        for item in entries:
            text=edition_credit(item,lang)
            if text not in credits:credits.append(text)
    title=lc['titles'][collection];size=13 if lang=='ur' else (12 if lang in RTL|{'bn','hi','th'} else 11);line=28 if lang=='ur' else (22 if lang in RTL else 18)
    cover=inside(root,lc['covers'][collection]);expected=lc['coverHashes'][collection]
    if digest(cover.read_bytes())!=expected:raise ValueError('Cover hash mismatch')
    doc=Document();sec=cover_page(doc,cover,Inches(6),Inches(9))
    sec.page_width=Inches(6);sec.page_height=Inches(9)
    sec.top_margin=sec.bottom_margin=Inches(.62);sec.left_margin=sec.right_margin=Inches(.58);sec.header_distance=sec.footer_distance=Inches(.28)
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
    scope_summary=(scope_titles[0]+(f' (+{len(scope_titles)-1})' if len(scope_titles)>1 else '')) if scope_titles else ''
    scoped_label=title+(' · '+scope_summary if scope_summary else '')
    p=sec.header.paragraphs[0];direction(p,lang);add_text(p,lc['brand']+' · '+scoped_label,lang,family,arabic,8,'heading')
    p=sec.footer.paragraphs[0];direction(p,'en',True)
    if lang in RTL:
        from native_pagination import append_native_number
        append_native_number(p,'PAGE',lang,family)
    else:
        r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'begin'});el(r._r,'w:instrText').text=' PAGE ';el(r._r,'w:fldChar',{'w:fldCharType':'end'})
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
    p=doc.add_paragraph();direction(p,lang);r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'begin'});r=p.add_run();el(r._r,'w:instrText').text=' TOC \\o "1-2" \\h \\z \\u ';r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'separate'});r=p.add_run(' ');r=p.add_run();el(r._r,'w:fldChar',{'w:fldCharType':'end'})
    preserved=[];notes=Footnotes(doc,lang,family,arabic);hadith_count=0;last_chapter=None
    for unit_index,unit in enumerate(units):
        unit_mirrors=block_mirrors(unit,lang)
        aggregate_hadith=unit['collection']=='hadith' and any(s.get('hadith') is True for s in unit['sections'])
        display_title=unit['title']
        if unit['collection']=='hadith' and not aggregate_hadith:
            hadith_count+=1;display_title=f"{lc['hadithLabel']} {digits(hadith_count,lang)}"
        new_page=unit_index==0 or unit['collection']!='hadith' or (unit.get('chapter') is not None and unit.get('chapter')!=last_chapter)
        chapter_title=unit.get('chapterTitle') if unit['collection']=='hadith' else None
        audio_heading_paragraphs=[]
        if chapter_title and (unit_index==0 or unit.get('chapter')!=last_chapter):
            native_text(chapter_title,lang);p=doc.add_paragraph(style='Heading 1');p.paragraph_format.page_break_before=True;direction(p,lang);add_text(p,chapter_title,lang,family,arabic,20,'heading',True);audio_heading_paragraphs.append(p);new_page=False
        p=doc.add_paragraph(style='Heading 2' if chapter_title else 'Heading 1');p.paragraph_format.page_break_before=new_page;direction(p,lang);add_text(p,display_title,lang,family,arabic,18 if unit['collection']=='hadith' else 22,'heading',True)
        audio_heading_paragraphs.append(p)
        if unit['collection']=='hadith' and not aggregate_hadith and not unit.get('titleIsReference') and unit['title']!=lc['hadithLabel']:
            p=doc.add_paragraph(style='Heading 3' if chapter_title else 'Heading 2');direction(p,lang);add_text(p,unit['title'],lang,family,arabic,15,'heading',True)
            audio_heading_paragraphs.append(p)
        panel=add_audio_panel(doc,unit,audio_registry,family,arabic,add_text,direction,heading_paragraphs=audio_heading_paragraphs,fonts=fonts,cache_root=root/'books/.cache/audio-cards')
        if panel:audio_panels.append(panel)
        last_chapter=unit.get('chapter')
        last_content=p
        for section in unit['sections']:
            section_title=section.get('heading','')
            if aggregate_hadith and section.get('hadith') is True:
                hadith_count+=1;section_title=f"{lc['hadithLabel']} {digits(hadith_count,lang)}"
            if section_title and section_title.strip()!=unit['title'].strip():
                p=doc.add_paragraph(style='Heading 2');direction(p,lang);add_text(p,section_title,lang,family,arabic,17,'heading',True);last_content=p
                if aggregate_hadith and section.get('hadith') is True and section.get('heading') and not section.get('titleIsReference'):
                    p=doc.add_paragraph(style='Heading 3');direction(p,lang);add_text(p,section['heading'],lang,family,arabic,14,'heading',True);last_content=p
            for b in section['blocks']:
                kind=b['kind']
                if kind=='credit':
                    if not b.get('citations'):raise ValueError('Reference block needs structured original-book citations')
                    for citation in b['citations']:notes.add(last_content,hadith_citation(citation,lang))
                    continue
                if kind=='note':
                    notes.add(last_content,native_text(b['text'],lang));continue
                p=doc.add_paragraph(style='Heading 3' if kind=='heading' else None);direction(p,'ar' if kind=='ayah' else lang,kind=='ayah');last_content=p
                blocksize=21 if kind=='ayah' else (10 if kind in {'note','credit'} else size)
                if kind in {'ayah','translation','heading'}:p.paragraph_format.keep_with_next=True
                spans=b.get('spans') or [{'text':b['text'],'role':b.get('role','current-ayah' if kind in {'ayah','translation'} else ('related' if kind=='quotation' else 'body'))}]
                if collection=='seerah' and kind=='paragraph' and any(s.get('role')=='quran' for s in spans) and all(s.get('role')=='quran' or not s.get('text','').strip() for s in spans):direction(p,'ar',True)
                mirror_maps=span_mirrors(spans,unit_mirrors[id(b)])
                for span_index,span in enumerate(spans):
                    add_text(p,span['text'],'ar' if kind=='ayah' else lang,arabic if kind=='ayah' else family,arabic,blocksize,span.get('role','body'),kind=='heading' or span.get('bold',False),ornament_mirrors=mirror_maps[span_index]);preserved.append(span['text'])
                    if kind not in {'ayah','translation'}:
                        keys=span.get('verseKeys',[])
                        if not keys and span.get('role')=='current-ayah' and section.get('ayahKey'):keys=[section['ayahKey']]
                        if keys:add_text(p,' '+'؛ '.join(quran_reference(key,lang,names) for key in keys),lang,family,arabic,10,'body')
                    for citation in span.get('citations',[]):notes.add(p,hadith_citation(citation,lang),group='span-'+str(span_index))
                    for note_index,note in enumerate(span.get('noteTexts',[])):notes.add(p,note,group='source-note-'+str(span_index)+'-'+str(note_index))
                if kind=='ayah':
                    ref=quran_reference(b['verseKey'],lang,names)
                    if lang not in RTL:ref='\u200e'+ref+'\u200e'
                    add_text(p,' '+ref,lang,family,arabic,10,'body')
                for citation in b.get('citations',[]):notes.add(p,hadith_citation(citation,lang))
    settings=doc.settings.element;el(settings,'w:updateFields',{'w:val':'true'});el(settings,'w:embedTrueTypeFonts',{'w:val':'true'})
    target=out/f'Iman_Companion_{lang}_{collection}.docx';doc.save(target);embed_fonts(target,fonts,notes.root if notes.texts else None)
    rendered=body_text(Document(target).element.body)
    offset=0
    for text in preserved:
        index=rendered.find(text,offset)
        if index<0:raise ValueError('Reader text lost or reordered in Word serialization')
        offset=index+len(text)
    (out/(target.name+'.reader-checks.json')).write_text(json.dumps({'body':preserved,'footnotes':notes.texts},ensure_ascii=False),encoding='utf-8')
    public_units=[]
    for i,u in enumerate(units,1):
        label=f"{lc['hadithLabel']} {digits(i,lang)}" if u['collection']=='hadith' and u.get('titleIsReference') else u['title']
        native_text(label,lang)
        public_units.append({'id':u['id'],'title':label,'sourceHashes':u['sourceHashes'],'readerTextSHA256':u['readerTextSHA256']})
    result={'language':lang,'languageLabel':lc['nativeName'],'collection':collection,'collectionLabel':title,'file':target.name,'sha256':digest(target.read_bytes()),'units':public_units,'sourceCommit':commit,'bodyColor':'#000000','rtl':lang in RTL,'arabicAyahs':'centered','quranReferences':'directly after quoted ayah','referencePresentation':'original Hadith collection and number in footnotes; no retrieval-site labels','footnoteCount':len(notes.texts),'hadithCount':hadith_count,'audioPanels':audio_panels}
    if edition_report:
        result['collectionLabel']=scoped_label
        result['editionScope']={'policy':edition_report['policy'],'includedMaterialTitles':scope_titles,'includedMaterialIds':[u['id'] for u in units]}
    if collection=='seerah':
        checks=[u.get('referenceReadiness') for u in units]
        result['referenceReadiness']={'units':len(units),'auditedUnits':sum(isinstance(x,dict) for x in checks),'unboundQuranSegments':sum(x.get('unboundQuranSegments',0) for x in checks if isinstance(x,dict)),'unboundHadithSegments':sum(x.get('unboundHadithSegments',0) for x in checks if isinstance(x,dict))}
        if result['referenceReadiness']['auditedUnits']!=len(units) or result['referenceReadiness']['unboundQuranSegments'] or result['referenceReadiness']['unboundHadithSegments']:
            result['quranReferences']='source references incomplete';result['referencePresentation']='source references incomplete; review candidate only'
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
        unit=load(source);check_unit(unit,record,quran)
        for binding in unit.get('inputBindings',[]):
            if digest(inside(root,binding['path']).read_bytes())!=binding['sha256']:raise ValueError('Book source changed after indexing: '+binding['path'])
        groups.setdefault(identity[:2],[]).append(unit)
    if not groups:raise ValueError('No approved complete units; no empty books will be published')
    result=[]
    for (lang,collection),units in sorted(groups.items()):
        units.sort(key=canonical_key);result.append(build_book(root,out,conf,lang,collection,units,args.commit,manifest.get('editionReconciliation')))
    coverage=[{'language':l,'collection':c,'available':(l,c) in groups} for l in conf['languages'] for c in sorted(COLLECTIONS)]
    for book in result:
        book['previewOnly']=bool(manifest.get('previewOnly'))
        if book['collection']=='hadith':book['hadithEdition']='new-extended'
    (out/'index.json').write_text(json.dumps({'sourceCommit':args.commit,'previewOnly':bool(manifest.get('previewOnly')),'builtAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'books':result,'coverage':coverage},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'books':len(result),'sourceCommit':args.commit,'manifestBound':True}))
if __name__=='__main__':main()
