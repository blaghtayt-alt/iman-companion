"""Diagnostic only: exact Article 26 marker variants through production LO saves.

This does not create publication receipts, acceptance, or a preparation queue.
The small fixture is conclusive only when its baseline reproduces the split.
"""
from pathlib import Path
from copy import deepcopy
import argparse, base64, hashlib, io, json, shutil, subprocess, sys, zipfile
from lxml import etree
from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
import pymupdf

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
BASE = 'b60f28e3027fb2274e9fc777c92be68f0c78bc06'
FIXTURE_SHA = '7dd022448d514417d0db22c4564cb16b64f1586112882b48a90b2676d5dfc1b1'
VARIANTS = ['prepared-baseline', 'builder-baseline', 'dir', 'bdo', 'dir-nbsp', 'bdo-nbsp', 'rtl-marker']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(file):
    with zipfile.ZipFile(file) as z:
        return {n: z.read(n) for n in z.namelist()}


def save_parts(file, parts):
    with zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in parts.items():
            z.writestr(name, raw)


def literal(parts):
    from reader_xml import body_text
    doc = etree.fromstring(parts['word/document.xml'])
    return body_text(doc.find(W + 'body'))


def notes(parts):
    doc = etree.fromstring(parts['word/document.xml'])
    definitions = {n.get(W + 'id'): ''.join(t.text or '' for t in n.iter(W + 't'))
                   for n in etree.fromstring(parts['word/footnotes.xml'])}
    return [definitions[n.get(W + 'id')] for n in doc.iter(W + 'footnoteReference')]


def trace(parts):
    doc = etree.fromstring(parts['word/document.xml'])
    p = next(doc.find(W + 'body').iter(W + 'p'))
    result = []
    for r in p.iter(W + 'r'):
        text = ''.join(t.text or '' for t in r.iter(W + 't'))
        result.append({'text': text, 'rtl': [n.get(W + 'val') for n in r.findall(W + 'rPr/' + W + 'rtl')],
                       'ancestors': [etree.QName(n).localname for n in r.iterancestors() if n.tag in {W + 'dir', W + 'bdo'}],
                       'footnotes': [n.get(W + 'id') for n in r.iter(W + 'footnoteReference')]})
    return result[-10:]


def variant(source_file, source, name, target):
    from build_books import add_text
    parts = unpack(source_file)
    if name != 'prepared-baseline':
        # Operate on the original XML directly: the reduced fixture deliberately
        # omits unused package media, so loading its relationship graph is not
        # necessary for exercising the production text builder.
        xml = parse_xml(parts['word/document.xml'])
        owner = Document()
        p = Paragraph(xml.find(W + 'body').find(W + 'p'), owner._body)
        anchors = [deepcopy(r) for r in p._p.findall(W + 'r') if r.find(W + 'footnoteReference') is not None]
        assert len(anchors) == 1
        for child in list(p._p):
            if child.tag != W + 'pPr':
                p._p.remove(child)
        for segment in source['segments']:
            add_text(p, segment['text'], 'ar', 'Iman Book Arabic', 'Iman Book Naskh', 12, 'body')
            if segment.get('note'):
                p._p.append(anchors.pop(0))
        marker = next(r for r in p._p.findall(W + 'r') if ''.join(t.text or '' for t in r.iter(W + 't')) == '[١٦]')
        if name.endswith('-nbsp'):
            previous = marker.getprevious()
            text = previous.find(W + 't')
            assert text is not None and (text.text or '').endswith('\u00a0')
            text.text = text.text[:-1]
            value = marker.find(W + 't')
            value.text = '\u00a0' + value.text
            value.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        if name == 'rtl-marker':
            marker.find(W + 'rPr/' + W + 'rtl').set(W + 'val', '1')
        if name.startswith(('dir', 'bdo')):
            container = OxmlElement('w:' + name.split('-')[0])
            container.set(W + 'val', 'ltr')
            position = p._p.index(marker)
            # The marker and its following native anchor retain their exact order.
            for child in list(p._p)[position:]:
                container.append(child)
            p._p.insert(position, container)
        parts['word/document.xml'] = etree.tostring(xml, xml_declaration=True, encoding='UTF-8', standalone=True)
    assert literal(parts) == source['text'], name
    assert notes(parts) == notes(unpack(source_file)), name
    save_parts(target, parts)


