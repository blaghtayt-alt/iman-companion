"""Diagnostic only: current A4 references through the current pinned renderer.

No publication queue, acceptance, release assets, or live candidate is modified.
All three exact fixtures reproduced their defects under production LO 24.2.
"""
from pathlib import Path
from copy import deepcopy
import argparse, base64, hashlib, io, json, os, re, shutil, subprocess, sys, zipfile
from lxml import etree
from docx import Document
from docx.oxml import OxmlElement
import pymupdf

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
FIXTURE_SHA = '915f5b01586686cbd442df6abb82d835995f01aec92d4af61c32516f374d76f9'
BASE = '9c4672b8f7137a178f76cb89bd34e50e6c3f4071'
VARIANTS = ['prepared-baseline', 'builder-baseline', 'marker-naskh', 'fit-text', 'fit-text-rtl',
            'quote-field-locked', 'marker-language-en', 'kinsoku-ar', 'kinsoku-en',
            'uno-forbidden-en', 'uno-keep-together']
DIGITS = '0123456789٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹'
# Writer may paint an adjacent sentence period before the closing parenthesis.
# Accept that interleave in the PDF locator, then exclude it from marker geometry.
# The independent literal DOCX comparison remains exact and is not normalized.
MARKER_INNER = r'[0-9\u0660-\u0669\u06f0-\u06f9\s.,،:/–\-]+'
MARKERS = re.compile('|'.join(re.escape(left) + MARKER_INNER + re.escape(right)
                              for left, right in [('[' , ']'), (']', '['), ('(', ')'), (')', '(')]))


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
    return body_text(etree.fromstring(parts['word/document.xml']).find(W + 'body'))


def notes(parts):
    doc = etree.fromstring(parts['word/document.xml'])
    anchors = list(doc.iter(W + 'footnoteReference'))
    if not anchors:
        return []
    definitions = {n.get(W + 'id'): ''.join(t.text or '' for t in n.iter(W + 't'))
                   for n in etree.fromstring(parts['word/footnotes.xml'])}
    return [definitions[n.get(W + 'id')] for n in anchors]


def run_text(node):
    return ''.join(t.text or '' for t in node.iter(W + 't'))


def cut_at(paragraph, offset):
    """Split a plain text run without changing any source character/property."""
    position = 0
    for child in list(paragraph):
        if child.tag == W + 'pPr':
            continue
        value = run_text(child)
        if position == offset:
            return paragraph.index(child)
        if position < offset < position + len(value):
            assert child.tag == W + 'r'
            assert all(c.tag in {W + 'rPr', W + 't'} for c in child)
            texts = child.findall(W + 't')
            assert len(texts) == 1
            where = offset - position
            prefix, suffix = deepcopy(child), deepcopy(child)
            for piece, value_part in [(prefix, value[:where]), (suffix, value[where:])]:
                text = piece.find(W + 't')
                text.text = value_part
                text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            index = paragraph.index(child)
            paragraph.remove(child)
            paragraph.insert(index, prefix)
            paragraph.insert(index + 1, suffix)
            return index + 1
        position += len(value)
        if position == offset:
            return paragraph.index(child) + 1
    assert position == offset
    return len(paragraph)


def marker_nodes(paragraph, marker):
    text = run_text(paragraph)
    assert text.count(marker) == 1
    start = text.index(marker)
    cut_at(paragraph, start + len(marker))
    first = cut_at(paragraph, start)
    last = cut_at(paragraph, start + len(marker))
    nodes = list(paragraph)[first:last]
    assert ''.join(run_text(n) for n in nodes) == marker
    assert all(n.tag == W + 'r' for n in nodes)
    return first, nodes


def set_property(run, name, attributes):
    props = run.find(W + 'rPr')
    if props is None:
        props = OxmlElement('w:rPr')
        run.insert(0, props)
    for old in props.findall(W + name):
        props.remove(old)
    value = OxmlElement('w:' + name)
    for key, text in attributes.items():
        value.set(W + key, str(text))
    props.append(value)


