"""Combine complete, already verified public books without rewriting their text.

Each constituent keeps its own cover, contents and page numbering. This is an
anthology of the public books in one language, not a personal selected edition.
"""
from pathlib import Path
from copy import deepcopy
import posixpath,re,zipfile,hashlib,uuid
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

FONT_EMBEDS=tuple(q('embed'+style)for style in('Regular','Bold','Italic','BoldItalic'))

def font_index(table):
    result={}
    for font in table.findall(q('font')):
        name=font.get(q('name'))
        if not name or name.casefold()in result:raise ValueError('Missing or duplicate Word font family')
        result[name.casefold()]=font
    return result

def font_embeddings(parts,font,relationships):
    """Compare the actual font bytes, independently of obfuscation keys/IDs."""
    result={}
    for node in font:
        if node.tag not in FONT_EMBEDS:continue
        if node.tag in result:raise ValueError('Duplicate embedded Word font style')
        rel=relationships.get(node.get('{'+R+'}id'))
        if rel is None or rel.get('Type')!=R+'/font' or rel.get('TargetMode')=='External':
            raise ValueError('Invalid embedded Word font relationship')
        target=resolved('word/fontTable.xml',rel.get('Target',''))
        if not target.startswith('word/fonts/')or target not in parts:raise ValueError('Unresolved embedded Word font')
        data=bytearray(parts[target])
        try:key=uuid.UUID(node.get(q('fontKey'),'').strip('{}')).bytes[::-1]
        except ValueError as error:raise ValueError('Invalid embedded Word font key')from error
        if len(data)<32:raise ValueError('Truncated embedded Word font')
        for i in range(32):data[i]^=key[i%16]
        result[node.tag]=(node,target,hashlib.sha256(data).hexdigest())
    return result

def merge_fonts(parts,source,index,copy_part,content_type):
    """Keep new pinned families and faces when appending a translated book.

    Font names are global in a Word package. Two different faces with the same
    family/style cannot be isolated through relationship IDs, so reject those
    conflicts rather than changing either book's appearance.
    """
    name='word/fontTable.xml';rels_name=relpath(name)
    if name not in source:return
    table=xml(parts[name])if name in parts else etree.Element(q('fonts'),nsmap={'w':W})
    incoming=xml(source[name]);existing=font_index(table);font_index(incoming)
    rels=xml(parts[rels_name])if rels_name in parts else etree.Element('{'+P+'}Relationships',nsmap={None:P})
    source_rels=xml(source[rels_name])if rels_name in source else[]
    def identities(nodes):
        result={}
        for rel in nodes:
            ident=rel.get('Id')
            if not ident or ident in result:raise ValueError('Missing or duplicate Word font relationship')
            result[ident]=rel
        return result
    relationships=identities(rels);source_relationships=identities(source_rels)
    known={key:font_embeddings(parts,font,relationships)for key,font in existing.items()}
    types=xml(source['[Content_Types].xml'])
    defaults={n.get('Extension'):n.get('ContentType')for n in types if n.tag=='{'+C+'}Default'}
    overrides={n.get('PartName','').lstrip('/'):n.get('ContentType')for n in types if n.tag=='{'+C+'}Override'}
    for font in incoming.findall(q('font')):
        family=font.get(q('name'));key=family.casefold();embeddings=font_embeddings(source,font,source_relationships)
        if key not in existing:
            copied=deepcopy(font)
            for child in list(copied):
                if child.tag in FONT_EMBEDS:copied.remove(child)
            table.append(copied);existing[key]=copied;known[key]={}
        for style,(node,target,digest)in embeddings.items():
            if style in known[key]:
                if known[key][style][2]!=digest:raise ValueError('Constituent books use incompatible embedded font: '+family+' '+etree.QName(style).localname)
                continue
            destination=copy_part(target)
            kind=overrides.get(target)or defaults.get(posixpath.splitext(target)[1].lstrip('.'))
            if not kind:raise ValueError('Missing embedded Word font content type')
            content_type(destination,kind)
            ident='m'+str(index)+'-font-'+str(len(relationships)+1)
            while ident in relationships:ident+='x'
            rel=etree.SubElement(rels,'{'+P+'}Relationship',Id=ident,Type=R+'/font',Target=posixpath.relpath(destination,'word'))
            relationships[ident]=rel;copied=deepcopy(node);copied.set('{'+R+'}id',ident);existing[key].append(copied)
            known[key][style]=(copied,destination,digest)
        target_font=existing[key]
        target_font[:]=[n for n in target_font if n.tag not in FONT_EMBEDS]+sorted(
            [n for n in target_font if n.tag in FONT_EMBEDS],key=lambda n:FONT_EMBEDS.index(n.tag))
    content_type(name,'application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml')
    parts[name]=serialized(table);parts[rels_name]=serialized(rels)

