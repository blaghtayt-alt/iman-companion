"""Preserve and verify pinned embedded Word fonts after LibreOffice saves."""
from pathlib import Path,PurePosixPath
import hashlib,json,uuid,zipfile
from lxml import etree
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';P='http://schemas.openxmlformats.org/package/2006/relationships';CT='http://schemas.openxmlformats.org/package/2006/content-types'
q=lambda ns,name:'{'+ns+'}'+name
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def families(conf,lang):
    selected=[conf['fonts'][conf['languages'][lang]['font']],conf['fonts']['Arabic'],conf['fonts']['Latin']]
    selected.extend(conf['fonts'][key]for key in['SymbolsLTR','SymbolsRTL']if key in conf['fonts'])
    native={'ar':'DigitsArabic','ur':'DigitsPersian','fa':'DigitsPersian'}.get(lang)
    if native and native in conf['fonts']:selected.append(conf['fonts'][native])
    return {f['family']:f for f in selected}

def verify(file,conf,lang):
    with zipfile.ZipFile(file) as z:
        table=etree.fromstring(z.read('word/fontTable.xml'));rels=etree.fromstring(z.read('word/_rels/fontTable.xml.rels'));relationships={r.get('Id'):r for r in rels}
        for family,definition in families(conf,lang).items():
            nodes=[n for n in table if n.get(q(W,'name'))==family]
            if len(nodes)!=1:raise ValueError('Missing or ambiguous pinned font: '+family)
            for style,expected in definition['sha256'].items():
                embedded=nodes[0].find(q(W,'embed'+style))
                if embedded is None:raise ValueError('Missing embedded font style: '+family+' '+style)
                rel=relationships.get(embedded.get(q(R,'id')))
                if rel is None or rel.get('Type')!=R+'/font' or rel.get('TargetMode')=='External':raise ValueError('Invalid embedded-font relationship')
                target=PurePosixPath(rel.get('Target',''))
                if target.is_absolute() or '..' in target.parts or not str(target).startswith('fonts/'):raise ValueError('Invalid embedded-font target')
                data=bytearray(z.read('word/'+str(target)));key=uuid.UUID(embedded.get(q(W,'fontKey')).strip('{}'));mask=key.bytes[::-1]
                if len(data)<32:raise ValueError('Truncated embedded font')
                for j in range(32):data[j]^=mask[j%16]
                if sha(data)!=expected:raise ValueError('Embedded font does not match pinned source: '+family+' '+style)
    return True

def restore(file,conf,lang,root):
    with zipfile.ZipFile(file) as z:parts={n:z.read(n) for n in z.namelist()}
    table=etree.fromstring(parts['word/fontTable.xml'])
    rels=etree.fromstring(parts['word/_rels/fontTable.xml.rels']) if 'word/_rels/fontTable.xml.rels' in parts else etree.Element(q(P,'Relationships'),nsmap={None:P})
    used={r.get('Id') for r in rels}
    for family,definition in families(conf,lang).items():
        nodes=[n for n in table if n.get(q(W,'name'))==family]
        if len(nodes)>1:raise ValueError('Ambiguous font table entry')
        node=nodes[0] if nodes else etree.SubElement(table,q(W,'font'),{q(W,'name'):family})
        for style,relative in definition['files'].items():
            source=(root/relative).resolve()
            if not source.is_relative_to(root.resolve()):raise ValueError('Font path escapes root')
            raw=source.read_bytes();digest=sha(raw)
            if digest!=definition['sha256'][style]:raise ValueError('Pinned font source changed')
            for old in node.findall(q(W,'embed'+style)):node.remove(old)
            key=uuid.uuid5(uuid.NAMESPACE_URL,'iman-book:'+family+style+digest);mask=key.bytes[::-1];data=bytearray(raw)
            for j in range(32):data[j]^=mask[j%16]
            target='fonts/iman-'+key.hex+'.odttf';name='word/'+target
            if name in parts and parts[name]!=bytes(data):raise ValueError('Existing font member conflicts')
            parts[name]=bytes(data);rid='imanfont-'+key.hex
            if rid in used:
                existing=next(r for r in rels if r.get('Id')==rid)
                if existing.get('Target')!=target or existing.get('Type')!=R+'/font':raise ValueError('Existing font relationship conflicts')
            else:etree.SubElement(rels,q(P,'Relationship'),{'Id':rid,'Type':R+'/font','Target':target});used.add(rid)
            etree.SubElement(node,q(W,'embed'+style),{q(R,'id'):rid,q(W,'fontKey'):'{'+str(key).upper()+'}'})
    parts['word/fontTable.xml']=etree.tostring(table,xml_declaration=True,encoding='UTF-8',standalone=True);parts['word/_rels/fontTable.xml.rels']=etree.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
    types=etree.fromstring(parts['[Content_Types].xml'])
    if not any(n.get('Extension')=='odttf' for n in types):etree.SubElement(types,q(CT,'Default'),{'Extension':'odttf','ContentType':'application/vnd.openxmlformats-officedocument.obfuscatedFont'})
    parts['[Content_Types].xml']=etree.tostring(types,xml_declaration=True,encoding='UTF-8',standalone=True)
    settings=etree.fromstring(parts['word/settings.xml']);embedded=settings.find(q(W,'embedTrueTypeFonts'))
    if embedded is None:embedded=etree.SubElement(settings,q(W,'embedTrueTypeFonts'))
    embedded.set(q(W,'val'),'true');parts['word/settings.xml']=etree.tostring(settings,xml_declaration=True,encoding='UTF-8',standalone=True)
    tmp=file.with_name(file.name+'.font-pending')
    if tmp.exists():raise ValueError('Foreign temporary file exists')
    try:
        with zipfile.ZipFile(tmp,'x',zipfile.ZIP_DEFLATED) as z:
            for name,data in parts.items():z.writestr(name,data)
        verify(tmp,conf,lang);tmp.replace(file)
    except BaseException:
        if tmp.exists():tmp.unlink()
        raise