def variant(source_file, case, name, target, width_points):
    from build_books import add_text
    parts = unpack(source_file)
    if name != 'prepared-baseline':
        doc = Document(source_file)
        paragraph = doc.paragraphs[0]
        if name == 'builder-baseline':
            anchors = [deepcopy(r) for r in paragraph._p.findall(W + 'r') if r.find(W + 'footnoteReference') is not None]
            for child in list(paragraph._p):
                if child.tag != W + 'pPr':
                    paragraph._p.remove(child)
            role = {'plain': 'body', 'quran': 'quran', 'hadith': 'hadith', 'scholar': 'scholar'}
            for span in case['segments']:
                add_text(paragraph, span['text'], 'ar', 'Iman Book Arabic', 'Iman Book Naskh', 12, role[span['role']])
                if span.get('note'):
                    paragraph._p.append(anchors.pop(0))
            assert not anchors
        elif not name.startswith('uno-'):
            first, nodes = marker_nodes(paragraph._p, case['marker'])
            if name == 'marker-naskh':
                for run in nodes:
                    set_property(run, 'rFonts', {slot: 'Iman Book Naskh' for slot in ['ascii', 'hAnsi', 'cs', 'eastAsia']})
            elif name.startswith('fit-text'):
                assert width_points and width_points > 0
                for run in nodes:
                    set_property(run, 'fitText', {'id': 901, 'val': round(width_points * 20)})
                    if name.endswith('-rtl'):
                        set_property(run, 'rtl', {'val': '1'})
            elif name == 'quote-field-locked':
                field = OxmlElement('w:fldSimple')
                field.set(W + 'instr', ' QUOTE "' + case['marker'] + '" ')
                field.set(W + 'fldLock', 'true')
                for run in nodes:
                    field.append(run)
                paragraph._p.insert(first, field)
            elif name == 'marker-language-en' or name.startswith('kinsoku-'):
                language = 'ar-SA' if name.endswith('-ar') else 'en-US'
                for run in nodes:
                    set_property(run, 'lang', {'val': language, 'bidi': language, 'eastAsia': language})
                if name.startswith('kinsoku-'):
                    props = paragraph._p.find(W + 'pPr')
                    for old in props.findall(W + 'kinsoku'):
                        props.remove(old)
                    flag = OxmlElement('w:kinsoku')
                    flag.set(W + 'val', '1')
                    props.append(flag)
                    settings = etree.fromstring(parts['word/settings.xml'])
                    for tag, chars in [('noLineBreaksBefore', DIGITS + '])،,'), ('noLineBreaksAfter', '[(' + DIGITS + '،,')]:
                        for old in settings.findall(W + tag):
                            if old.get(W + 'lang') == language:
                                settings.remove(old)
                        etree.SubElement(settings, W + tag, {W + 'lang': language, W + 'val': chars})
                    parts['word/settings.xml'] = etree.tostring(settings, xml_declaration=True, encoding='UTF-8', standalone=True)
        parts['word/document.xml'] = etree.tostring(doc.element, xml_declaration=True, encoding='UTF-8', standalone=True)
    assert literal(parts) == case['text'], name
    assert notes(parts) == notes(unpack(source_file)), name
    save_parts(target, parts)


def trace(parts):
    document = etree.fromstring(parts['word/document.xml'])
    result = []
    for run in document.find(W + 'body').iter(W + 'r'):
        props = run.find(W + 'rPr')
        result.append({'text': run_text(run),
                       'propertiesXML': etree.tostring(props, encoding='unicode') if props is not None else None,
                       'ancestors': [etree.QName(n).localname for n in run.iterancestors() if n.tag in {W + 'dir', W + 'bdo', W + 'fldSimple'}],
                       'footnotes': [n.get(W + 'id') for n in run.iter(W + 'footnoteReference')]})
    return result


