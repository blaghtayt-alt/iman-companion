"""Combine complete, already verified public books without rewriting their text.

Each constituent keeps its own cover, contents and page numbering. This is an
anthology of the public books in one language, not a personal selected edition.
"""
from pathlib import Path
from copy import deepcopy
import posixpath,re,zipfile,hashlib
from lxml import etree
from pypdf import PdfReader,PdfWriter
from reader_xml import body_text

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
C='http://schemas.openxmlformats.org/package/2006/content-types'
NS={'w':W};q=lambda n:'{'+W+'}'+n
def xml(raw):return etree.fromstring(raw)
def serialized(node):return etree.tostring(node,xml_declaration=True,encoding='UTF-8',standalone=True)
def relpath(part):return posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
def resolved(part,target):return posixpath.normpath(posixpath.join(posixpath.dirname(part),target))if not target.startswith('/')else target[1:]
def semantic(node):
    return(node.tag,tuple(sorted((k,v)for k,v in node.attrib.items()if 'rsid'not in k)),(node.text or'').strip(),tuple(semantic(c)for c in node if c.tag!=q('rsid')))
def normal_notes(parts,body):
    if 'word/footnotes.xml'not in parts:return []
    notes={n.get(q('id')):n for n in xml(parts['word/footnotes.xml'])if n.get(q('type'))in(None,'normal')}
    return[''.join(n.itertext())for ref in body.iter(q('footnoteReference'))for n in[notes[ref.get(q('id'))]]]

