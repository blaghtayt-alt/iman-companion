"""Exercise complete reviewed books through the pinned preparation sequence.

This read-only CI regression creates diagnostic books only. It does not call
the publication controller, write a preparation queue, or create acceptance.
The negative control disables only optional TOC tooltip omission on an exact
isolated copy, and must reproduce the pinned renderer's cached-link loss.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

from lxml import etree
import pypdfium2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from check_contents_targets import check as check_targets
from reader_xml import body_text
from renderer_pin import verify_packages
from toc_sync import linked_pages, reconcile
from word_layout_check import contents

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SCOPES = [('en', 'hadith'), ('ar', 'seerah'), ('th', 'hadith'), ('ur', 'hadith'), ('bn', 'tadabbur-extended'), ('uz', 'hadith')]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unpack(file):
    with zipfile.ZipFile(file) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def toc_paragraph(paragraph):
    style = paragraph.find(W + 'pPr/' + W + 'pStyle')
    return style is not None and style.get(W + 'val') in {'TOC1', 'TOC2', 'TOC 1', 'TOC 2'}


def document_evidence(file):
    parts = unpack(file)
    root = etree.fromstring(parts['word/document.xml'])
    rows = contents(root)  # Missing, duplicate, or nonexistent anchors stay fatal.
    titles = [body_text(paragraph).rsplit('\t', 1)[0]
              for paragraph in root.iter(W + 'p') if toc_paragraph(paragraph)]
    body = deepcopy(root.find(W + 'body'))
    for paragraph in list(body.iter(W + 'p')):
        if toc_paragraph(paragraph):
            paragraph.getparent().remove(paragraph)
    literal = body_text(body)
    notes = {}
    if 'word/footnotes.xml' in parts:
        notes = {note.get(W + 'id'): body_text(note)
                 for note in etree.fromstring(parts['word/footnotes.xml'])}
    ordered_notes = [notes[ref.get(W + 'id')] for ref in root.iter(W + 'footnoteReference')]
    links = [link for paragraph in root.iter(W + 'p') if toc_paragraph(paragraph)
             for link in paragraph.iter(W + 'hyperlink')]
    return {'docxSHA256': digest(file.read_bytes()), 'contents': rows, 'contentsTitles': titles,
            'literalBodySHA256': digest(literal.encode()),
            'orderedNotesSHA256': digest(json.dumps(ordered_notes, ensure_ascii=False).encode()),
            'noteCount': len(ordered_notes), 'tooltipLinks': sum(W + 'tooltip' in link.attrib for link in links)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'diagnosticOnly': True, 'publicationAcceptance': False,
              'renderer': verify_packages(), 'scopes': {}, 'passed': False}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    report['sourceCommit'] = commit
    manifest = root / 'books/manifest.json'
    original_manifest = manifest.read_bytes() if manifest.exists() else None

    def save():
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

    def run(command, log):
        result = subprocess.run([str(item) for item in command], cwd=root, capture_output=True, text=True)
        log.write_text(result.stdout + '\n' + result.stderr, encoding='utf8')
        if result.returncode:
            raise RuntimeError(log.name + ': ' + result.stderr[-2000:] + result.stdout[-1000:])

    try:
        for language, collection in SCOPES:
            key = language + '-' + collection
            folder = out / key
            folder.mkdir()
            book_folder = folder / 'book'
            row = {'stages': {}}
            report['scopes'][key] = row
            commands = [
                ('index', [sys.executable, 'books/index_units.py', '--root', root, '--commit', commit,
                           '--language', language, '--collection', collection]),
                ('build', [sys.executable, 'books/build_books.py', '--root', root, '--out', book_folder, '--commit', commit]),
                ('roundtrip-1', ['/usr/bin/python3', 'books/render_uno.py', '--folder', book_folder]),
            ]
            for stage, command in commands:
                run(command, folder / (stage + '.log'))
            index = json.loads((book_folder / 'index.json').read_bytes())
            if len(index['books']) != 1:
                raise ValueError('Renderer regression scope produced multiple books')
            file = book_folder / index['books'][0]['file']
            pdf = file.with_suffix('.pdf')
            original = document_evidence(file)

            def snapshot(stage):
                actual = document_evidence(file)
                for field in ('literalBodySHA256', 'orderedNotesSHA256', 'contentsTitles'):
                    if actual[field] != original[field]:
                        raise ValueError(key + '/' + stage + ': literal text or notes changed')
                if [item['anchor'] for item in actual['contents']] != [item['anchor'] for item in original['contents']]:
                    raise ValueError(key + '/' + stage + ': contents target anchors changed')
                actual['pdfSHA256'] = digest(pdf.read_bytes())
                actual['pdfTargetPages'] = linked_pages(pdf, len(actual['contents']))
                destination = folder / stage
                destination.mkdir()
                shutil.copy2(file, destination / file.name)
                shutil.copy2(pdf, destination / pdf.name)
                row['stages'][stage] = actual
                save()

            snapshot('roundtrip-1')
            if language == 'en':
                if not original['tooltipLinks']:
                    raise ValueError('The negative control has no optional TOC tooltip to reproduce the import bug')
                control = out / 'negative-control'
                control.mkdir()
                control_file = control / file.name
                shutil.copy2(file, control_file)
                control_index = deepcopy(index)
                control_index.update(diagnosticOnly=True, previewOnly=True)
                (control / 'index.json').write_text(json.dumps(control_index), encoding='utf8')
                driver = out / 'negative-control-import.py'
                driver.write_text('import sys\nsys.path.insert(0, ' + repr(str(root / 'books')) + ')\n'
                                  'import render_uno\n'
                                  'render_uno.normalize_toc_hyperlinks = lambda file: 0\n'
                                  'render_uno.main()\n', encoding='utf8')
                run(['/usr/bin/python3', driver, '--folder', control, '--keep-contents'], out / 'negative-control.log')
                rejected = None
                with zipfile.ZipFile(control_file) as archive:
                    control_root = etree.fromstring(archive.read('word/document.xml'))
                counts = [len(list(paragraph.iter(W + 'hyperlink')))
                          for paragraph in control_root.iter(W + 'p') if toc_paragraph(paragraph)]
                try:
                    contents(control_root)
                except ValueError as error:
                    rejected = str(error)
                report['negativeControl'] = {'disabled': 'optional-contents-tooltip-omission',
                                             'inputDocxSHA256': original['docxSHA256'],
                                             'inputTooltipLinks': original['tooltipLinks'],
                                             'outputLinksPerEntry': counts,
                                             'missingLinksRejected': rejected,
                                             'docxSHA256': digest(control_file.read_bytes()),
                                             'pdfSHA256': digest(control_file.with_suffix('.pdf').read_bytes())}
                if not rejected or counts != [0] * len(original['contents']):
                    raise ValueError('Pinned renderer did not reproduce the TOC-tooltip import failure')
                save()

            run([sys.executable, 'books/native_pagination.py', '--root', root, '--folder', book_folder], folder / 'native-pagination.log')
            run(['/usr/bin/python3', 'books/render_uno.py', '--folder', book_folder, '--keep-contents'], folder / 'roundtrip-2.log')
            snapshot('roundtrip-2')
            for attempt in range(4):
                result = reconcile(file, pdf, language)
                if not result['mismatches']:
                    break
                run([sys.executable, 'books/toc_sync.py', '--folder', book_folder, '--write'], folder / f'toc-reconcile-{attempt}.log')
                run(['/usr/bin/python3', 'books/render_uno.py', '--folder', book_folder, '--keep-contents'], folder / f'toc-render-{attempt}.log')
            run([sys.executable, 'books/toc_sync.py', '--folder', book_folder], folder / 'toc-final.log')
            snapshot('contents-converged')
            run([sys.executable, 'books/restore_book_fonts.py', '--root', root, '--folder', book_folder], folder / 'font-restored.log')
            snapshot('font-restored')
            run([sys.executable, 'books/normalize_word_page_breaks.py', '--folder', book_folder], folder / 'page-break-normalized.log')
            snapshot('page-break-normalized')
            run([sys.executable, 'books/check_outputs.py', '--root', root, '--folder', book_folder,
                 '--tag', 'diagnostic-renderer-contents', '--repo', 'blaghtayt-alt/iman-companion', '--prepare-only'], folder / 'check-outputs.log')
            row['contentsTargets'] = check_targets(file, pdf)
            row['fullPreparationChecksPassed'] = True
            final_index = json.loads((book_folder / 'index.json').read_bytes())
            row['pages'] = final_index['books'][0]['pages']
            row['audioQRVerification'] = final_index['books'][0]['audioQRVerification']
            visuals = folder / 'final-pages'
            visuals.mkdir()
            document = pypdfium2.PdfDocument(pdf)
            for number in range(min(3, len(document))):
                document[number].render(scale=2).to_pil().save(visuals / f'page-{number + 1:04d}.png')
            document.close()
            save()
        report['passed'] = True
        save()
        print(json.dumps({'passed': True, 'scopes': list(report['scopes']), 'renderer': report['renderer']}))
    except Exception as error:
        report['error'] = str(error)
        save()
        raise
    finally:
        if original_manifest is None:
            manifest.unlink(missing_ok=True)
        else:
            manifest.write_bytes(original_manifest)


if __name__ == '__main__':
    main()
