"""Restore native TOC links lost by the pinned renderer's DOCX import.

The keep-contents path regenerates native destinations, then restores only the
exact input page-number caches. Titles, row order, anchors and source targets
must remain identical. Existing Word/PDF publication validators remain strict.
"""
from collections import Counter
import json
import re
import xml.etree.ElementTree as ET
import zipfile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CONTENT_INDEX = 'com.sun.star.text.ContentIndex'
TOC_STYLES = {'TOC1': 1, 'TOC 1': 1, 'TOC2': 2, 'TOC 2': 2}


def tag(name):
    return '{' + W + '}' + name


def _style(paragraph):
    value = paragraph.find('./' + tag('pPr') + '/' + tag('pStyle'))
    return value.get(tag('val')) if value is not None else None


def _visible(element):
    if element.tag in {tag('pPr'), tag('rPr')}:
        return ''
    if element.tag == tag('t'):
        return element.text or ''
    if element.tag == tag('tab'):
        return '\t'
    if element.tag in {tag('br'), tag('cr')}:
        return '\n'
    if element.tag == tag('noBreakHyphen'):
        return '\u2011'
    if element.tag == tag('softHyphen'):
        return '\u00ad'
    return ''.join(_visible(child) for child in element)


def _split_cache(text):
    prefix, separator, cache = text.rpartition('\t')
    if not separator or not prefix or not cache.isdecimal() or int(cache) < 1:
        raise ValueError('Contents entry has no exact positive numeric cache')
    return prefix + separator, cache


def _has_contents_field(root):
    """Recognize actual TOC instructions, including split complex field runs."""
    def contents(parts):
        return re.match(r'^\s*TOC(?:\s|$)', ''.join(parts), re.IGNORECASE) is not None
    stack = []
    for node in root.iter():
        if node.tag == tag('fldSimple') and contents([node.get(tag('instr'), '')]):
            return True
        if node.tag == tag('fldChar'):
            kind = node.get(tag('fldCharType'))
            if kind == 'begin':
                stack.append([])
            elif kind in {'separate', 'end'} and stack:
                if contents(stack[-1]):
                    return True
                if kind == 'end':
                    stack.pop()
        elif node.tag == tag('instrText'):
            if stack:
                stack[-1].append(node.text or '')
            elif contents([node.text or '']):
                return True
    return any(contents(parts) for parts in stack)


