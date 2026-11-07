"""Restore explicit native complex-script font selection after a Word save.

LibreOffice may drop the cs slot/hint and Word then falls back to Cambria for
parts of Thai/Bengali/Hindi mixed-script paragraphs, despite embedded fonts.
No text, source marker, field, paragraph order or reference is rewritten.
"""
from lxml import etree
import re

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';q=lambda name:'{'+W+'}'+name
SCRIPTS={'th':r'[\u0e00-\u0e7f]','bn':r'[\u0980-\u09ff]','hi':r'[\u0900-\u097f]','ar':r'[\u0600-\u06ff\u0750-\u077f]','ur':r'[\u0600-\u06ff\u0750-\u077f]','fa':r'[\u0600-\u06ff\u0750-\u077f]'}

def repair_parts(parts,conf,language):
    if language not in SCRIPTS:return {}
    main=conf['fonts'][conf['languages'][language]['font']]['family'];arabic=conf['fonts']['Arabic']['family'];counts={}
    protected={conf['fonts'][k]['family']for k in ('DigitsArabic','DigitsPersian','SymbolsLTR','SymbolsRTL')if k in conf['fonts']}
    for name,raw in list(parts.items()):
        if not(name.startswith('word/')and name.endswith('.xml')):continue
        root=etree.fromstring(raw);before=etree.tostring(root);texts=[n.text for n in root.iter(q('t'))]
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
        if texts!=[n.text for n in root.iter(q('t'))]:raise ValueError('Font restoration changed source text')
        if etree.tostring(root)!=before:
            parts[name]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True);counts[name]=hinted
    return counts
