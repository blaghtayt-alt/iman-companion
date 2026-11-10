"""Restore native font selection after a LibreOffice save.

LibreOffice may drop the cs slot/hint and Word then falls back to Cambria for
parts of Thai/Bengali/Hindi mixed-script paragraphs, despite embedded fonts.
Word also propagates fallback from unsupported WORD JOINER, em dash and bullet
characters to Arabic letters/digits in the same run. Actual Word A/B proofs
confirmed that isolation alone is insufficient: these neutral characters must
not force complex script. Keep their codepoints, text faces and all font bytes.
No text, source marker, field, paragraph order or reference is rewritten.
"""
from copy import deepcopy
from lxml import etree
import re
from script_fallbacks import fallback_runs,has_fallbacks
from reader_xml import body_text
from arabic_quote_direction import coalesce_quotes

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';q=lambda name:'{'+W+'}'+name
SCRIPTS={'th':r'[\u0e00-\u0e7f]','bn':r'[\u0980-\u09ff]','hi':r'[\u0900-\u097f]','ar':r'[\u0600-\u06ff\u0750-\u077f]','ur':r'[\u0600-\u06ff\u0750-\u077f]','fa':r'[\u0600-\u06ff\u0750-\u077f]'}
# Only the three failure characters demonstrated in actual Arabic Word proofs.
# In particular, ZWJ/ZWNJ affect Arabic letter shaping and must remain untouched.
ARABIC_FALLBACK_CHARS='\u2060\u2014\u2022'


def _reader_content(root):
    """Ignore run-format boundaries, retaining text and all other XML content.

    A text-node list is too strict when preserving a character by moving it to
    its own run. These tokens also preserve paragraph boundaries, field codes,
    reference IDs, and their order; only r/rPr and t wrapping is ignored.
    """
    tokens=[]
    def visit(node):
        if node.tag==q('rPr'):return
        if node.tag==q('t'):
            value=node.text or ''
            if tokens and tokens[-1][0]=='text':tokens[-1]=('text',tokens[-1][1]+value)
            else:tokens.append(('text',value))
            return
        if node.tag==q('r'):
            for child in node:visit(child)
            return
        tokens.append(('open',node.tag,tuple(sorted(node.attrib.items())),node.text if node.text and node.text.strip() else None))
        for child in node:visit(child)
        tokens.append(('close',node.tag))
    visit(root)
    return tokens


def _neutral_fallback_run(run):
    pr=run.find(q('rPr'))
    if pr is None:pr=etree.Element(q('rPr'));run.insert(0,pr)
    fonts=pr.find(q('rFonts'))
    if fonts is not None:fonts.attrib.pop(q('hint'),None)
    for old in pr.findall(q('cs'))+pr.findall(q('rtl')):pr.remove(old)
    etree.SubElement(pr,q('rtl'),{q('val'):'0'})


def _isolate_fallback_chars(run):
    if not any(any(c in (n.text or '') for c in ARABIC_FALLBACK_CHARS) for n in run.findall(q('t'))):return
    children=[n for n in run if n.tag!=q('rPr')]
    if all(n.tag==q('t') and not (n.text or '').strip(ARABIC_FALLBACK_CHARS) for n in children):
        _neutral_fallback_run(run)
        return
    # Group ordinary children around each control. Tabs, breaks, field markers,
    # drawings and footnote anchors stay once, in their original order.
    groups=[]
    for child in children:
        chunks=re.split('(['+ARABIC_FALLBACK_CHARS+']+)',child.text or '') if child.tag==q('t') else [None]
        for index,chunk in enumerate(chunks):
            if chunk=='':continue
            control=chunk is not None and not chunk.strip(ARABIC_FALLBACK_CHARS)
            node=deepcopy(child)
            if chunk is not None:
                node.text=chunk
                if chunk and (chunk[0].isspace() or chunk[-1].isspace()):
                    node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                if index!=len(chunks)-1:node.tail=None
            if not groups or groups[-1][0]!=control:groups.append((control,[]))
            groups[-1][1].append(node)
    parent=run.getparent();position=parent.index(run)
    for offset,(control,nodes) in enumerate(groups):
        new=deepcopy(run)
        for child in list(new):
            if child.tag!=q('rPr'):new.remove(child)
        new.text=None;new.tail=run.tail if offset==len(groups)-1 else None
        new.extend(nodes)
        if control:_neutral_fallback_run(new)
        parent.insert(position+offset,new)
    parent.remove(run)


def _set_pinned_fallback(run,key,conf):
    pr=run.find(q('rPr'))
    if pr is None:pr=etree.Element(q('rPr'));run.insert(0,pr)
    fonts=pr.find(q('rFonts'))
    if fonts is None:fonts=etree.Element(q('rFonts'));pr.insert(0,fonts)
    for attr in list(fonts.attrib):
        if attr.endswith('Theme'):del fonts.attrib[attr]
    for slot in ('ascii','hAnsi','eastAsia','cs'):fonts.set(q(slot),conf['fonts'][key]['family'])
    _neutral_fallback_run(run)
    if key=='Arabic':
        fonts.set(q('hint'),'cs');etree.SubElement(pr,q('cs'),{q('val'):'1'})
        pr.find(q('rtl')).set(q('val'),'1')