def read_cached_contents(path):
    """Bind cached rows to existing, unique internal targets before UNO import."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    paragraphs = list(root.iter(tag('p')))
    names = Counter(node.get(tag('name')) for node in root.iter(tag('bookmarkStart')))
    targets = {}
    source_ordinal = 0
    for paragraph in paragraphs:
        if _style(paragraph) in TOC_STYLES:
            continue
        text = _visible(paragraph)
        if not text.strip():
            continue
        binding = {'sourceParagraphOrdinal': source_ordinal,
                   'style': _style(paragraph), 'text': text}
        for node in paragraph.iter(tag('bookmarkStart')):
            targets[node.get(tag('name'))] = binding
        source_ordinal += 1
    rows = []
    for paragraph in paragraphs:
        level = TOC_STYLES.get(_style(paragraph))
        if level is None:
            continue
        links = list(paragraph.iter(tag('hyperlink')))
        if len(links) != 1:
            raise ValueError('Cached contents entry has no unique internal link')
        link = links[0]
        anchor = link.get(tag('anchor'))
        if (not anchor or '{' + R + '}id' in link.attrib
                or names[anchor] != 1 or anchor not in targets):
            raise ValueError('Cached contents target is missing, ambiguous or external')
        prefix, cache = _split_cache(_visible(paragraph))
        rows.append({'level': level, 'anchor': anchor, 'prefix': prefix,
                     'cache': cache, 'target': targets[anchor]})
    if not rows and _has_contents_field(root):
        raise ValueError('Cached contents entries are missing')
    return rows


def verify_cached_contents(path, expected):
    if read_cached_contents(path) != expected:
        raise ValueError('Saved contents text, cache or source target changed')


def _contains(text, outer, inner):
    # XTextRangeCompare returns +1 when the first range starts/ends earlier.
    return (text.compareRegionStarts(inner, outer) <= 0
            and text.compareRegionEnds(inner, outer) >= 0)


def _native_rows(index):
    """Enumerate the actual index section, excluding any index header."""
    anchor = index.ContentSection.getAnchor()
    text = anchor.getText()
    selection = text.createTextCursorByRange(anchor.getStart())
    selection.gotoRange(anchor.getEnd(), True)
    enumeration = selection.createEnumeration()
    header = index.HeaderSection
    header_anchor = header.getAnchor() if header is not None else None
    rows = []
    while enumeration.hasMoreElements():
        paragraph = enumeration.nextElement()
        if not paragraph.supportsService('com.sun.star.text.Paragraph'):
            raise ValueError('Contents section has unexpected non-paragraph content')
        if not _contains(text, anchor, paragraph):
            raise ValueError('Contents paragraph crosses its native section boundary')
        if header_anchor is not None and _contains(text, header_anchor, paragraph):
            continue
        cursor = text.createTextCursorByRange(paragraph.getStart())
        cursor.gotoRange(paragraph.getEnd(), True)
        rows.append((paragraph, cursor))
    return rows


def _tail_cursor(paragraph, cache):
    cursor = paragraph.getText().createTextCursorByRange(paragraph.getEnd())
    units = len(cache.encode('utf-16-le')) // 2
    if not cursor.goLeft(units, True) or cursor.getString() != cache:
        raise ValueError('Cannot select the exact generated numeric cache')
    return cursor


def _link_properties(cursor):
    names = ['HyperLinkURL', 'VisitedCharStyleName', 'UnvisitedCharStyleName']
    info = cursor.getPropertySetInfo()
    names.extend(name for name in ('HyperLinkName', 'HyperLinkTarget')
                 if info.hasPropertyByName(name))
    return {name: cursor.getPropertyValue(name) for name in names}


def _link_spans(paragraph):
    spans = []
    portions = paragraph.createEnumeration()
    while portions.hasMoreElements():
        portion = portions.nextElement()
        info = portion.getPropertySetInfo()
        item = {'text': portion.getString()}
        for name in ('TextPortionType', 'HyperLinkURL', 'HyperLinkName', 'HyperLinkTarget',
                     'VisitedCharStyleName', 'UnvisitedCharStyleName'):
            if info.hasPropertyByName(name):
                item[name] = portion.getPropertyValue(name)
        spans.append(item)
    return spans


def refresh_cached_contents(doc, expected):
    """Regenerate real native targets and restore only validated numeric tails."""
    indexes = doc.getDocumentIndexes()
    contents = [indexes.getByIndex(i) for i in range(indexes.getCount())
                if indexes.getByIndex(i).getServiceName() == CONTENT_INDEX]
    if not expected:
        if contents:
            raise ValueError('Native contents index has no validated cached rows')
        return 0
    before = [row for index in contents for row in _native_rows(index)]
    if len(before) != len(expected):
        raise ValueError('Imported contents row count changed')
    for (_, cursor), saved in zip(before, expected):
        if cursor.getString() != saved['prefix'] + saved['cache']:
            raise ValueError('Imported contents title, separator or cache changed')
        url = cursor.getPropertyValue('HyperLinkURL')
        if url and url != '#' + saved['anchor']:
            raise ValueError('Imported contents target changed')
    if all(cursor.getPropertyValue('HyperLinkURL') == '#' + saved['anchor']
           for (_, cursor), saved in zip(before, expected)):
        return 0
    for index in contents:
        index.update()
    after = [row for index in contents for row in _native_rows(index)]
    if len(after) != len(expected):
        raise ValueError('Regenerated contents row count changed')
    edits = []
    for (paragraph, cursor), saved in zip(after, expected):
        prefix, cache = _split_cache(cursor.getString())
        if prefix != saved['prefix']:
            raise ValueError('Regenerated contents title or separator changed')
        if cursor.getPropertyValue('HyperLinkURL') != '#' + saved['anchor']:
            raise ValueError('Regenerated contents target changed')
        if cache != saved['cache']:
            tail = _tail_cursor(paragraph, cache)
            properties = _link_properties(cursor)
            if (properties['HyperLinkURL'] != '#' + saved['anchor']
                    or tail.getPropertyValue('HyperLinkURL') != properties['HyperLinkURL']
                    or any(not isinstance(value, str) for value in properties.values())):
                raise ValueError('Generated numeric cache has ambiguous link properties')
            before_spans = _link_spans(paragraph) if len(edits) < 3 else None
            edits.append((paragraph, tail, saved, properties, before_spans))
    protected = [(index, index.IsProtected) for index in contents]
    coalesced = 0
    samples = []
    try:
        for index, _ in protected:
            index.IsProtected = False
        for paragraph, tail, saved, properties, before_spans in edits:
            tail.setString(saved['cache'])
            replacement = _tail_cursor(paragraph, saved['cache'])
            if paragraph.getString() != saved['prefix'] + saved['cache']:
                raise ValueError('Numeric cache replacement changed contents row text')
            # Preserve the numeric span's hyperlink attributes across replacement,
            # using only the exact native properties captured before that edit.
            for name, value in properties.items():
                replacement.setPropertyValue(name, value)
            whole = paragraph.getText().createTextCursorByRange(paragraph.getStart())
            whole.gotoRange(paragraph.getEnd(), True)
            url = whole.getPropertyValue('HyperLinkURL')
            if url != properties['HyperLinkURL']:
                spans = _link_spans(paragraph)
                if (whole.getString() != saved['prefix'] + saved['cache']
                        or ''.join(span['text'] for span in spans) != whole.getString()
                        or any(span.get('HyperLinkURL') != properties['HyperLinkURL']
                               for span in spans if span['text'])):
                    raise ValueError('Numeric edit changed native link spans: ' + repr(spans))
                # Mixed range state can result from distinct native hyperlink
                # attributes with the same URL. Reapply only the properties
                # proven uniform across this entire generated row before editing.
                for name, value in properties.items():
                    whole.setPropertyValue(name, value)
                coalesced += 1
                if len(samples) < 3:
                    samples.append({'anchor': saved['anchor'], 'before': before_spans,
                                    'afterNumericEdit': spans, 'restoredProperties': properties})
    finally:
        for index, value in protected:
            index.IsProtected = value
    restored = [row for index in contents for row in _native_rows(index)]
    if len(restored) != len(expected):
        raise ValueError('Restored contents row count changed')
    for number, ((_, cursor), saved) in enumerate(zip(restored, expected), 1):
        if cursor.getString() != saved['prefix'] + saved['cache']:
            raise ValueError('Restoring numeric cache changed contents text at row ' + str(number))
        url = cursor.getPropertyValue('HyperLinkURL')
        if url != '#' + saved['anchor']:
            raise ValueError('Restoring numeric cache changed contents URL at row '
                             + str(number) + ': ' + repr(url))
    if coalesced:
        print(json.dumps({'schema': 'iman-toc-link-metadata-coalescing-v1',
                          'rows': coalesced, 'samples': samples}, ensure_ascii=True))
    return len(edits)