STYLE_REFERENCES={q(n)for n in('pStyle','rStyle','tblStyle','basedOn','next','link','styleLink','numStyleLink')}

def style_index(styles):
    result={}
    for style in styles.findall(q('style')):
        ident=style.get(q('styleId'))
        if not ident or ident in result:raise ValueError('Missing or duplicate Word style identity')
        result[ident]=style
    return result

def default_styles(styles):
    result={}
    for style in styles.findall(q('style')):
        value=style.get(q('default'))
        if value not in(None,'0','false','off','1','true','on'):
            raise ValueError('Unsupported Word default style flag: '+str(value))
        if value not in('1','true','on'):continue
        kind=style.get(q('type'))
        if kind in result:raise ValueError('Duplicate default Word style')
        result[kind]=style.get(q('styleId'))
    return result

class BookStyles:
    """Isolate differing style trees without changing either book's formatting.

    Word can normalize unused built-in styles differently in two verified files.
    Those differences must not prevent an anthology or silently replace a style
    used by the other book. A dependent style also needs its own identity when
    its base, linked style, or next style is isolated.
    """
    def __init__(self,target,source,index):
        first=target.find(q('docDefaults'));second=source.find(q('docDefaults'))
        if (semantic(first)if first is not None else None)!=(semantic(second)if second is not None else None):
            raise ValueError('Constituent books use incompatible document style defaults')
        existing=style_index(target);incoming=style_index(source)
        target_defaults=default_styles(target);source_defaults=default_styles(source)
        # A source with no default for a kind must not inherit a previous book's
        # default. Explicit incoming defaults can be bound below; an absent one
        # has no style identity that can safely be substituted.
        if set(target_defaults)-set(source_defaults):
            raise ValueError('Constituent books use incompatible implicit style defaults')
        existing_names={n.get(q('val'),'').casefold():ident for ident,style in existing.items()for n in style.findall(q('name'))}
        separate={ident for ident,style in incoming.items()if ident in existing and semantic(existing[ident])!=semantic(style)}
        separate.update(ident for ident,style in incoming.items()for n in style.findall(q('name'))
                        if n.get(q('val'),'').casefold()in existing_names and existing_names[n.get(q('val'),'').casefold()]!=ident)
        while True:
            changed={ident for ident,style in incoming.items()if ident in existing
                     and any(n.tag in STYLE_REFERENCES and n.get(q('val'))in separate for n in style.iter())}
            if changed<=separate:break
            separate.update(changed)
        used=set(existing)|set(incoming);self.ids={};self.names={}
        for ident in sorted(separate):
            base='m'+str(index)+'_'+hashlib.sha256(ident.encode()).hexdigest()[:24];new=base;suffix=1
            while new in used:new=base+'_'+str(suffix);suffix+=1
            self.ids[ident]=new;used.add(new)
        self.defaults={kind:self.ids.get(ident,ident)for kind,ident in source_defaults.items()
                       if self.ids.get(ident,ident)!=target_defaults.get(kind)}
        for ident,style in incoming.items():
            if ident in existing and ident not in self.ids:continue
            copied=deepcopy(style)
            if ident in self.ids:
                copied.set(q('styleId'),self.ids[ident])
                name=copied.find(q('name'))
                old=name.get(q('val'))if name is not None else ident
                new=old+' (Book '+str(index)+' '+hashlib.sha256(ident.encode()).hexdigest()[:8]+')'
                if name is None:name=etree.Element(q('name'));copied.insert(0,name)
                name.set(q('val'),new)
                self.names[old.casefold()]=new;self.names[ident.casefold()]=new
                aliases=copied.find(q('aliases'))
                if aliases is not None:
                    renamed=[]
                    for alias in aliases.get(q('val'),'').split(','):
                        alias=alias.strip()
                        if not alias:continue
                        renamed.append(alias+' (Book '+str(index)+' '+hashlib.sha256(ident.encode()).hexdigest()[:8]+')')
                        self.names[alias.casefold()]=renamed[-1]
                    aliases.set(q('val'),','.join(renamed))
            # Only the first book supplies package-wide defaults. Unstyled
            # content in a later book is bound to its own default explicitly.
            copied.attrib.pop(q('default'),None)
            self.references(copied);target.append(copied)

    def references(self,root):
        for node in root.iter():
            if node.tag in STYLE_REFERENCES and node.get(q('val'))in self.ids:
                node.set(q('val'),self.ids[node.get(q('val'))])

    def instruction(self,text):
        # STYLEREF and TOC's style list refer to names, rather than style IDs.
        # Leave other field operands (bookmarks, URLs, etc.) completely alone.
        def replace_name(value):return self.names.get(value.casefold(),value)
        if re.match(r'^\s*STYLEREF\b',text,re.I):
            def replace(match):
                old=match.group(2)if match.group(2)is not None else match.group(3)
                new=replace_name(old)
                return match.group(1)+('"'+new+'"'if new!=old or match.group(2)is not None else old)
            return re.sub(r'(^\s*STYLEREF\s+)(?:"([^"]+)"|([^\s\\]+))',replace,text,count=1,flags=re.I)
        if re.match(r'^\s*TOC\b',text,re.I):
            def replace(match):
                fields=match.group(2).split(',')
                for index in range(0,len(fields),2):
                    old=fields[index];value=old.strip();new=replace_name(value)
                    if value!=new:fields[index]=old[:len(old)-len(old.lstrip())]+new+old[len(old.rstrip()):]
                return match.group(1)+'"'+','.join(fields)+'"'
            return re.sub(r'(\\t\s+)"([^"]*)"',replace,text,flags=re.I)
        return text

    def rewrite(self,root):
        self.references(root)
        for kind,element,properties,reference in [('paragraph','p','pPr','pStyle'),('character','r','rPr','rStyle'),('table','tbl','tblPr','tblStyle')]:
            if kind not in self.defaults:continue
            for node in root.iter(q(element)):
                prop=node.find(q(properties))
                if prop is None:prop=etree.Element(q(properties));node.insert(0,prop)
                if prop.find(q(reference))is None:prop.insert(0,etree.Element(q(reference),{q('val'):self.defaults[kind]}))
        if not self.names:return
        stack=[]
        def rewrite_field(nodes):
            text=''.join(n.text or''for n in nodes);changed=self.instruction(text)
            if nodes and changed!=text:
                nodes[0].text=changed
                for node in nodes[1:]:node.text=''
        for node in root.iter():
            if node.tag==q('fldSimple'):
                value=node.get(q('instr'))
                if value is not None:node.set(q('instr'),self.instruction(value))
            elif node.tag==q('fldChar'):
                kind=node.get(q('fldCharType'))
                if kind=='begin':stack.append([])
                elif kind in('separate','end')and stack:
                    if stack[-1]is not None:rewrite_field(stack[-1]);stack[-1]=None
                    if kind=='end':stack.pop()
            elif node.tag==q('instrText'):
                if stack and stack[-1]is not None:stack[-1].append(node)
                elif not stack:rewrite_field([node])

