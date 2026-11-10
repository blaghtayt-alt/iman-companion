"""Temporarily direct Arabic quotation lines during LibreOffice PDF export.

Word uses the saved coherent RTL runs, but LibreOffice needs explicit embedding
controls for the same narrow English quotation shape. These controls exist only
in the loaded document during PDF export. Insert and remove them with collapsed
or single-control cursors; never replace source text or save the loaded DOCX.
"""
from collections import defaultdict
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import re
from arabic_quote_direction import quote_ranges

RLE = '\u202b'
PDF = '\u202c'


class PdfQuoteRestorationError(RuntimeError):
    """The PDF attempt must fail because exact restoration was not verified."""


def control_insertions(text):
    """Return original Python offsets and controls for each quotation line."""
    positions = defaultdict(list)
    for left, right in quote_ranges(text, 'en'):
        start = left
        for newline in re.finditer(r'\r\n|[\r\n]', text[left:right]):
            end = left + newline.start()
            if text[start:end].strip():
                positions[start].append(RLE)
                positions[end].append(PDF)
            start = left + newline.end()
        if text[start:right].strip():
            positions[start].append(RLE)
            positions[right].append(PDF)
    # Adjacent quotations share a boundary: close the earlier embedding before
    # opening the next. One insertion at that boundary preserves this order.
    return [(position, ''.join(sorted(values, key=lambda value: value != PDF)))
            for position, values in sorted(positions.items())]


def _utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def _cursor(paragraph, expected_prefix, length=0):
    text = paragraph.getText()
    # XTextCursor.goRight accepts a signed 16-bit character count. Actual UNO
    # versions can count a non-BMP character differently from UTF-16 offsets.
    # Try both conventions on fresh cursors, accepting only an exact selected
    # prefix; no source-adjacent mutation occurs before that boundary is proven.
    cursor = None
    for count in dict.fromkeys((_utf16_length(expected_prefix), len(expected_prefix))):
        candidate = text.createTextCursorByRange(paragraph.getStart())
        remaining = count
        while remaining:
            step = min(remaining, 32767)
            if not candidate.goRight(step, True):
                break
            remaining -= step
        if not remaining and candidate.getString() == expected_prefix:
            cursor = candidate
            break
    if cursor is None:
        raise ValueError('Arabic quotation cursor prefix does not match the original text')
    cursor.collapseToEnd()
    if cursor.getString():
        raise ValueError('Arabic quotation insertion cursor is not collapsed')
    if length and not cursor.goRight(length, True):
        raise ValueError('Cannot select the recorded PDF direction control')
    return text, cursor


def _expected(original, insertions):
    pieces = []
    start = 0
    for position, controls in sorted(insertions):
        pieces.extend((original[start:position], controls))
        start = position
    pieces.append(original[start:])
    return ''.join(pieces)


def _remove_controls(state):
    paragraph, original, applied = state
    if paragraph.getString() != _expected(original, applied):
        raise ValueError('PDF quotation paragraph differs from its recorded insertions')
    positions = []
    shift = 0
    for position, controls in sorted(applied):
        offset = position + shift
        positions.extend((offset + index, char) for index, char in enumerate(controls))
        shift += len(controls)
    for offset, char in reversed(positions):
        text, cursor = _cursor(paragraph, _expected(original, applied)[:offset], 1)
        if cursor.getString() != char:
            raise ValueError('Recorded PDF direction control is not at its exact offset')
        text.insertString(cursor, '', True)
    if paragraph.getString() != original:
        raise ValueError('PDF quotation paragraph was not exactly restored')


@contextmanager
def temporary_pdf_quote_direction(doc, language, saved_docx):
    """Keep source characters and the saved DOCX unchanged around PDF export.

    Non-English documents are untouched. Existing controls in source text are
    preserved: cleanup removes only the characters recorded by this context.
    Export errors propagate unchanged when restoration succeeds. A restoration
    failure aborts the operation and retains the export error as its cause.
    """
    saved_docx = Path(saved_docx)
    disk_hash = sha256(saved_docx.read_bytes()).hexdigest()
    body = None
    original_body = None
    states = []
    active_error = None
    control_count = 0
    try:
        if language == 'en':
            body = doc.getText()
            original_body = body.getString()
            paragraphs = body.createEnumeration()
            while paragraphs.hasMoreElements():
                paragraph = paragraphs.nextElement()
                if not paragraph.supportsService('com.sun.star.text.Paragraph'):
                    continue
                original = paragraph.getString()
                insertions = control_insertions(original)
                if not insertions:
                    continue
                applied = []
                states.append((paragraph, original, applied))
                for position, controls in reversed(insertions):
                    text, cursor = _cursor(paragraph, original[:position])
                    text.insertString(cursor, controls, False)
                    applied.append((position, controls))
                    control_count += len(controls)
                if paragraph.getString() != _expected(original, insertions):
                    raise ValueError('PDF direction controls changed more than their exact insertion positions')
        yield {'paragraphs': len(states), 'insertedControls': control_count}
    except BaseException as error:
        active_error = error
        raise
    finally:
        restoration_errors = []
        for state in reversed(states):
            try:
                _remove_controls(state)
            except Exception as error:
                restoration_errors.append(error)
        if body is not None:
            try:
                if body.getString() != original_body:
                    raise ValueError('PDF export did not exactly restore the complete document body')
            except Exception as error:
                restoration_errors.append(error)
        try:
            if sha256(saved_docx.read_bytes()).hexdigest() != disk_hash:
                raise ValueError('Saved DOCX bytes changed during PDF export')
        except Exception as error:
            restoration_errors.append(error)
        if restoration_errors:
            failure = PdfQuoteRestorationError('; '.join(str(error) for error in restoration_errors))
            raise failure from (active_error or restoration_errors[0])
