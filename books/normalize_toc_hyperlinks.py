"""Preserve cached TOC hyperlinks when the pinned Writer imports a DOCX.

Writer tdf#168053 combines an optional tooltip with the internal hyperlink
command, then misparses its quoted target. Omit only that optional attribute
on an already valid internal contents link before import. Visible text,
native page digits, bookmarks, relationships and other properties stay exact.
XML attribute reordering does not fix the renderer's internal command order.
Remove this compatibility pass once the pinned renderer includes upstream
commit 2776654bbb109af114a44fe00ec9771e4ad2d99d and the real-book gate passes.

Only the standard library is used, so the system Python UNO process can run
this without sharing the publication virtual environment's dependencies.
"""
from io import BytesIO
from collections import Counter
import os
from pathlib import Path
import re
import tempfile
from xml.dom import minidom
from xml.etree.ElementTree import canonicalize
from xml.parsers import expat
from zipfile import ZipFile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CONTENT_INDEX = 'com.sun.star.text.ContentIndex'
PARAGRAPH = 'com.sun.star.text.Paragraph'


def label_native_contents(doc):
    """Label existing native links with their current visible row, without editing it.

    Run after the DOCX is saved and immediately before PDF export. The
    renderer uses HyperLinkName for PDF link accessibility text. A complete
    row includes its literal tab and current native page digits, which the
    unchanged PDF validators compare with the real link destination.
    These PDF labels must not be saved back into the editable DOCX: actual
    Word finalization may subsequently change its own numeric page caches.
    """
    indexes = doc.getDocumentIndexes()
    bookmarks = doc.getBookmarks()
    changes = []
    for number in range(indexes.getCount()):
        index = indexes.getByIndex(number)
        if index.getServiceName() != CONTENT_INDEX:
            continue
        styles = {getattr(index, 'ParaStyleLevel' + str(level)) for level in range(1, 11)}
        paragraphs = index.getAnchor().createEnumeration()
        while paragraphs.hasMoreElements():
            paragraph = paragraphs.nextElement()
            if not paragraph.supportsService(PARAGRAPH):
                continue
            value = paragraph.getString()
            if not value or paragraph.ParaStyleName == index.ParaStyleHeading:
                continue
            if paragraph.ParaStyleName not in styles:
                raise ValueError('Unexpected paragraph in native contents index')
            parts = []
            portions = paragraph.createEnumeration()
            while portions.hasMoreElements():
                portion = portions.nextElement()
                literal = portion.getString()
                if literal:
                    parts.append((literal, portion.HyperLinkURL))
            if ''.join(text for text, _ in parts) != value:
                raise ValueError('Native contents portions do not match the visible row')
            urls = {url for _, url in parts}
            if not any(urls):
                # Do not create a missing link. The unchanged final contents
                # validators must still reject this, including the control.
                continue
            if len(urls) != 1:
                raise ValueError('Native contents row is not one complete hyperlink')
            url = next(iter(urls))
            if not isinstance(url, str) or not url.startswith('#') or not bookmarks.hasByName(url[1:]):
                raise ValueError('Native contents link has no existing internal bookmark')
            title, separator, page = value.rpartition('\t')
            if not separator or not title.strip() or not page.strip().isdecimal() or int(page.strip()) < 1:
                raise ValueError('Native contents row has no numeric page cache')
            cursor = paragraph.getText().createTextCursorByRange(paragraph.getStart())
            cursor.gotoRange(paragraph.getEnd(), True)
            if cursor.getString() != value or cursor.HyperLinkURL != url:
                raise ValueError('Native contents cursor does not cover the exact linked row')
            changes.append((cursor, value, url))
    # Validate every row before assigning any label. Never assign String or
    # HyperLinkURL: reader text, page caches and targets belong to the index.
    for cursor, value, url in changes:
        cursor.HyperLinkName = value
        if cursor.getString() != value or cursor.HyperLinkURL != url or cursor.HyperLinkName != value:
            raise ValueError('Native contents accessibility label changed its text or target')
    return len(changes)


def children(node, name):
    return [child for child in node.childNodes
            if child.nodeType == child.ELEMENT_NODE
            and child.namespaceURI == W and child.localName == name]