def pdf_evidence(file, png_dir, marker):
    pdf = pymupdf.open(file)
    png_dir.mkdir(exist_ok=True)
    target_matches = []
    all_markers = []
    expected_digits = sorted(c for c in marker if c in DIGITS)
    expected_visual_digits = ''.join(c for c in marker if c in DIGITS)
    for number, page in enumerate(pdf, 1):
        page.get_pixmap(dpi=144, alpha=False).save(png_dir / f'page-{number:04d}.png')
        chars = []
        for span in page.get_texttrace():
            if not 11.7 <= span['size'] <= 12.3:
                continue
            for cp, glyph, origin, bbox in span['chars']:
                if not 0 <= cp <= 0x10ffff:
                    continue
                chars.append({'char': chr(cp), 'origin': list(origin), 'bbox': list(bbox), 'font': span.get('font')})
        text = ''.join(c['char'] for c in chars)
        for match in MARKERS.finditer(text):
            painted = chars[match.start():match.end()]
            matched = [c for c in painted if not c['char'].isspace() and c['char'] != '.']
            ys = [c['origin'][1] for c in matched]
            row = {'page': number, 'text': match.group(), 'singleBaseline': max(ys) - min(ys) <= .75,
                   'characters': matched, 'paintOrderInterleaves': [c for c in painted if c['char'] == '.'],
                   'sumAdvanceWidthPoints': sum(c['bbox'][2] - c['bbox'][0] for c in matched)}
            digits = sorted((c for c in matched if c['char'] in DIGITS), key=lambda c: c['origin'][0])
            ends = sorted(c['origin'][0] for c in matched if c['char'] in '[]()')
            row['digitsInVisualOrder'] = ''.join(c['char'] for c in digits)
            row['digitsEnclosed'] = len(ends) == 2 and bool(digits) and all(ends[0] < c['origin'][0] < ends[1] for c in digits)
            all_markers.append(row)
            if match.group()[0] in {marker[0], marker[-1]} and sorted(c for c in match.group() if c in DIGITS) == expected_digits:
                target_matches.append(row)
    complete = len(target_matches) == 1 and target_matches[0]['singleBaseline'] and target_matches[0]['digitsEnclosed'] and target_matches[0]['digitsInVisualOrder'] == expected_visual_digits
    return {'pages': len(pdf), 'sha256': sha(file.read_bytes()), 'targetMatches': target_matches,
            'allBodyNumericMarkers': all_markers, 'markerCompleteSingleLine': complete,
            'splitTargetBaselines': len(target_matches) == 1 and not target_matches[0]['singleBaseline']}