def merge_docx(inputs,output):
    if len(inputs)<2:raise ValueError('A single public book can use its existing verified file')
    sources=[]
    for file in inputs:
        with zipfile.ZipFile(file)as archive:parts={n:archive.read(n)for n in archive.namelist()}
        document=xml(parts['word/document.xml']);body=document.find(q('body'))
        if any(n.get(q('val'))not in(None,'0')for n in body.findall('.//'+q('numPr')+'/'+q('numId'))):raise ValueError('Unsupported automatic list numbering in a combined book')
        sources.append((parts,document,body))
    parts,document,body=sources[0];parts=dict(parts);rels=xml(parts['word/_rels/document.xml.rels']);types=xml(parts['[Content_Types].xml']);styles=xml(parts['word/styles.xml'])
    expected_text=''.join(body_text(source_body)for _,_,source_body in sources)
    def payloads(source,source_body):
        relationships={n.get('Id'):n for n in xml(source['word/_rels/document.xml.rels'])};result=[]
        for node in source_body.iter():
            if node.tag in{q('headerReference'),q('footerReference')}:continue
            for attribute,value in node.attrib.items():
                if not attribute.startswith('{'+R+'}'):continue
                rel=relationships[value];kind=rel.get('Type').rsplit('/',1)[-1]
                if kind=='hyperlink'and rel.get('TargetMode')=='External':result.append(('link',rel.get('Target')))
                elif kind=='image':result.append(('image',hashlib.sha256(source[resolved('word/document.xml',rel.get('Target'))]).hexdigest()))
                else:raise ValueError('Unsupported inline payload in public book: '+kind)
        return result
    expected_payloads=[item for source,_,source_body in sources for item in payloads(source,source_body)]
    expected_notes=[note for source,_,source_body in sources for note in normal_notes(source,source_body)]
    footnotes=xml(parts['word/footnotes.xml'])if'word/footnotes.xml'in parts else etree.Element(q('footnotes'),nsmap={'w':W})
    for source,_,_ in sources:
        for note in xml(source['word/footnotes.xml'])if'word/footnotes.xml'in source else[]:
            kind=note.get(q('type'))
            if kind in {'separator','continuationSeparator','continuationNotice'}and not any(n.get(q('type'))==kind for n in footnotes):
                copied=deepcopy(note);used={n.get(q('id'))for n in footnotes}
                if copied.get(q('id'))in used:copied.set(q('id'),str(min([int(n)for n in used]+[0])-1))
                footnotes.insert(0,copied)
    next_note=max([int(n.get(q('id')))for n in footnotes]+[0])+1
    next_bookmark=max([int(n.get(q('id')))for n in body.iter(q('bookmarkStart'))]+[0])+1
    def content_type(name,kind):
        path='/'+name
        if not any(n.get('PartName')==path for n in types):etree.SubElement(types,'{'+C+'}Override',PartName=path,ContentType=kind)
    def relationship(kind,target,external=False):
        for item in rels:
            if item.get('Type')==kind and item.get('Target')==target and(item.get('TargetMode')=='External')==external:return item.get('Id')
        existing={n.get('Id')for n in rels};i=1
        while'mergedRel'+str(i)in existing:i+=1
        rid='mergedRel'+str(i);attrs={'Id':rid,'Type':kind,'Target':target}
        if external:attrs['TargetMode']='External'
        etree.SubElement(rels,'{'+P+'}Relationship',**attrs);return rid
    relationship(R+'/footnotes','footnotes.xml');content_type('word/footnotes.xml','application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml')
    blank={}
    for kind,tag in [('header','hdr'),('footer','ftr')]:
        name='word/merged-cover-'+kind+'.xml';node=etree.Element(q(tag),nsmap={'w':W});etree.SubElement(node,q('p'));parts[name]=serialized(node)
        content_type(name,'application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind+'+xml');blank[kind]=relationship(R+'/'+kind,posixpath.basename(name))
    def set_part_sections(source_body):
        sections=list(source_body.iter(q('sectPr')))
        if not sections:raise ValueError('Book has no section geometry')
        start=sections[0].find(q('pgNumType'))
        if start is None:start=etree.SubElement(sections[0],q('pgNumType'))
        start.set(q('start'),'1')
        for kind,rid in blank.items():
            for old in sections[0].findall(q(kind+'Reference')):sections[0].remove(old)
            etree.SubElement(sections[0],q(kind+'Reference'),{q('type'):'default','{'+R+'}id':rid})
        for section in sections:
            note=section.find(q('footnotePr'))
            if note is None:note=etree.SubElement(section,q('footnotePr'))
            restart=note.find(q('numRestart'))
            if restart is None:restart=etree.SubElement(note,q('numRestart'))
            restart.set(q('val'),'eachSect')
            start=note.find(q('numStart'))
            if start is None:start=etree.Element(q('numStart'));note.insert(list(note).index(restart),start)
            start.set(q('val'),'1')
            order=['headerReference','footerReference','footnotePr','endnotePr','type','pgSz','pgMar','paperSrc','pgBorders','lnNumType','pgNumType','cols','formProt','vAlign','noEndnote','titlePg','textDirection','bidi','rtlGutter','docGrid','printerSettings','sectPrChange']
            section[:]=sorted(list(section),key=lambda n:order.index(etree.QName(n).localname)if etree.QName(n).localname in order else len(order))
    set_part_sections(body)
    def scope_toc(source_body,prefix):
        nonlocal next_bookmark
        paragraphs=list(source_body.iter(q('p')))
        if not paragraphs:raise ValueError('Empty public book')
        ident=str(next_bookmark);next_bookmark+=1;scope=prefix+'BookScope'
        start=etree.Element(q('bookmarkStart'),{q('id'):ident,q('name'):scope});end=etree.Element(q('bookmarkEnd'),{q('id'):ident})
        paragraphs[0].insert(1 if paragraphs[0].find(q('pPr'))is not None else 0,start);paragraphs[-1].append(end)
        for instruction in source_body.iter(q('instrText')):
            if re.match(r'^\s*TOC\b',instruction.text or''):
                if re.search(r'\\b\s',instruction.text):raise ValueError('Unexpected existing contents range')
                instruction.text=(instruction.text or'')+' \\b '+scope+' '
    scope_toc(body,'m1_')
    for index,(source,_,source_body)in enumerate(sources[1:],2):
        source_body=deepcopy(source_body);source_styles=xml(source['word/styles.xml']);existing={n.get(q('styleId')):n for n in styles}
        for style in source_styles:
            ident=style.get(q('styleId'))
            if ident is None:continue
            if ident in existing:
                if semantic(existing[ident])!=semantic(style):raise ValueError('Constituent books use incompatible paragraph styles: '+ident)
            else:styles.append(deepcopy(style))
        common={'word/styles.xml':'word/styles.xml','word/fontTable.xml':'word/fontTable.xml','word/settings.xml':'word/settings.xml','word/footnotes.xml':'word/footnotes.xml','word/numbering.xml':'word/numbering.xml'}
        common.update({n:n for n in source if n.startswith('word/theme/')and n in parts});mapped=dict(common)
        overrides={n.get('PartName','').lstrip('/'):n.get('ContentType')for n in xml(source['[Content_Types].xml'])if n.tag=='{'+C+'}Override'}
        def copy_part(name):
            if name in mapped:return mapped[name]
            if name not in source:raise ValueError('Unresolved Word package dependency')
            target=posixpath.join(posixpath.dirname(name),'m'+str(index)+'-'+posixpath.basename(name));mapped[name]=target;parts[target]=source[name]
            if name in overrides:content_type(target,overrides[name])
            relationships=relpath(name)
            if relationships in source:
                copied=xml(source[relationships])
                for rel in copied:
                    if rel.get('TargetMode')=='External':continue
                    destination=copy_part(resolved(name,rel.get('Target')));rel.set('Target',posixpath.relpath(destination,posixpath.dirname(target)))
                parts[relpath(target)]=serialized(copied)
            return target
        source_rels=xml(source['word/_rels/document.xml.rels']);rid_map={}
        for rel in source_rels:
            if rel.get('TargetMode')=='External':rid_map[rel.get('Id')]=relationship(rel.get('Type'),rel.get('Target'),True)
            else:
                original=resolved('word/document.xml',rel.get('Target'));target=copy_part(original)
                rid_map[rel.get('Id')]=relationship(rel.get('Type'),posixpath.relpath(target,'word'))
        for node in source_body.iter():
            for key,value in list(node.attrib.items()):
                if key.startswith('{'+R+'}'):
                    if value not in rid_map:raise ValueError('Unresolved document relationship')
                    node.set(key,rid_map[value])
        names={};ids={}
        for start in source_body.iter(q('bookmarkStart')):
            old=start.get(q('name'));name='m'+str(index)+'_'+hashlib.sha256(old.encode()).hexdigest()[:24];names[old]=name
            oldid=start.get(q('id'));ids[oldid]=str(next_bookmark);next_bookmark+=1;start.set(q('id'),ids[oldid]);start.set(q('name'),name)
        for end in source_body.iter(q('bookmarkEnd')):end.set(q('id'),ids[end.get(q('id'))])
        for link in source_body.iter(q('hyperlink')):
            if link.get(q('anchor'))in names:link.set(q('anchor'),names[link.get(q('anchor'))])
        for instruction in source_body.iter(q('instrText')):
            for old,new in names.items():instruction.text=re.sub(r'(?<![\w])'+re.escape(old)+r'(?![\w])',new,instruction.text or'')
        source_notes=xml(source['word/footnotes.xml'])if'word/footnotes.xml'in source else[];normal={n.get(q('id')):n for n in source_notes if n.get(q('type'))in(None,'normal')};note_ids={}
        for ref in source_body.iter(q('footnoteReference')):
            old=ref.get(q('id'))
            if old not in note_ids:
                if old not in normal:raise ValueError('Missing source footnote')
                note_ids[old]=str(next_note);next_note+=1;note=deepcopy(normal[old]);note.set(q('id'),note_ids[old]);footnotes.append(note)
            ref.set(q('id'),note_ids[old])
        set_part_sections(source_body);scope_toc(source_body,'m'+str(index)+'_')
        final=body.find(q('sectPr'))
        if final is None:raise ValueError('Missing final section')
        previous=body[-2]
        if previous.tag!=q('p'):raise ValueError('Public book does not end in a paragraph')
        properties=previous.find(q('pPr'))
        if properties is None:properties=etree.Element(q('pPr'));previous.insert(0,properties)
        if properties.find(q('sectPr'))is not None:raise ValueError('Unexpected trailing section break')
        body.remove(final);properties.append(final)
        for element in source_body:body.append(deepcopy(element))
    for tag in ['{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr','{http://schemas.openxmlformats.org/drawingml/2006/picture}cNvPr']:
        for i,node in enumerate(body.iter(tag),1):node.set('id',str(i))
    if body_text(body)!=expected_text:raise ValueError('Combined Word reader text changed')
    parts['word/document.xml']=serialized(document);parts['word/styles.xml']=serialized(styles);parts['word/footnotes.xml']=serialized(footnotes);parts['word/_rels/document.xml.rels']=serialized(rels);parts['[Content_Types].xml']=serialized(types)
    if normal_notes(parts,body)!=expected_notes:raise ValueError('Combined Word footnotes changed or were reordered')
    if payloads(parts,body)!=expected_payloads:raise ValueError('Combined Word changed a cover, QR image or clickable audio link')
    settings=xml(parts['word/settings.xml']);update=settings.find(q('updateFields'))
    if update is None:update=etree.SubElement(settings,q('updateFields'))
    update.set(q('val'),'false');parts['word/settings.xml']=serialized(settings)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED)as archive:
        for name,raw in parts.items():archive.writestr(name,raw)
    return {'parts':len(inputs),'sourceBodyExactlyPreserved':True,'sourceFootnotesExactlyPreserved':len(expected_notes),'imagesAndAudioLinksVerified':len(expected_payloads),'independentBookPagination':True}