def merge_docx(inputs,output):
    if len(inputs)<2:raise ValueError('A single public book can use its existing verified file')
    sources=[]
    for file in inputs:
        with zipfile.ZipFile(file)as archive:parts={n:archive.read(n)for n in archive.namelist()}
        document=xml(parts['word/document.xml']);body=document.find(q('body'))
        source_styles=xml(parts['word/styles.xml']);by_style=style_index(source_styles)
        active=set(default_styles(source_styles).values())
        for name,raw in parts.items():
            if not(name.startswith('word/')and name.endswith('.xml'))or name in('word/styles.xml','word/numbering.xml','word/stylesWithEffects.xml'):continue
            tree=xml(raw)
            if any(n.get(q('val'))not in(None,'0')for n in tree.findall('.//'+q('numPr')+'/'+q('numId'))):raise ValueError('Unsupported automatic list numbering in a combined book')
            active.update(n.get(q('val'))for n in tree.iter()if n.tag in STYLE_REFERENCES)
        pending=list(active)
        while pending:
            style=by_style.get(pending.pop())
            if style is None:continue
            if any(n.get(q('val'))not in(None,'0')for n in style.findall('.//'+q('numPr')+'/'+q('numId'))):raise ValueError('Unsupported automatic list numbering in a combined book')
            dependencies={n.get(q('val'))for n in style.iter()if n.tag in STYLE_REFERENCES}-active
            active.update(dependencies);pending.extend(dependencies)
        sources.append((parts,document,body))
    numbering=[semantic(xml(source['word/numbering.xml']))if'word/numbering.xml'in source else None for source,_,_ in sources]
    if any(item!=numbering[0]for item in numbering[1:]):
        raise ValueError('Constituent books use incompatible automatic numbering definitions')
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
    style_remaps=[]
    for index,(source,_,source_body)in enumerate(sources[1:],2):
        source_body=deepcopy(source_body);source_styles=BookStyles(styles,xml(source['word/styles.xml']),index)
        if 'word/numbering.xml'in source and any(n.tag in STYLE_REFERENCES and n.get(q('val'))in source_styles.ids for n in xml(source['word/numbering.xml']).iter()):
            raise ValueError('Cannot isolate a style referenced by shared automatic numbering definitions')
        source_styles.rewrite(source_body)
        if source_styles.ids:style_remaps.append({'part':index,'styles':source_styles.ids})
        common={'word/styles.xml':'word/styles.xml','word/fontTable.xml':'word/fontTable.xml','word/settings.xml':'word/settings.xml','word/footnotes.xml':'word/footnotes.xml','word/numbering.xml':'word/numbering.xml'}
        common.update({n:n for n in source if n.startswith('word/theme/')and n in parts});mapped=dict(common)
        overrides={n.get('PartName','').lstrip('/'):n.get('ContentType')for n in xml(source['[Content_Types].xml'])if n.tag=='{'+C+'}Override'}
        def copy_part(name):
            if name in mapped:return mapped[name]
            if name not in source:raise ValueError('Unresolved Word package dependency')
            target=posixpath.join(posixpath.dirname(name),'m'+str(index)+'-'+posixpath.basename(name));mapped[name]=target;parts[target]=source[name]
            if name.endswith('.xml'):
                copied_xml=xml(source[name]);source_styles.rewrite(copied_xml);parts[target]=serialized(copied_xml)
            if name in overrides:content_type(target,overrides[name])
            relationships=relpath(name)
            if relationships in source:
                copied=xml(source[relationships])
                for rel in copied:
                    if rel.get('TargetMode')=='External':continue
                    destination=copy_part(resolved(name,rel.get('Target')));rel.set('Target',posixpath.relpath(destination,posixpath.dirname(target)))
                parts[relpath(target)]=serialized(copied)
            return target
        merge_fonts(parts,source,index,copy_part,content_type)
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
                note_ids[old]=str(next_note);next_note+=1;note=deepcopy(normal[old]);note.set(q('id'),note_ids[old]);source_styles.rewrite(note);footnotes.append(note)
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
    return {'parts':len(inputs),'sourceBodyExactlyPreserved':True,'sourceFootnotesExactlyPreserved':len(expected_notes),'imagesAndAudioLinksVerified':len(expected_payloads),'independentBookPagination':True,'isolatedStyles':style_remaps}

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