def pdf_evidence(file, png_dir):
    doc = pymupdf.open(file)
    png_dir.mkdir(exist_ok=True)
    brackets, digits, lines = [], [], []
    for number, page in enumerate(doc, 1):
        page.get_pixmap(dpi=144, alpha=False).save(png_dir / f'page-{number:04d}.png')
        for span in page.get_texttrace():
            for cp, glyph, origin, bbox in span['chars']:
                if bbox[1] >= 250:
                    continue
                row = {'page': number, 'char': chr(cp), 'origin': list(origin), 'bbox': list(bbox), 'font': span.get('font')}
                if cp in (ord('['), ord(']')):
                    brackets.append(row)
                elif cp in (ord('١'), ord('٦')):
                    digits.append(row)
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            for line in block['lines']:
                if line['bbox'][1] < 250:
                    lines.append({'page': number, 'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])})
    same_line = (len(brackets) == 2 and brackets[0]['page'] == brackets[1]['page']
                 and abs(brackets[0]['origin'][1] - brackets[1]['origin'][1]) < .5)
    contained = []
    if same_line:
        lo = min(b['origin'][0] for b in brackets)
        hi = max(b['origin'][0] for b in brackets)
        contained = [d['char'] for d in digits if d['page'] == brackets[0]['page']
                     and abs(d['origin'][1] - brackets[0]['origin'][1]) < .5 and lo < d['origin'][0] < hi]
    return {'pages': len(doc), 'sha256': sha(file.read_bytes()), 'brackets': brackets,
            'bodyLines': lines, 'markerCompleteSingleLine': same_line and sorted(contained) == sorted('١٦'),
            'splitBracketBaselines': len(brackets) == 2 and not same_line}


def snapshot(file, folder, stage, expected, expected_notes):
    target = folder / stage
    target.mkdir()
    shutil.copy2(file, target / file.name)
    parts = unpack(file)
    raw = parts['word/document.xml']
    (target / 'document.xml').write_bytes(raw)
    result = {'docxSHA256': sha(file.read_bytes()), 'literalBodySHA256': sha(literal(parts).encode()),
              'literalBodyExact': literal(parts) == expected, 'footnoteTextsExact': notes(parts) == expected_notes,
              'runs': trace(parts)}
    pdf = file.with_suffix('.pdf')
    if pdf.exists():
        shutil.copy2(pdf, target / pdf.name)
        result['pdf'] = pdf_evidence(pdf, target / 'pages')
    (target / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--fixture', type=Path, required=True)
    args = ap.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    sys.path.insert(0, str(root / 'books'))
    out.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output(['soffice', '--version'], text=True).strip()
    if '24.2' not in version:
        raise RuntimeError('This diagnostic requires the production LibreOffice 24.2 engine: ' + version)
    archive = base64.b64decode(args.fixture.read_text())
    assert sha(archive) == FIXTURE_SHA
    fixtures = out / 'fixture'
    fixtures.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert set(z.namelist()) == {'source-prepared.docx', 'source.json'}
        for name in z.namelist():
            (fixtures / name).write_bytes(z.read(name))
    source_file = fixtures / 'source-prepared.docx'
    source = json.loads((fixtures / 'source.json').read_text())
    expected_notes = notes(unpack(source_file))
    report = {'schema': 'iman-marker-roundtrip-diagnostic-v1', 'diagnosticOnly': True, 'publicationAcceptance': False,
              'baseCommit': BASE, 'diagnosticCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              'renderer': version, 'fixtureBundleSHA256': FIXTURE_SHA,
              'sourceParagraphSHA256': sha(source['text'].encode()),
              'sourceProjection': '/articles/25/paragraphs/90',
              'note': 'The extracted fixture has no TOC; native-pagination and TOC convergence steps are inapplicable. Both real render_uno saves, font restoration, and final page-break normalization are exercised.',
              'variants': {}}
    for name in VARIANTS:
        work, evidence = out / name / 'work', out / name / 'evidence'
        work.mkdir(parents=True)
        evidence.mkdir()
        file = work / 'Iman_Companion_ar_articles.docx'
        variant(source_file, source, name, file)
        (work / 'index.json').write_text(json.dumps({'diagnosticOnly': True, 'previewOnly': True,
            'books': [{'file': file.name, 'language': 'ar', 'collection': 'articles'}]}))
        row = {'stages': {}}
        report['variants'][name] = row
        row['stages']['before'] = snapshot(file, evidence, 'before', source['text'], expected_notes)
        try:
            commands = [
                ('roundtrip-1', ['/usr/bin/python3', 'books/render_uno.py', '--folder', str(work)]),
                ('roundtrip-2', ['/usr/bin/python3', 'books/render_uno.py', '--folder', str(work), '--keep-contents']),
                ('font-restored', [sys.executable, 'books/restore_book_fonts.py', '--root', str(root), '--folder', str(work)]),
                ('page-break-normalized', [sys.executable, 'books/normalize_word_page_breaks.py', '--folder', str(work)]),
            ]
            for stage, command in commands:
                run = subprocess.run(command, cwd=root, text=True, capture_output=True)
                (evidence / (stage + '.log')).write_text(run.stdout + '\n' + run.stderr)
                if run.returncode:
                    raise RuntimeError(stage + ' failed: ' + run.stderr[-2000:] + run.stdout[-1000:])
                row['stages'][stage] = snapshot(file, evidence, stage, source['text'], expected_notes)
            row['state'] = 'completed'
        except Exception as error:
            row['state'] = 'error'
            row['error'] = str(error)
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'variant': name, 'state': row['state'],
                          'stages': {k: {'literalBodyExact': v['literalBodyExact'],
                                         'markerCompleteSingleLine': v.get('pdf', {}).get('markerCompleteSingleLine'),
                                         'splitBracketBaselines': v.get('pdf', {}).get('splitBracketBaselines')}
                                     for k, v in row['stages'].items()}}, ensure_ascii=False), flush=True)
    baseline = report['variants']['builder-baseline']['stages'].get('roundtrip-2', {})
    alternate = report['variants']['prepared-baseline']['stages'].get('roundtrip-2', {})
    report['baselineReproduced'] = any(b.get('pdf', {}).get('splitBracketBaselines') for b in [baseline, alternate])
    report['candidateVariants'] = [name for name, row in report['variants'].items() if 'baseline' not in name
        and row['state'] == 'completed' and all(s['literalBodyExact'] and s['footnoteTextsExact']
            and s.get('pdf', {'markerCompleteSingleLine': True})['markerCompleteSingleLine'] for s in row['stages'].values())]
    report['conclusion'] = ('Inspect candidate images and expand to whole Articles before implementation.' if report['baselineReproduced']
                            else 'Inconclusive small fixture: render complete Articles through exact production stages.')
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'baselineReproduced': report['baselineReproduced'], 'candidateVariants': report['candidateVariants'],
                      'conclusion': report['conclusion']}), flush=True)


if __name__ == '__main__':
    main()