def page_annotations(reader,page,offset=0):
    """Comparable links, with resolved physical pages rather than object IDs."""
    def destination(value):
        if isinstance(value,str):
            named=reader.named_destinations.get(value)
            if named is None:raise ValueError('Unresolved named PDF destination')
            return [reader.get_destination_page_number(named)+offset,str(named.typ),*list(named.dest_array)[2:]]
        if not isinstance(value,list)or not value:raise ValueError('Unsupported PDF destination')
        target=value[0].get_object();number=reader.get_page_number(target)
        if number is None:raise ValueError('Unresolved PDF page destination')
        return [number+offset,*list(value)[1:]]
    result=[]
    for indirect in page.get('/Annots',[]):
        annotation=indirect.get_object();item={'type':str(annotation.get('/Subtype')),'rect':list(annotation.get('/Rect',[]))}
        if '/Dest'in annotation:item['destination']=destination(annotation['/Dest'])
        if '/A'in annotation:
            action=annotation['/A'];kind=str(action.get('/S'));item['action']=kind
            if kind=='/GoTo':item['destination']=destination(action['/D'])
            elif kind=='/URI':item['uri']=str(action['/URI'])
            else:raise ValueError('Unsupported PDF action in public book')
        result.append(item)
    return result

def merge_pdf(inputs,output,titles):
    if len(inputs)!=len(titles)or len(inputs)<2:raise ValueError('A merged edition needs at least two titled books')
    writer=PdfWriter();original=[];offsets=[];count=0
    annotations=[]
    for file,title in zip(inputs,titles):
        reader=PdfReader(file);offsets.append(count);original.extend(p.get_contents().get_data()for p in reader.pages)
        annotations.extend(page_annotations(reader,page,count)for page in reader.pages);count+=len(reader.pages)
        writer.append(reader,outline_item=title,import_outline=True)
    with Path(output).open('wb')as target:writer.write(target)
    merged=PdfReader(output)
    if len(merged.pages)!=count or any(page.get_contents().get_data()!=expected for page,expected in zip(merged.pages,original)):raise ValueError('Combined PDF changed a published page')
    if [page_annotations(merged,page)for page in merged.pages]!=annotations:raise ValueError('Combined PDF changed a contents, footnote or audio link')
    return {'parts':len(inputs),'pages':count,'sourcePageContentStreamsPreserved':True,'annotationsVerified':sum(map(len,annotations)),'partOffsets':offsets}