def snapshot(file, folder, stage, case, expected_notes):
    target = folder / stage
    target.mkdir()
    parts = unpack(file)
    for name in ['document.xml', 'settings.xml']:
        (target / name).write_bytes(parts['word/' + name])
    # Work retains the exact final DOCX. Avoid duplicating embedded font payloads
    # at every diagnostic stage, while recording every stage's exact file hash.
    result = {'docxSHA256': sha(file.read_bytes()), 'literalBodySHA256': sha(literal(parts).encode()),
              'literalBodyExact': literal(parts) == case['text'], 'footnoteTextsExact': notes(parts) == expected_notes,
              'runs': trace(parts)}
    pdf = file.with_suffix('.pdf')
    if pdf.exists():
        shutil.copy2(pdf, target / pdf.name)
        result['pdf'] = pdf_evidence(pdf, target / 'pages', case['marker'])
    (target / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def hooked_renderer(root, folder, case, mode):
    template = (root / 'books/render_uno.py').read_text()
    needle = '                    native_footer(doc,languages[file.name])'
    assert template.count(needle) == 1
    hook = '''
def diagnostic_marker_properties(doc):
    mode = MODE_VALUE
    marker = MARKER_VALUE
    descriptor = doc.createSearchDescriptor()
    descriptor.SearchString = marker
    descriptor.SearchRegularExpression = False
    ranges = doc.findAll(descriptor)
    report = []
    if mode == 'uno-forbidden-en':
        settings = doc.createInstance('com.sun.star.document.Settings')
        table = settings.getPropertyValue('ForbiddenCharacters')
        locale = uno.createUnoStruct('com.sun.star.lang.Locale')
        locale.Language, locale.Country = 'en', 'US'
        rules = uno.createUnoStruct('com.sun.star.i18n.ForbiddenCharacters')
        rules.beginLine = '0123456789٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹])،,'
        rules.endLine = '[(0123456789٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹،,'
        table.setForbiddenCharacters(locale, rules)
    for index in range(ranges.getCount()):
        found = ranges.getByIndex(index)
        info = found.getPropertySetInfo()
        if mode == 'uno-keep-together':
            available = info.hasPropertyByName('CharKeepTogether')
            if not available:
                raise RuntimeError('Writer range does not implement CharKeepTogether')
            found.setPropertyValue('CharKeepTogether', True)
            report.append({'text': found.String, 'CharKeepTogether': found.getPropertyValue('CharKeepTogether')})
        else:
            for name in ['CharLocale', 'CharLocaleComplex', 'CharLocaleAsian']:
                if info.hasPropertyByName(name):
                    found.setPropertyValue(name, locale)
            cursor = found.getText().createTextCursorByRange(found)
            cursor.gotoStartOfParagraph(False)
            cursor.gotoEndOfParagraph(True)
            cursor.ParaIsForbiddenRules = True
            report.append({'text': found.String, 'forbiddenRules': True})
    print('DIAGNOSTIC MARKER PROPERTIES ' + json.dumps(report, ensure_ascii=False), flush=True)

'''.replace('MODE_VALUE', repr(mode)).replace('MARKER_VALUE', repr(case['marker']))
    file = folder / 'diagnostic_render.py'
    file.write_text(template.replace('def main():', hook + 'def main():').replace(needle,
        '                    diagnostic_marker_properties(doc)\n' + needle))
    return str(file)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--fixture', type=Path, required=True)
    ap.add_argument('--expected-renderer', default='26.2.5.2')
    ap.add_argument('--variants', default=','.join(VARIANTS))
    ap.add_argument('--require-complete', action='store_true')
    args = ap.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    sys.path.insert(0, str(root / 'books'))
    from renderer_pin import verify_packages
    packages = verify_packages()
    out.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output(['soffice', '--version'], text=True).strip()
    if args.expected_renderer not in version:
        raise RuntimeError('Unexpected diagnostic renderer: ' + version)
    variants = args.variants.split(',')
    assert len(variants) == len(set(variants)) and set(variants) <= set(VARIANTS)
    assert variants[:2] == ['prepared-baseline', 'builder-baseline']
    data = base64.b64decode(args.fixture.read_text())
    assert sha(data) == FIXTURE_SHA
    fixtures = out / 'fixture'
    fixtures.mkdir()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            assert '/' not in name and '..' not in name
            (fixtures / name).write_bytes(z.read(name))
    source = json.loads((fixtures / 'manifest.json').read_text())
    report = {'schema': 'iman-a4-marker-roundtrip-diagnostic-v1', 'diagnosticOnly': True,
              'publicationAcceptance': False, 'baseCommit': BASE,
              'diagnosticCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              'renderer': version, 'rendererPackages': packages, 'expectedRenderer': args.expected_renderer,
              'fontconfigFile': os.environ.get('FONTCONFIG_FILE'),
              'fontconfigSHA256': sha(Path(os.environ['FONTCONFIG_FILE']).read_bytes()) if os.environ.get('FONTCONFIG_FILE') else None,
              'fixtureBundleSHA256': FIXTURE_SHA, 'source': source,
              'note': 'Exact current A4 paragraph fixtures, without TOC. Both actual production render_uno saves, font restoration, and page-break normalization run. UNO-only variants explicitly record their diagnostic hook.',
              'cases': {}}
    for case in source['cases']:
        source_file = fixtures / (case['id'] + '.docx')
        assert sha(source_file.read_bytes()) == case['fixtureDocxSHA256']
        expected_notes = notes(unpack(source_file))
        rows = report['cases'][case['id']] = {'variants': {}}
        width_points = None
        for name in variants:
            directory = out / case['id'] / name
            work, evidence = directory / 'work', directory / 'evidence'
            work.mkdir(parents=True)
            evidence.mkdir()
            file = work / 'Iman_Companion_ar_articles.docx'
            row = {'stages': {}}
            rows['variants'][name] = row
            try:
                variant(source_file, case, name, file, width_points)
                (work / 'index.json').write_text(json.dumps({'diagnosticOnly': True, 'previewOnly': True,
                    'books': [{'file': file.name, 'language': 'ar', 'collection': 'articles'}]}))
                row['stages']['before'] = snapshot(file, evidence, 'before', case, expected_notes)
                renderer = hooked_renderer(root, directory, case, name) if name.startswith('uno-') else 'books/render_uno.py'
                commands = [
                    ('roundtrip-1', ['/usr/bin/python3', renderer, '--folder', str(work)]),
                    ('roundtrip-2', ['/usr/bin/python3', renderer, '--folder', str(work), '--keep-contents']),
                    ('font-restored', [sys.executable, 'books/restore_book_fonts.py', '--root', str(root), '--folder', str(work)]),
                    ('page-break-normalized', [sys.executable, 'books/normalize_word_page_breaks.py', '--folder', str(work)]),
                ]
                for stage, command in commands:
                    run = subprocess.run(command, cwd=root, text=True, capture_output=True)
                    (evidence / (stage + '.log')).write_text(run.stdout + '\n' + run.stderr)
                    if run.returncode:
                        raise RuntimeError(stage + ' failed: ' + run.stderr[-2200:] + run.stdout[-1200:])
                    row['stages'][stage] = snapshot(file, evidence, stage, case, expected_notes)
                row['state'] = 'completed'
                if name == 'prepared-baseline':
                    matched = row['stages']['roundtrip-2']['pdf']['targetMatches']
                    if len(matched) == 1:
                        width_points = matched[0]['sumAdvanceWidthPoints']
            except Exception as error:
                row['state'] = 'error'
                row['error'] = str(error)
            (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({'case': case['id'], 'variant': name, 'state': row['state'], 'error': row.get('error'),
                'stages': {k: {'literalBodyExact': v['literalBodyExact'], 'footnotesExact': v['footnoteTextsExact'],
                               'markerCompleteSingleLine': v.get('pdf', {}).get('markerCompleteSingleLine'),
                               'splitTargetBaselines': v.get('pdf', {}).get('splitTargetBaselines')}
                           for k, v in row['stages'].items()}}, ensure_ascii=False), flush=True)
        rows['baselineReproduced'] = any(rows['variants'][name]['stages'].get('roundtrip-2', {}).get('pdf', {}).get('splitTargetBaselines')
                                        for name in ['prepared-baseline', 'builder-baseline'])
        rows['candidates'] = [name for name, row in rows['variants'].items() if 'baseline' not in name and row['state'] == 'completed'
            and all(s['literalBodyExact'] and s['footnoteTextsExact'] and s.get('pdf', {'markerCompleteSingleLine': True})['markerCompleteSingleLine']
                    for s in row['stages'].values())]
        print(json.dumps({'case': case['id'], 'baselineReproduced': rows['baselineReproduced'], 'candidates': rows['candidates']}), flush=True)
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report['allBaselinesReproduced'] = all(row['baselineReproduced'] for row in report['cases'].values())
    report['commonCandidates'] = sorted(set.intersection(*(set(row['candidates']) for row in report['cases'].values())))
    failures = [case_id + '/' + name for case_id, case in report['cases'].items()
                for name, variant_row in case['variants'].items()
                if variant_row['state'] != 'completed' or not all(stage['literalBodyExact'] and stage['footnoteTextsExact']
                   and stage.get('pdf', {'markerCompleteSingleLine': True})['markerCompleteSingleLine']
                   for stage in variant_row['stages'].values())]
    report['allSelectedVariantsComplete'] = not failures
    report['failures'] = failures
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'allBaselinesReproduced': report['allBaselinesReproduced'], 'commonCandidates': report['commonCandidates']}), flush=True)
    print(json.dumps({'allSelectedVariantsComplete': not failures, 'failures': failures}), flush=True)
    if args.require_complete and failures:
        raise ValueError('Current renderer failed exact A4 citation diagnostics: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
