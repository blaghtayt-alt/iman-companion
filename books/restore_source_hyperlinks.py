"""Restore the exact reviewed bare-origin spelling after renderer URL rewriting.

Only an added slash on an otherwise identical bare HTTP(S) origin is eligible.
The exact source label, URL proof and occurrence count must identify every use
of the affected relationship. Reader XML and all other package parts stay exact;
the ordinary source-link validator remains strict.
"""
from collections import Counter
from io import BytesIO
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from zipfile import ZipFile

from lxml import etree
from check_outputs import validate_source_hyperlinks
from source_literal_text import check_text, proof_list

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
RELATIONSHIPS = 'word/_rels/document.xml.rels'


def _added_root_slash(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.netloc
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or url != parsed.scheme + '://' + parsed.netloc):
        raise ValueError('Only an added slash on an exact bare source origin may be restored')
    return url + '/'


def restore(file, expected, language, root):
    if not expected:
        return 0
    for link in expected:
        check_text(root, link['url'], language, proof_list(link.get('sourceLiteralProof')), exact=True)
    file = Path(file)
    original = file.read_bytes()
    with ZipFile(BytesIO(original)) as archive:
        infos = archive.infolist()
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError('Duplicate DOCX package members')
        parts = {info.filename: archive.read(info.filename) for info in infos}
        comment = archive.comment
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    body = etree.fromstring(parts['word/document.xml'], parser)
    relationships = etree.fromstring(parts[RELATIONSHIPS], parser)
    ids = [item.get('Id') for item in relationships]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate DOCX relationship IDs')
    targets = {item.get('Id'): item for item in relationships
               if item.get('Type') == R + '/hyperlink' and item.get('TargetMode') == 'External'}
    links = [(node, ''.join(node.itertext('{' + W + '}t')), node.get('{' + R + '}id'))
             for node in body.iter('{' + W + '}hyperlink')]
    actual = Counter((text, targets[rid].get('Target')) for node, text, rid in links if rid in targets)
    required = Counter((link['text'], link['url']) for link in expected)
    repairs = {}
    selected = set()
    for (text, url), count in (required - actual).items():
        rewritten = _added_root_slash(url)
        if required[(text, rewritten)]:
            raise ValueError('Ambiguous original source-link spellings; preserve the document')
        matches = [(node, rid) for node, label, rid in links
                   if label == text and rid in targets and targets[rid].get('Target') == rewritten]
        if len(matches) != count:
            raise ValueError('Source link label, target or count changed beyond an added root slash')
        for node, rid in matches:
            if rid in repairs and repairs[rid] != url:
                raise ValueError('Conflicting source targets share a relationship')
            repairs[rid] = url
            selected.add(node)
    if not repairs:
        validate_source_hyperlinks(body, relationships, expected, language, root)
        return 0
    # A relationship can also be shared by another label or a drawing link.
    # Reject that case rather than changing any use not identified above.
    if any(node.get('{' + R + '}id') in repairs and node not in selected for node in body.iter()):
        raise ValueError('Source relationship is shared with an unrelated link')
    for rid, url in repairs.items():
        targets[rid].set('Target', url)
    validate_source_hyperlinks(body, relationships, expected, language, root)
    parts[RELATIONSHIPS] = etree.tostring(relationships, xml_declaration=True, encoding='UTF-8', standalone=True)
    descriptor, pending = tempfile.mkstemp(prefix='.source-links-', suffix='.docx', dir=file.parent)
    os.close(descriptor)
    try:
        with ZipFile(pending, 'w') as archive:
            archive.comment = comment
            for info in infos:
                archive.writestr(info, parts[info.filename])
        if file.read_bytes() != original:
            raise ValueError('Document changed during original source-link restoration')
        os.replace(pending, file)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return len(repairs)
