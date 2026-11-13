"""Check actual ornate-bracket font selection in every generated Word book.

The source characters are never rewritten. Unicode FD3E/FD3F do not mirror
automatically. Pinned symbol faces paint the correct shape for each quoted
passage. Validate after renderer/font restoration so a lost font assignment
cannot silently reintroduce reversed brackets in a future book.
"""
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from book_typography import LEFT, RIGHT, SYMBOL_LTR, SYMBOL_RTL, quotation_mirrors

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
q = lambda name: '{' + W + '}' + name
SYMBOL_FACES = {SYMBOL_LTR, SYMBOL_RTL}


def _paired_positions(text):
    """Select complete pairs; a quote may legitimately continue in another p."""
    stack, positions = [], set()
    for offset, character in enumerate(text):
        if character not in {LEFT, RIGHT}:
            continue
        if stack and stack[-1][1] != character:
            positions.update((stack.pop()[0], offset))
        else:
            stack.append((offset, character))
    return positions


def validate_part(root, language, *, part='word/document.xml'):
    checked = paired = unpaired = 0
    for paragraph_number, paragraph in enumerate(root.iter(q('p')), 1):
        # Nested textbox paragraphs have their own bidi context and are
        # inspected separately. Their text must not shift outer offsets.
        nodes = [node for node in paragraph.iter(q('t'))
                 if next(node.iterancestors(q('p')), None) is paragraph]
        text = ''.join(node.text or '' for node in nodes)
        if not any(character in {LEFT, RIGHT} for character in text):
            continue
        complete = _paired_positions(text)
        mirrors = quotation_mirrors(text, language)
        offset = 0
        for node in nodes:
            run = next(node.iterancestors(q('r')), None)
            value = node.text or ''
            for index, character in enumerate(value):
                if character not in {LEFT, RIGHT}:
                    continue
                checked += 1
                location = f'{part}, paragraph {paragraph_number}, character {offset + index}'
                fonts = run.find('./' + q('rPr') + '/' + q('rFonts')) if run is not None else None
                faces = {fonts.get(q(slot)) if fonts is not None else None
                         for slot in ('ascii', 'hAnsi', 'eastAsia', 'cs')}
                if len(faces) != 1 or not faces <= SYMBOL_FACES:
                    raise ValueError('Unpinned ornate-bracket font at ' + location)
                if offset + index not in complete:
                    # Do not invent the direction of a source quotation
                    # extending beyond a paragraph. Still require pinned fonts.
                    unpaired += 1
                    continue
                paired += 1
                expected = SYMBOL_LTR if mirrors[offset + index] else SYMBOL_RTL
                if faces != {expected}:
                    raise ValueError('Reversed ornate-bracket direction at ' + location
                                     + '; expected ' + expected)
            offset += len(value)
    return {'ornateBrackets': checked, 'pairedMarkers': paired,
            'crossParagraphOrUnpairedMarkers': unpaired}


def verify(file, language):
    result = {'schema': 'iman-book-bracket-direction-v1', 'language': language,
              'ornateBrackets': 0, 'pairedMarkers': 0,
              'crossParagraphOrUnpairedMarkers': 0, 'parts': {}}
    with ZipFile(Path(file)) as archive:
        for name in archive.namelist():
            if not (name.startswith('word/') and name.endswith('.xml')):
                continue
            counts = validate_part(etree.fromstring(archive.read(name)), language, part=name)
            if counts['ornateBrackets']:
                result['parts'][name] = counts
                for key, count in counts.items():
                    result[key] += count
    return result