def _isolate_pinned_fallbacks(run,language,conf):
    """Keep source characters, field markers and anchors in their exact order."""
    paragraph=next(run.iterancestors(q('p')),None)
    source_text=body_text(paragraph) if paragraph is not None else None
    children=[node for node in run if node.tag!=q('rPr')];groups=[]
    for child in children:
        chunks=(list(fallback_runs(child.text or '',language,source_text=source_text)) or [('',None)]) if child.tag==q('t') else [(None,None)]
        for index,(chunk,key) in enumerate(chunks):
            node=deepcopy(child)
            if chunk is not None:
                node.text=chunk
                if chunk and (chunk[0].isspace() or chunk[-1].isspace()):
                    node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                if index!=len(chunks)-1:node.tail=None
            if not groups or groups[-1][0]!=key:groups.append((key,[]))
            groups[-1][1].append(node)
    if not any(key is not None for key,_ in groups):return
    if len(groups)==1:
        _set_pinned_fallback(run,groups[0][0],conf);return
    parent=run.getparent();position=parent.index(run)
    for offset,(key,nodes) in enumerate(groups):
        new=deepcopy(run)
        for child in list(new):
            if child.tag!=q('rPr'):new.remove(child)
        new.text=None;new.tail=run.tail if offset==len(groups)-1 else None;new.extend(nodes)
        if key is not None:_set_pinned_fallback(new,key,conf)
        parent.insert(position+offset,new)
    parent.remove(run)

def repair_parts(parts,conf,language):
    if language not in SCRIPTS and not has_fallbacks(language):return {}
    main=conf['fonts'][conf['languages'][language]['font']]['family'] if language in SCRIPTS else None
    arabic=conf['fonts']['Arabic']['family'];counts={}
    protected={conf['fonts'][k]['family']for k in ('DigitsArabic','DigitsPersian','SymbolsLTR','SymbolsRTL')if k in conf['fonts']}
    for name,raw in list(parts.items()):
        if not(name.startswith('word/')and name.endswith('.xml')):continue
        root=etree.fromstring(raw);before=etree.tostring(root);content=_reader_content(root)
        hinted=0
        if language=='en':
            for paragraph in root.iter(q('p')):coalesce_quotes(paragraph,language,arabic)
        if language=='th' and name=='word/styles.xml':
            # Live PAGE/TOC results inherit their style when Word refreshes
            # fields. Keep Thai in the complex-script slots and give generated
            # ASCII the same pinned Latin face used by authored number runs.
            for fonts in root.iter(q('rFonts')):
                if main in {fonts.get(q(slot)) for slot in ('ascii','hAnsi','eastAsia','cs')}:
                    for slot in ('ascii','hAnsi'):
                        fonts.set(q(slot),conf['fonts']['Latin']['family']);fonts.attrib.pop(q(slot+'Theme'),None)
        for run in list(root.iter(q('r'))):_isolate_pinned_fallbacks(run,language,conf)
        for run in root.iter(q('r')):
            text=''.join(n.text or ''for n in run.findall(q('t')))
            if language not in SCRIPTS or not re.search(SCRIPTS[language],text):continue
            pr=run.find(q('rPr'))
            if pr is None:pr=etree.Element(q('rPr'));run.insert(0,pr)
            fonts=pr.find(q('rFonts'))
            if fonts is None:fonts=etree.Element(q('rFonts'));pr.insert(0,fonts)
            # Preserve the separately selected canonical Arabic ayah face in
            # RTL books; all native body runs use the configured app face.
            slots=('ascii','hAnsi','eastAsia','cs')
            existing=next((fonts.get(q(s))for s in slots if fonts.get(q(s))in protected),None)
            family=existing or (arabic if language in {'ar','ur','fa'}and any(fonts.get(q(s))==arabic for s in slots)else main)
            for attr in list(fonts.attrib):
                if attr.endswith('Theme'):del fonts.attrib[attr]
            for slot in ('ascii','hAnsi','eastAsia','cs'):fonts.set(q(slot),family)
            fonts.set(q('hint'),'cs')
            for old in pr.findall(q('cs')):pr.remove(old)
            etree.SubElement(pr,q('cs'),{q('val'):'1'});hinted+=1
        if language=='ar':
            for run in list(root.iter(q('r'))):_isolate_fallback_chars(run)
        if content!=_reader_content(root):raise ValueError('Font restoration changed source text or structure')
        if etree.tostring(root)!=before:
            parts[name]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True);counts[name]=hinted
    return counts
