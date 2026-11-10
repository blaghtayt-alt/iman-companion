"""Keep an Arabic quotation and its native locator in one RTL font run.

This is a general formatting rule for English books: a brace-delimited Arabic
quotation followed by an Arabic label, colon and Arabic-Indic number. It does
not depend on an edition or source-review status. The surrounding paragraph and
every literal character stay unchanged. This narrow shape has no Latin text,
square citation markers or bidi controls. Ordinary numeric references continue
through the existing numeric tokenizer.
"""
from copy import deepcopy
import re
import unicodedata
from reader_xml import body_text

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
q = lambda name: '{' + W + '}' + name
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
ARABIC = r'\u0600-\u06ff\u0750-\u077f\u0870-\u08ff\ufb50-\ufdff\ufe70-\ufeff'
PATTERN = re.compile(r'\{([^{}]+)\}[ \t]*([' + ARABIC + r']+(?:[ \t]+[' + ARABIC + r']+)*)[ \t]*:[ \t]*([\u0660-\u0669]+)')
PUNCTUATION = '،؛؟'
FONT_PROPERTIES = {q(name) for name in ('rFonts', 'rtl', 'cs', 'lang')}


def _arabic_character(character):
    return bool(re.fullmatch('[' + ARABIC + ']', character))


def _arabic_text(text, *, label=False):
    letter = False
    for char in text:
        if char in (' \t' if label else ' \t\n\r'):
            continue
        if not label and char in PUNCTUATION:
            continue
        category = unicodedata.category(char)
        if not _arabic_character(char) or category[0] not in ('L', 'M') and not (not label and category == 'Nd'):
            return False
        letter |= category[0] == 'L'
    return letter


def quote_ranges(text, language):
    """Return complete Arabic-only quote/locator offsets in English text."""
    if language != 'en':
        return []
    result = []
    for match in PATTERN.finditer(text):
        if not _arabic_text(match[1]) or not _arabic_text(match[2], label=True):
            continue
        if match.end() < len(text) and (text[match.end()].isalnum() or unicodedata.category(text[match.end()])[0] == 'M'):
            continue
        result.append((match.start(), match.end()))
    return result


def quote_segments(text, language):
    """Yield unchanged segments, a coherent-RTL flag and original offsets."""
    start = 0
    for left, right in quote_ranges(text, language):
        if left > start:
            yield text[start:left], False, start
        yield text[left:right], True, left
        start = right
    if start < len(text):
        yield text[start:], False, start


def _safe_run(run):
    if run.tag != q('r') or len(run.findall(q('rPr'))) > 1:
        raise ValueError('Arabic quotation crosses unsupported Word content')
    for node in run:
        if node.tag == q('rPr'):
            continue
        if node.tag not in {q('t'), q('br'), q('cr'), q('tab')} or len(node):
            raise ValueError('Arabic quotation crosses a field, reference or unsupported Word run')
        if node.tag == q('br') and (node.get(q('type')) not in (None, 'textWrapping') or node.get(q('clear')) is not None):
            raise ValueError('Arabic quotation crosses a non-text Word break')


def _format_signature(run):
    from lxml import etree
    properties = run.find(q('rPr'))
    if properties is None:
        return ()
    values = {}
    for node in properties:
        if node.tag not in FONT_PROPERTIES:
            values.setdefault(node.tag, set()).add(etree.tostring(node, method='c14n'))
    if any(len(items) != 1 for items in values.values()):
        raise ValueError('Arabic quotation has conflicting repeated formatting')
    # LibreOffice can repeat the same b=false property in Arabic runs. Those
    # identical declarations are compatible; contradictory ones are not.
    return tuple(sorted(next(iter(items)) for items in values.values()))


def _slice_run(run, left, right):
    """Split only plain text/break/tab children, preserving their logical order."""
    _safe_run(run)
    result = deepcopy(run)
    for child in list(result):
        if child.tag != q('rPr'):
            result.remove(child)
    offset = 0
    for child in run:
        if child.tag == q('rPr'):
            continue
        length = len(child.text or '') if child.tag == q('t') else 1
        lo, hi = max(left - offset, 0), min(right - offset, length)
        if hi > lo:
            copied = deepcopy(child)
            if child.tag == q('t'):
                copied.text = (child.text or '')[lo:hi]
                if copied.text[0].isspace() or copied.text[-1].isspace():
                    copied.set(XML_SPACE, 'preserve')
            result.append(copied)
        offset += length
    return result


def _set_quote_font(run, family):
    from lxml import etree
    properties = run.find(q('rPr'))
    if properties is None:
        properties = etree.Element(q('rPr'))
        run.insert(0, properties)
    fonts = properties.find(q('rFonts'))
    if fonts is None:
        fonts = etree.Element(q('rFonts'))
        properties.insert(0, fonts)
    for key in list(fonts.attrib):
        if key.endswith('Theme'):
            del fonts.attrib[key]
    for slot in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        fonts.set(q(slot), family)
    for node in properties.findall(q('rtl')):
        properties.remove(node)
    etree.SubElement(properties, q('rtl'), {q('val'): '1'})


def _coalesce_ranges(paragraph, ranges, family):
    """Apply validated text matches to a disposable paragraph clone."""
    from lxml import etree
    before = etree.tostring(paragraph)
    for left, right in reversed(ranges):
        items = []
        offset = 0
        for index, child in enumerate(paragraph):
            length = len(body_text(child)) if child.tag != q('pPr') else 0
            if length and offset < right and offset + length > left:
                items.append((index, child, offset, length))
            elif not length and child.tag != q('pPr') and left < offset < right:
                raise ValueError('Arabic quotation crosses a Word anchor or unsupported element')
            offset += length
        if not items:
            raise ValueError('Arabic quotation run boundaries are unavailable')
        for _, run, _, _ in items:
            _safe_run(run)
        if len({_format_signature(run) for _, run, _, _ in items}) != 1:
            raise ValueError('Arabic quotation has incompatible non-font formatting')
        if items[-1][0] - items[0][0] + 1 != len(items):
            raise ValueError('Arabic quotation crosses non-run Word content')
        first, last = items[0], items[-1]
        replacement = []
        if left > first[2]:
            replacement.append(_slice_run(first[1], 0, left - first[2]))
        merged = deepcopy(first[1])
        for child in list(merged):
            if child.tag != q('rPr'):
                merged.remove(child)
        for _, run, start, length in items:
            piece = _slice_run(run, max(0, left - start), min(length, right - start))
            for child in list(piece):
                if child.tag != q('rPr'):
                    merged.append(child)
        _set_quote_font(merged, family)
        replacement.append(merged)
        if right < last[2] + last[3]:
            replacement.append(_slice_run(last[1], right - last[2], last[3]))
        for _, run, _, _ in items:
            paragraph.remove(run)
        for offset, run in enumerate(replacement):
            paragraph.insert(first[0] + offset, run)
    return int(etree.tostring(paragraph) != before)


def coalesce_quotes(paragraph, language, family):
    """Restore recognized quotations after a renderer splits their runs.

    Formatting outside the matches is retained. Unknown inline elements or
    differing non-font formatting inside a match fail closed; fields, anchors,
    hyperlinks and references are never flattened into replacement text.
    All spans are processed on a clone before committing any changes, so a
    failure in one span leaves the original paragraph byte-for-byte unchanged.
    The caller still verifies the complete _reader_content token invariant.
    """
    ranges = quote_ranges(body_text(paragraph), language)
    if not ranges:
        return 0
    candidate = deepcopy(paragraph)
    changed = _coalesce_ranges(candidate, ranges, family)
    if changed:
        paragraph[:] = list(candidate)
    return changed
