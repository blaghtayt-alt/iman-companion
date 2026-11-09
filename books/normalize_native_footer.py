"""Simplify the generated native PAGE expression before Writer imports it.

The renderer already replaces this expression with its native live page field.
Deleting the imported nested fields can itself stall layout in a long book, so
remove that temporary expression at the package boundary instead. Match the
complete generator output; an unfamiliar footer must remain untouched on error.
Only the standard library is available in the system Python UNO environment.
"""
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
from xml.dom import minidom
from zipfile import ZipFile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
DIGITS = {'ar': '٠١٢٣٤٥٦٧٨٩', 'ur': '۰۱۲۳۴۵۶۷۸۹', 'fa': '۰۱۲۳۴۵۶۷۸۹'}


def _instruction(value):
    return ' '.join(value.split())


def _generated_tokens(language):
    """The exact field/cache grammar emitted by native_pagination for PAGE."""
    def field(parts, cache=''):
        tokens = [('fldChar', 'begin')]
        for part in parts:
            tokens.extend([('instrText', _instruction(part))] if isinstance(part, str) else part)
        tokens.append(('fldChar', 'separate'))
        if cache:
            tokens.append(('t', cache))
        return tokens + [('fldChar', 'end')]

    native = DIGITS[language]
    tokens = []
    for power in (1000, 100, 10, 1):
        value = field([' = MOD(INT(', field([' PAGE \\* Arabic '], '2'), f' / {power}),10) '], '0')

        def choice(number):
            if number == 9:
                return '"' + native[number] + '" '
            return field([' IF ', value, f' = {number} "{native[number]}" ', choice(number + 1), ' '], native[0])

        selected = choice(0)
        if power > 1:
            selected = field([' IF ', field([' PAGE \\* Arabic '], '2'), f' >= {power} ', selected, ' "" '])
        tokens.extend(selected)
    return tokens


def _elements(node):
    elements = []
    for child in node.childNodes:
        if child.nodeType == child.ELEMENT_NODE:
            elements.append(child)
        elif child.nodeType != child.TEXT_NODE or child.data.strip():
            raise ValueError('Unknown content in generated native footer')
    return elements


def normalize_footer_xml(raw, language):
    if language not in DIGITS:
        return raw, 0
    if b'<!DOCTYPE' in raw:
        raise ValueError('Native footer must not contain a DTD')
    document = minidom.parseString(raw)
    root = document.documentElement
    if root.namespaceURI != W or root.localName != 'ftr':
        raise ValueError('Not a Word footer XML part')
    instructions = root.getElementsByTagNameNS(W, 'instrText')
    if not any(re.search(r'\b(?:IF|MOD|INT)\b', ''.join(child.data for child in node.childNodes
                                                     if child.nodeType == child.TEXT_NODE), re.I)
               for node in instructions):
        # Empty cover footers and ordinary PAGE fields from a preceding render
        # already have no generated formula to simplify.
        return raw, 0
    paragraphs = _elements(root)
    if len(paragraphs) != 1 or paragraphs[0].namespaceURI != W or paragraphs[0].localName != 'p':
        raise ValueError('Additional content in generated native footer')
    paragraph = paragraphs[0]
    children = _elements(paragraph)
    props = [node for node in children if node.namespaceURI == W and node.localName == 'pPr']
    runs = [node for node in children if node.namespaceURI == W and node.localName == 'r']
    if len(props) > 1 or len(props) + len(runs) != len(children) or not runs:
        raise ValueError('Additional content in generated native footer')
    tokens = []
    run_props = None
    field_prefix = None
    for run in runs:
        parts = _elements(run)
        if (run.attributes.length or len(parts) != 2 or parts[0].namespaceURI != W
                or parts[0].localName != 'rPr' or parts[1].namespaceURI != W):
            raise ValueError('Unknown run in generated native footer')
        if run_props is None:
            run_props = parts[0]
        elif parts[0].toxml() != run_props.toxml():
            raise ValueError('Mixed formatting in generated native footer')
        # These are the generator's complete formatting properties. Refuse
        # additional content even if it is concealed inside a property node.
        if any(node.namespaceURI != W or node.localName not in {'rFonts', 'sz', 'szCs', 'rtl'}
               for node in parts[0].getElementsByTagName('*')):
            raise ValueError('Unknown formatting in generated native footer')
        node = parts[1]
        if node.localName == 'fldChar':
            if node.attributes.length != 1 or node.childNodes:
                raise ValueError('Unknown field property in generated native footer')
            attribute = node.getAttributeNodeNS(W, 'fldCharType')
            if attribute is None:
                raise ValueError('Missing field type in generated native footer')
            field_prefix = attribute.prefix
            value = attribute.value
        elif node.localName in {'instrText', 't'}:
            if any(attr.namespaceURI != 'http://www.w3.org/XML/1998/namespace' or attr.localName != 'space'
                   for attr in node.attributes.values()):
                raise ValueError('Unknown text property in generated native footer')
            if any(child.nodeType != child.TEXT_NODE for child in node.childNodes):
                raise ValueError('Additional text content in generated native footer')
            value = ''.join(child.data for child in node.childNodes)
            if node.localName == 'instrText':
                value = _instruction(value)
        else:
            raise ValueError('Additional content in generated native footer')
        tokens.append((node.localName, value))
    if tokens != _generated_tokens(language) or not field_prefix:
        raise ValueError('Unrecognized generated native PAGE expression')
    for run in runs:
        paragraph.removeChild(run)
    for tag, value in (('fldChar', 'begin'), ('instrText', ' PAGE '),
                       ('fldChar', 'separate'), ('t', DIGITS[language][2]), ('fldChar', 'end')):
        run = document.createElementNS(W, field_prefix + ':r')
        run.appendChild(run_props.cloneNode(True))
        node = document.createElementNS(W, field_prefix + ':' + tag)
        if tag == 'fldChar':
            node.setAttributeNS(W, field_prefix + ':fldCharType', value)
        else:
            node.setAttributeNS('http://www.w3.org/XML/1998/namespace', 'xml:space', 'preserve')
            node.appendChild(document.createTextNode(value))
        run.appendChild(node)
        paragraph.appendChild(run)
    return document.toxml(encoding='UTF-8'), 1


def normalize(file, language):
    """Atomically change only recognized generated footer parts."""
    if language not in DIGITS:
        return 0
    file = Path(file)
    original = file.read_bytes()
    with ZipFile(BytesIO(original)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate DOCX package members')
        parts = {name: archive.read(name) for name in names}
        comment = archive.comment
    changed = 0
    for name, raw in parts.items():
        if name.startswith('word/footer') and name.endswith('.xml'):
            parts[name], count = normalize_footer_xml(raw, language)
            changed += count
    if not changed:
        return 0
    descriptor, pending = tempfile.mkstemp(prefix='.native-footer-', suffix='.docx', dir=file.parent)
    os.close(descriptor)
    try:
        with ZipFile(pending, 'w') as archive:
            archive.comment = comment
            for info in infos:
                archive.writestr(info, parts[info.filename])
        if file.read_bytes() != original:
            raise ValueError('Document changed during native footer normalization')
        os.replace(pending, file)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return changed