def normalize_document_xml(raw):
    """Omit optional TOC tooltips; never create or infer a missing link target."""
    if b'<!DOCTYPE' in raw:
        raise ValueError('Document XML must not contain a DTD')
    document = minidom.parseString(raw)
    root = document.documentElement
    if root.namespaceURI != W or root.localName != 'document':
        raise ValueError('Not a Word document XML part')
    jobs = {}
    bookmarks = Counter(node.getAttributeNS(W, 'name')
                        for node in root.getElementsByTagNameNS(W, 'bookmarkStart'))
    links = root.getElementsByTagNameNS(W, 'hyperlink')
    for index, link in enumerate(links):
        paragraph = link.parentNode
        while paragraph is not None and not (paragraph.namespaceURI == W and paragraph.localName == 'p'):
            paragraph = paragraph.parentNode
        if paragraph is None:
            continue
        props = children(paragraph, 'pPr')
        styles = children(props[0], 'pStyle') if len(props) == 1 else []
        if len(styles) != 1 or not re.fullmatch(r'TOC\s*[1-9]', styles[0].getAttributeNS(W, 'val')):
            continue
        tooltip = link.getAttributeNodeNS(W, 'tooltip')
        if tooltip is None:
            continue
        anchor = link.getAttributeNS(W, 'anchor')
        if (not anchor or bookmarks[anchor] != 1
                or link.hasAttributeNS(R, 'id')
                or len(paragraph.getElementsByTagNameNS(W, 'hyperlink')) != 1):
            raise ValueError('Contents tooltip has no unique internal bookmark link')
        jobs[index] = tooltip.name.encode('UTF-8')
        link.removeAttributeNS(W, 'tooltip')
    if not jobs:
        return raw, 0
    # Delete only the original optional attribute bytes, without serializing
    # the DOM. Namespace prefixes, entities, comments, text, and every other
    # attribute retain their original bytes and order.
    edits = []
    seen = 0
    parser = expat.ParserCreate(namespace_separator='|')

    def start(name, attributes):
        nonlocal seen
        if name != W + '|hyperlink':
            return
        index = seen
        seen += 1
        if index not in jobs:
            return
        begin = parser.CurrentByteIndex
        end = begin + 1
        quote = None
        while end < len(raw):
            value = raw[end]
            if quote is not None:
                if value == quote:
                    quote = None
            elif value in (ord('"'), ord("'")):
                quote = value
            elif value == ord('>'):
                break
            end += 1
        tag = raw[begin:end + 1]
        attrs = list(re.finditer(rb'''\s+([^\s=/>]+)\s*=\s*(?:"[^"]*"|'[^']*')''', tag))
        selected = [match for match in attrs if match[1] == jobs[index]]
        if len(selected) != 1 or end >= len(raw):
            raise ValueError('Cannot preserve exact TOC hyperlink attribute bytes')
        match = selected[0]
        repaired = tag[:match.start()] + tag[match.end():]
        edits.append((begin, end + 1, repaired))

    parser.StartElementHandler = start
    parser.Parse(raw, True)
    if seen != len(links) or len(edits) != len(jobs):
        raise ValueError('Ambiguous TOC hyperlink normalization')
    result = raw
    for begin, end, repaired in reversed(edits):
        result = result[:begin] + repaired + result[end:]
    # The DOM has only the selected optional attributes removed. Canonical
    # equality verifies that no reader text, target, or other property changed.
    if canonicalize(document.toxml(encoding='UTF-8')) != canonicalize(result):
        raise ValueError('Unexpected XML change while normalizing TOC hyperlinks')
    return result, len(edits)


def normalize(file):
    """Atomically change only document.xml; preserve all other package bytes."""
    file = Path(file)
    with ZipFile(BytesIO(file.read_bytes())) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate DOCX package members')
        parts = {name: archive.read(name) for name in names}
        comment = archive.comment
    if 'word/document.xml' not in parts:
        raise ValueError('Missing Word document XML part')
    repaired, changed = normalize_document_xml(parts['word/document.xml'])
    if not changed:
        return 0
    parts['word/document.xml'] = repaired
    descriptor, pending = tempfile.mkstemp(prefix='.toc-hyperlinks-', suffix='.docx', dir=file.parent)
    os.close(descriptor)
    try:
        with ZipFile(pending, 'w') as archive:
            archive.comment = comment
            for info in infos:
                archive.writestr(info, parts[info.filename])
        os.replace(pending, file)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return changed
