"""Prove native TOC links and exact caches survive repeated renderer saves.

Optional baseline input records the old renderer's first/keep-pass behavior.
Only the current renderer must pass; no checker or candidate gate is bypassed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.shared import Mm, Pt
from lxml import etree
from pypdf import PdfReader

BOOKS = Path(__file__).resolve().parents[1] / 'books'
sys.path.insert(0, str(BOOKS))
from native_pagination import native_toc
from toc_sync import linked_pages, toc_nodes

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
TOC = {'TOC1', 'TOC2', 'TOC 1', 'TOC 2'}


def tag(name):
    return '{' + W + '}' + name


def read_parts(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def style(paragraph):
    node = paragraph.find('./' + tag('pPr') + '/' + tag('pStyle'))
    return node.get(tag('val')) if node is not None else None


def reader_text(path):
    parts = read_parts(path)
    body = etree.fromstring(parts['word/document.xml'])
    paragraphs = [''.join(t.text or '' for t in p.iter(tag('t')))
                  for p in body.iter(tag('p')) if style(p) not in TOC]
    notes = etree.fromstring(parts['word/footnotes.xml'])
    anchors = [n.get(tag('id')) for n in body.iter(tag('footnoteReference'))]
    definitions = {}
    for note in notes:
        role = note.get(tag('type'), 'normal')
        if role in {'separator', 'continuationSeparator', 'continuationNotice'}:
            continue
        ident = note.get(tag('id'))
        if role != 'normal' or ident is None or ident in definitions:
            raise ValueError('Invalid or duplicate normal footnote definition')
        definitions[ident] = note
    if set(anchors) != set(definitions):
        raise ValueError('Missing or orphan normal footnote definition')
    return {'body': [p for p in paragraphs if p.strip()],
            'footnotes': [''.join(t.text or '' for t in definitions[ident].iter(tag('t')))
                          for ident in anchors]}


def make_fixture(folder, language):
    folder.mkdir(parents=True, exist_ok=True)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(18)
    section.left_margin = section.right_margin = Mm(18)
    for name in ('TOC 1', 'TOC 2'):
        if name not in document.styles:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    for item in document.styles:
        if item.type == WD_STYLE_TYPE.PARAGRAPH:
            family = 'Iman Book Arabic' if language == 'ar' else 'Iman Book Inter'
            item.font.name = family
            item.font.size = Pt(14)
            fonts = item.element.get_or_add_rPr().find(qn('w:rFonts'))
            for name in list(fonts.attrib):
                if name.endswith('Theme'): del fonts.attrib[name]
            for name in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
                fonts.set(qn('w:' + name), family)
    title = document.styles.add_style('FixtureContentsTitle', WD_STYLE_TYPE.PARAGRAPH)
    outline = OxmlElement('w:outlineLvl'); outline.set(qn('w:val'), '9')
    title.element.get_or_add_pPr().append(outline)
    document.add_paragraph('المحتويات' if language == 'ar' else 'Contents', style=title)
    paragraph = document.add_paragraph()
    for kind, value in (('fldChar', 'begin'), ('instrText', ' TOC \\o "1-2" \\h \\z \\u '),
                        ('fldChar', 'separate'), ('t', ' '), ('fldChar', 'end')):
        node = OxmlElement('w:' + kind)
        if kind == 'fldChar': node.set(qn('w:fldCharType'), value)
        else: node.text = value
        paragraph.add_run()._r.append(node)
    headings = ('الفصل الأول', 'حديث واحد', 'الفصل الثاني') if language == 'ar' else (
        'First chapter', 'First lesson', 'Second chapter')
    body_text = 'نص ثابت لا يتغير مع التحديث [١٠].' if language == 'ar' else 'Exact source body [10].'
    for i, heading in enumerate(headings):
        p = document.add_paragraph(heading, style='Heading 2' if i == 1 else 'Heading 1')
        p.paragraph_format.page_break_before = True
        p = document.add_paragraph(body_text)
        if i == 0:
            reference = OxmlElement('w:footnoteReference'); reference.set(qn('w:id'), '2')
            p.add_run()._r.append(reference)
    notes = etree.Element(tag('footnotes'), nsmap={'w': W})
    for ident, kind in ((-1, 'separator'), (0, 'continuationSeparator')):
        note = etree.SubElement(notes, tag('footnote'), {tag('id'): str(ident), tag('type'): kind})
        etree.SubElement(etree.SubElement(etree.SubElement(note, tag('p')), tag('r')), tag(kind))
    note = etree.SubElement(notes, tag('footnote'), {tag('id'): '2'})
    p = etree.SubElement(note, tag('p'))
    etree.SubElement(etree.SubElement(p, tag('r')), tag('footnoteRef'))
    note_run = etree.SubElement(p, tag('r'))
    fonts = etree.SubElement(etree.SubElement(note_run, tag('rPr')), tag('rFonts'))
    for name in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
        fonts.set(tag(name), 'Iman Book Naskh')
    etree.SubElement(note_run, tag('t')).text = 'Exact native footnote — حاشية كاملة [١٠].'
    part = Part(PackURI('/word/footnotes.xml'), CONTENT_TYPE.WML_FOOTNOTES,
                etree.tostring(notes, xml_declaration=True, encoding='UTF-8', standalone=True),
                document.part.package)
    document.part.relate_to(part, RELATIONSHIP_TYPE.FOOTNOTES)
    path = folder / ('toc-' + language + '.docx')
    document.save(path)
    (folder / 'index.json').write_text(json.dumps({'books': [{'file': path.name,
        'language': language, 'collection': 'hadith'}]}) + '\n', encoding='utf-8')
    return path


def inspect(path):
    parts = read_parts(path)
    root = etree.fromstring(parts['word/document.xml'])
    rows = [p for p in root.iter(tag('p')) if style(p) in TOC]
    bookmarks = {n.get(tag('name')) for n in root.iter(tag('bookmarkStart'))}
    result = {'docxSHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'pdfSHA256': hashlib.sha256(path.with_suffix('.pdf').read_bytes()).hexdigest(),
              'entries': len(rows), 'linksPerEntry': [len(p.findall('.//' + tag('hyperlink'))) for p in rows],
              'pdfPages': len(PdfReader(path.with_suffix('.pdf')).pages)}
    try:
        nodes = toc_nodes(root)
        for p in rows:
            link = p.find('.//' + tag('hyperlink'))
            if link.get(tag('anchor')) not in bookmarks or len(link.attrib) == 0:
                raise ValueError('TOC hyperlink has no existing internal bookmark')
            if any(etree.QName(k).localname == 'id' for k in link.attrib):
                raise ValueError('TOC hyperlink unexpectedly uses an external relationship')
        result['labels'] = [n.text.strip() for n in nodes]
        result['anchors'] = [p.find('.//' + tag('hyperlink')).get(tag('anchor')) for p in rows]
        result['pdfDestinations'] = linked_pages(path.with_suffix('.pdf'), len(rows))
        if [int(n) for n in result['labels']] != result['pdfDestinations']:
            raise ValueError('TOC cached labels differ from actual PDF destinations')
    except ValueError as error:
        result['validationError'] = str(error)
    return result


def cached_labels(path):
    """Read exact numeric caches even when the baseline importer lost links."""
    xml = etree.fromstring(read_parts(path)['word/document.xml'])
    result = []
    for paragraph in xml.iter(tag('p')):
        if style(paragraph) not in TOC:
            continue
        nodes = list(paragraph.iter())
        tabs = [i for i, node in enumerate(nodes) if node.tag == tag('tab')]
        assert tabs, 'Contents entry has no tab'
        values = [node.text for node in nodes[tabs[-1] + 1:]
                  if node.tag == tag('t') and (node.text or '').strip()]
        assert len(values) == 1 and values[0].isdecimal(), values
        result.append(values[0])
    assert len(result) == 3, result
    return result


def set_diagnostic_caches(path, labels):
    """Deliberately wrong caches test keep semantics; never publication input."""
    parts = read_parts(path)
    xml = etree.fromstring(parts['word/document.xml'])
    nodes = toc_nodes(xml)
    assert len(nodes) == len(labels) == 3
    for node, label in zip(nodes, labels):
        assert label.isdecimal() and int(label) > 4
        node.text = label
    parts['word/document.xml'] = etree.tostring(
        xml, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)


def exercise(root, out, renderer, language, required):
    file = make_fixture(out / 'input', language)
    original = reader_text(file)
    result = {'language': language, 'rendererSHA256': hashlib.sha256(renderer.read_bytes()).hexdigest()}
    environment = dict(os.environ, PYTHONPATH=str(root / 'books'))
    original_anchors = None

    def render_phase(phase, flags, expected_labels=None, intentional_mismatch=False):
        subprocess.run(['/usr/bin/python3', str(renderer), '--folder', str(file.parent), *flags],
                       cwd=root, env=environment, check=True)
        state = inspect(file)
        state['readerTextPreserved'] = reader_text(file) == original
        if expected_labels is not None:
            state['cachedLabelsPreserved'] = state.get('labels') == expected_labels
        if intentional_mismatch:
            state['intentionalDiagnosticCacheMismatch'] = True
        result[phase] = state
        (out / (phase + '.json')).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        snapshot = out / phase
        snapshot.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, snapshot / file.name)
        shutil.copy2(file.with_suffix('.pdf'), snapshot / file.with_suffix('.pdf').name)
        if required:
            assert state['entries'] == 3 and state['linksPerEntry'] == [1, 1, 1], state
            assert state.get('pdfDestinations') == [2, 3, 4], 'Links do not follow known heading pages'
            assert state['readerTextPreserved'], 'Body/footnote reader text changed'
            if original_anchors is not None:
                assert state['anchors'] == original_anchors, 'Native link target identity changed'
            if expected_labels is not None:
                assert state['cachedLabelsPreserved'], 'Keep-contents changed exact cached page labels'
            if intentional_mismatch:
                assert state.get('validationError') == 'TOC cached labels differ from actual PDF destinations', state
            else:
                assert 'validationError' not in state, state
        return state

    first = render_phase('first-pass', [])
    original_anchors = first.get('anchors')
    if language == 'ar':
        native_toc(file, file, language, 'Iman Book Naskh')
    expected = cached_labels(file)
    if language == 'ar':
        assert all(all(c in '٠١٢٣٤٥٦٧٨٩' for c in label) for label in expected), expected
    render_phase('keep-contents', ['--keep-contents'], expected)
    if not required:
        return result
    render_phase('repeat-keep-contents', ['--keep-contents'], expected)

    # Values intentionally differ from regenerated page numbers. This proves
    # that keep preserves exact caches instead of merely transliterating them.
    distinct = ['٢١', '٣١', '٤١'] if language == 'ar' else ['21', '31', '41']
    set_diagnostic_caches(file, distinct)
    render_phase('distinct-cache-keep', ['--keep-contents'], distinct, True)
    render_phase('distinct-cache-repeat', ['--keep-contents'], distinct, True)

    # Exercise the actual production reconciliation command, then require a
    # fully valid final DOCX/PDF pair again after another native keep save.
    sync = subprocess.run([sys.executable, str(root / 'books/toc_sync.py'),
                           '--folder', str(file.parent), '--write'],
                          cwd=root, env=environment, check=True, text=True, capture_output=True)
    reconciled = json.loads(sync.stdout)
    assert len(reconciled) == 1 and reconciled[0]['entries'] == 3 and reconciled[0]['mismatches'] == 3, reconciled
    result['tocSyncWrite'] = reconciled
    (out / 'toc-sync-write.json').write_text(
        json.dumps(reconciled, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert cached_labels(file) == expected, 'Production reconciliation did not restore exact expected labels'
    render_phase('reconciled-keep', ['--keep-contents'], expected)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-renderer', type=Path)
    parser.add_argument('--fixtures-only', action='store_true')
    args = parser.parse_args(); root, out = args.root.resolve(), args.out.resolve()
    report = {'schema': 'iman-renderer-toc-regression-v1', 'publicationAcceptance': False, 'cases': []}
    if args.fixtures_only:
        for language in ('ar', 'en'):
            path = make_fixture(out / language, language)
            report['cases'].append({'language': language, 'readerText': reader_text(path)})
    else:
        if args.baseline_renderer:
            for language in ('ar', 'en'):
                report['cases'].append({'mode': 'baseline', **exercise(root, out / ('baseline-' + language),
                    args.baseline_renderer.resolve(), language, False)})
        for language in ('ar', 'en'):
            report['cases'].append({'mode': 'current', **exercise(root, out / ('current-' + language),
                root / 'books/render_uno.py', language, True)})
    out.mkdir(parents=True, exist_ok=True)
    (out / 'toc-regression.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
