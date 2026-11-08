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

def repair_parts(parts,conf,language):
    if language not in SCRIPTS:return {}
    main=conf['fonts'][conf['languages'][language]['font']]['family'];arabic=conf['fonts']['Arabic']['family'];counts={}
    protected={conf['fonts'][k]['family']for k in ('DigitsArabic','DigitsPersian','SymbolsLTR','SymbolsRTL')if k in conf['fonts']}
    for name,raw in list(parts.items()):
        if not(name.startswith('word/')and name.endswith('.xml')):continue
        root=etree.fromstring(raw);before=etree.tostring(root);content=_reader_content(root)
        hinted=0
        for run in root.iter(q('r')):
            text=''.join(n.text or ''for n in run.findall(q('t')))
            if not re.search(SCRIPTS[language],text):continue
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
