"""Turn an exact prepared pair into a checked release candidate, never an approval.

``plan`` binds the immutable preparation to the current scoped inputs. On an
owned Windows desktop, copy the preparation and run ``finalize_word.py`` on the
copy. Inspect both final formats, then supply an explicit, hash-bound visual
acceptance. ``finalize`` verifies that evidence and stages the candidate for the
existing publisher. It neither runs Word on Linux nor publishes a release.
"""
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
from zipfile import ZipFile
from datetime import datetime, timezone
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys

from lxml import etree
from published_library import (asset_names, capture, declaration, inside, read,
                               scope_catalog, scope_key, scope_settings, sha)
from preparation_queue import load as load_queue, signature
from check_outputs import require_complete_references
from word_layout_check import verify as verify_word, W

HANDOFF_SCHEMA = 'iman-prepared-book-handoff-v1'
ACCEPTANCE_SCHEMA = 'iman-book-visual-acceptance-v1'
FINAL_SCHEMA = 'iman-finalized-book-candidate-v1'
PROOF = 'word-proof/Word-visual-proof.pdf'
KNOWN_CHECKS = {'scope-release-hold', 'source-references',
                'actual-word-layout', 'final-visual-inspection'}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode('utf8')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def evidence_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate field in review evidence: ' + key)
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('Review evidence must be a JSON object')
    return value


def checked_file(folder, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe candidate file path: ' + str(relative))
    folder = folder.resolve()
    path = folder / relative
    current = path
    while current != folder:
        if current.is_symlink():
            raise ValueError('Candidate files must not be symbolic links: ' + str(relative))
        current = current.parent
    if not path.is_file() or not path.resolve().is_relative_to(folder):
        raise ValueError('Missing candidate file: ' + str(relative))
    return path


def file_hash(folder, name):
    return sha(checked_file(folder, name).read_bytes())


def execute(args, root):
    result = subprocess.run([str(x) for x in args], cwd=root, capture_output=True,
                            text=True, encoding='utf8')
    if result.returncode:
        raise ValueError('Finalization check failed: ' + ' '.join(map(str, args[:2]))
                         + '\n' + result.stderr[-3500:] + '\n' + result.stdout[-1000:])
    return result.stdout


def git_head(root):
    return execute(['git', 'rev-parse', 'HEAD'], root).strip()


def _prepared(root, folder):
    index = read(checked_file(folder, 'index.json'))
    if index.get('previewOnly') is not False or len(index.get('books', [])) != 1:
        raise ValueError('Handoff requires one production prepared book')
    book = index['books'][0]
    key = scope_key(book)
    names = asset_names(book)
    if book.get('preparationVerified') is not True or book.get('exportVerified') is not False:
        raise ValueError('Use the immutable preparation, not a modified or released index')
    if book.get('previewOnly') is not False:
        raise ValueError('Preview books cannot be finalized for release')
    matches = [r for r in load_queue(root)['entries'] if scope_key(r) == key]
    if len(matches) != 1:
        raise ValueError('No unique current preparation queue entry for this scope')
    queued = matches[0]
    if queued.get('state') != 'prepared-awaiting-release-qc' or queued.get('releaseVerified') is not False:
        raise ValueError('Preparation is superseded or no longer awaiting release checks')
    if queued.get('inputFingerprint') != signature(root, key):
        raise ValueError('Preparation inputs changed; rebuild this scope before finalization')
    commit = queued.get('sourceCommit', '')
    if not re.fullmatch('[a-f0-9]{40}', commit) or index.get('sourceCommit') != commit or book.get('sourceCommit') != commit:
        raise ValueError('Prepared source commit identity differs')
    if queued.get('candidate', {}).get('book') != book:
        raise ValueError('Prepared index differs from the trusted preparation queue')
    snapshot = queued['candidate']['snapshot']
    if (snapshot.get('catalogSHA256') != scope_catalog(root, key, for_release=False)
            or snapshot.get('scopeSettingsSHA256') != scope_settings(root, key, snapshot['unitIds'])
            or not snapshot.get('bindings')
            or any(sha(inside(root, b['path']).read_bytes()) != b['sha256'] for b in snapshot['bindings'])):
        raise ValueError('Prepared source, approval, or settings bindings are stale')
    stored = read(checked_file(folder, 'prepared-snapshot.json'))
    if stored.get('entries') != [queued] or stored.get('schema') != 'iman-book-preparation-queue-v1':
        raise ValueError('Prepared snapshot differs from the current queue entry')
    for name, field in names:
        if file_hash(folder, name) != book.get(field):
            raise ValueError('Original prepared pair changed: ' + name)
    manifest = read(checked_file(folder, 'source-manifest.json'))
    if (manifest.get('sourceCommit') != commit or manifest.get('previewOnly') is not False
            or manifest.get('scope') != {'language': key[0], 'collection': key[1]}):
        raise ValueError('Prepared source manifest identity differs')
    checked_file(folder, book['file'] + '.reader-checks.json')
    return index, queued


def plan(root, prepared):
    """Return a deterministic handoff; this does not grant visual/release approval."""
    root, prepared = Path(root).resolve(), Path(prepared).resolve()
    index, queued = _prepared(root, prepared)
    book = index['books'][0]
    docx = book['file']
    names = [docx, str(Path(docx).with_suffix('.pdf')), docx + '.reader-checks.json',
             'index.json', 'source-manifest.json', 'prepared-snapshot.json']
    return {'schema': HANDOFF_SCHEMA, 'language': book['language'], 'collection': book['collection'],
            'sourceCommit': queued['sourceCommit'], 'inputFingerprint': queued['inputFingerprint'],
            'preparation': {name: file_hash(prepared, name) for name in names},
            'pendingChecks': copy.deepcopy(queued['pendingChecks']),
            'wordProof': PROOF,
            'wordCommand': ['python', 'books/finalize_word.py', '--root', '.',
                            '--docx', 'candidate/' + docx, '--language', book['language'],
                            '--proof-dir', 'candidate/word-proof'],
            'nextSteps': ['Keep prepared/ unchanged and copy it into candidate/.',
                          'Run wordCommand on the owned desktop with Microsoft Word installed.',
                          'Inspect every page of the final PDF and the Word visual proof.',
                          'Supply visual-acceptance.json for the exact final hashes; do not reuse an earlier acceptance.',
                          'Resolve all source and scope release holds before finalization.']}


def acceptance_template(handoff, candidate):
    """Populate exact file identities, with every approval field still unaccepted."""
    candidate = Path(candidate).resolve()
    key = scope_key(handoff)
    docx = f'Iman_Companion_{key[0]}_{key[1]}.docx'
    return {'schema': ACCEPTANCE_SCHEMA, 'handoffSHA256': sha(encoded(handoff)),
            'language': key[0], 'collection': key[1], 'sourceCommit': handoff['sourceCommit'],
            'inputFingerprint': handoff['inputFingerprint'],
            'docxSHA256': file_hash(candidate, docx),
            'pdfSHA256': file_hash(candidate, str(Path(docx).with_suffix('.pdf'))),
            'wordReadbackSHA256': file_hash(candidate, docx + '.word-layout.json'),
            'wordProofSHA256': file_hash(candidate, PROOF),
            'accepted': False, 'allPdfPagesInspected': False, 'allWordPagesInspected': False,
            'reviewer': '', 'reviewedAt': ''}


def _acceptance(handoff, candidate, acceptance):
    expected = acceptance_template(handoff, candidate)
    for key, value in expected.items():
        if key not in {'accepted', 'allPdfPagesInspected', 'allWordPagesInspected', 'reviewer', 'reviewedAt'}:
            if acceptance.get(key) != value:
                raise ValueError('Visual acceptance does not match final files/handoff: ' + key)
    if any(acceptance.get(k) is not True for k in ('accepted', 'allPdfPagesInspected', 'allWordPagesInspected')):
        raise ValueError('Explicit visual acceptance of both final formats is still required')
    if not isinstance(acceptance.get('reviewer'), str) or not acceptance['reviewer'].strip():
        raise ValueError('Visual acceptance must identify the actual reviewer')
    try:
        reviewed = datetime.fromisoformat(acceptance['reviewedAt'].replace('Z', '+00:00'))
        if reviewed.tzinfo is None or reviewed > datetime.now(timezone.utc):
            raise ValueError()
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError('Visual acceptance requires a past timezone-aware reviewedAt') from None
    return expected


def _visual_record(handoff, acceptance, acceptance_bytes):
    fields = ('docxSHA256', 'pdfSHA256', 'wordReadbackSHA256', 'wordProofSHA256',
              'reviewer', 'reviewedAt', 'accepted', 'allPdfPagesInspected', 'allWordPagesInspected')
    return {'schema': ACCEPTANCE_SCHEMA, 'acceptanceSHA256': sha(acceptance_bytes),
            'handoffSHA256': sha(encoded(handoff)), 'sourceCommit': handoff['sourceCommit'],
            'inputFingerprint': handoff['inputFingerprint'],
            **{field: acceptance[field] for field in fields}}


def verify_final_visual_acceptance(folder, book):
    """Recheck persisted exact review evidence immediately before publication."""
    folder = Path(folder).resolve()
    asset_names(book)
    handoff = evidence_json(checked_file(folder, 'handoff.json').read_bytes())
    acceptance_bytes = checked_file(folder, 'visual-acceptance.json').read_bytes()
    acceptance = evidence_json(acceptance_bytes)
    if (handoff.get('schema') != HANDOFF_SCHEMA or scope_key(handoff) != scope_key(book)
            or handoff.get('sourceCommit') != book.get('sourceCommit')):
        raise ValueError('Persisted visual handoff differs from this book scope or source')
    exact = _acceptance(handoff, folder, acceptance)
    if book.get('sha256') != exact['docxSHA256'] or book.get('pdfSha256') != exact['pdfSHA256']:
        raise ValueError('Visual acceptance differs from the indexed final pair hashes')
    record = _visual_record(handoff, acceptance, acceptance_bytes)
    if book.get('finalVisualAcceptance') != record:
        raise ValueError('Persisted visual acceptance differs from the captured release evidence')
    return record


def _parts(file):
    with ZipFile(file) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate DOCX package parts')
        return {name: archive.read(name) for name in names}


def _without_contents_numbers(raw):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    body = etree.fromstring(raw, parser)
    for p in body.iter(W + 'p'):
        style = p.find('./' + W + 'pPr/' + W + 'pStyle')
        if style is None or not re.fullmatch(r'TOC\s*[1-9]', style.get(W + 'val', '')):
            continue
        link = p.find(W + 'hyperlink')
        if link is None:
            raise ValueError('Malformed contents entry during source-preservation check')
        nodes = list(link.iter())
        tabs = [i for i, node in enumerate(nodes) if node.tag == W + 'tab']
        if not tabs:
            raise ValueError('Missing contents number separator')
        values = [n for n in nodes[tabs[-1] + 1:] if n.tag == W + 't' and (n.text or '').strip()]
        if len(values) != 1 or not values[0].text.strip().isdecimal():
            raise ValueError('Invalid contents number during source-preservation check')
        values[0].text = 'CHECKED-PAGE-NUMBER'
    return etree.tostring(body, method='c14n')


def _unchanged_reader(root, prepared_docx, candidate_docx, language, temporary):
    """Allow only changes the existing Word finalizer itself can produce."""
    expected = prepared_docx
    if language in {'ar', 'ur', 'fa'}:
        from native_word_footer import prepare
        expected = temporary / 'expected-native-footer.docx'
        shutil.copyfile(prepared_docx, expected)
        prepare(expected, root, language)
    original, final = _parts(expected), _parts(candidate_docx)
    if original.keys() != final.keys():
        raise ValueError('Final DOCX package membership changed beyond Word finalization')
    for name in original:
        if name == 'word/document.xml':
            same = _without_contents_numbers(original[name]) == _without_contents_numbers(final[name])
        else:
            same = original[name] == final[name]
        if not same:
            raise ValueError('Final DOCX changed outside permitted pagination furniture: ' + name)


def _manifest_identity(manifest):
    # These two hashes describe the entire repository inventory. Unrelated
    # languages may advance while this scope's exact preparation stays current.
    return {k: v for k, v in manifest.items() if k not in {'catalogSHA256', 'reviewedBooksSHA256'}}


def _atomic_json(path, value):
    fd, name = mkstemp(dir=path.parent, prefix='.' + path.name + '-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def finalize(root, prepared, candidate, handoff, acceptance, out, commit, repo, tag):
    """Validate and append one candidate to build-report['built']; leave queue intact.

    All path arguments are local paths. ``handoff`` and ``acceptance`` are JSON
    files. No input artifact is edited. The existing publisher must subsequently
    verify remote assets before completing the queue entry.
    """
    root, prepared, candidate, out = map(lambda p: Path(p).resolve(), (root, prepared, candidate, out))
    handoff, acceptance = Path(handoff).resolve(), Path(acceptance).resolve()
    if (not re.fullmatch('[a-f0-9]{40}', commit)
            or not re.fullmatch(r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+', repo)
            or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', tag)):
        raise ValueError('Invalid publication identity')
    if git_head(root) != commit:
        raise ValueError('Checkout advanced; finalize against the current publication commit')
    if (prepared == candidate or prepared.is_relative_to(candidate) or candidate.is_relative_to(prepared)
            or out.is_relative_to(prepared) or out.is_relative_to(candidate)):
        raise ValueError('Keep immutable preparation, final candidate, and output in separate folders')
    wanted = plan(root, prepared)
    handoff_bytes, acceptance_bytes = handoff.read_bytes(), acceptance.read_bytes()
    if evidence_json(handoff_bytes) != wanted:
        raise ValueError('Handoff changed or no longer matches this exact preparation')
    accepted = evidence_json(acceptance_bytes)
    final_hashes = _acceptance(wanted, candidate, accepted)
    index, queued = _prepared(root, prepared)
    book = index['books'][0]
    key = scope_key(book)
    try:
        declaration(root, key, for_release=True)
    except ValueError as error:
        raise ValueError('Scope release hold remains; finalization cannot enable automaticRelease') from error
    require_complete_references(book)
    unknown = {r.get('check') for r in queued['pendingChecks']} - KNOWN_CHECKS
    if unknown:
        raise ValueError('Unresolved preparation checks: ' + ', '.join(sorted(map(str, unknown))))
    docx, pdf = book['file'], str(Path(book['file']).with_suffix('.pdf'))
    receipt_name = docx + '.word-layout.json'
    receipt = read(checked_file(candidate, receipt_name))
    if receipt.get('language') != key[0]:
        raise ValueError('Actual Word receipt has the wrong language')
    verified_word = verify_word(checked_file(candidate, docx), checked_file(candidate, receipt_name))
    from pypdf import PdfReader
    if len(PdfReader(checked_file(candidate, PROOF)).pages) != verified_word['pages']:
        raise ValueError('Word visual proof page count differs from actual Word readback')
    if key[0] in {'ar', 'ur', 'fa'}:
        from native_word_footer import verify_rendered_footer
        footer = verify_rendered_footer(checked_file(candidate, PROOF), root, key[0])
        if receipt.get('nativeFooter', {}).get('actualWordOutput') != footer:
            raise ValueError('Actual Word native-footer proof differs from its receipt')
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / 'build-report.json'
    report_bytes = report_path.read_bytes() if report_path.exists() else None
    report = json.loads(report_bytes) if report_bytes is not None else {
        'sourceCommit': commit, 'built': [], 'prepared': [], 'unchanged': [], 'failed': []}
    if report.get('sourceCommit') != commit or not isinstance(report.get('built'), list):
        raise ValueError('Build report belongs to another publication commit')
    if any(scope_key(row) == key for row in report['built']):
        raise ValueError('This scope already has a finalized candidate in the build report')
    destination = out / (key[0] + '-' + key[1] + '-finalized')
    if destination.exists():
        raise ValueError('Finalized output already exists; use a fresh output directory')
    with TemporaryDirectory(dir=out, prefix='.finalize-') as name:
        temporary = Path(name)
        staged = temporary / 'candidate'
        staged.mkdir()
        _unchanged_reader(root, checked_file(prepared, docx), checked_file(candidate, docx), key[0], temporary)
        for name in (docx, pdf, receipt_name, PROOF):
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked_file(candidate, name), target)
        for name in ('index.json', 'source-manifest.json', 'prepared-snapshot.json', docx + '.reader-checks.json'):
            shutil.copyfile(checked_file(prepared, name), staged / name)
        # Discard all untrusted candidate metadata; final checks update the
        # original, queue-bound index. In particular reference holds cannot be
        # cleared by editing a received index.json.
        execute([sys.executable, 'books/index_units.py', '--root', root, '--commit', queued['sourceCommit'],
                 '--language', key[0], '--collection', key[1]], root)
        if _manifest_identity(read(root / 'books/manifest.json')) != _manifest_identity(read(staged / 'source-manifest.json')):
            raise ValueError('Regenerated source manifest differs from the prepared scope')
        captured = capture(root, index, preparation=True)
        if captured['entries'] != [queued['candidate']]:
            raise ValueError('Regenerated source snapshot differs from the queued preparation')
        execute([sys.executable, 'books/check_outputs.py', '--root', root, '--folder', staged,
                 '--tag', tag, '--repo', repo], root)
        checked = read(staged / 'index.json')
        checked_book = checked['books'][0]
        if (len(checked['books']) != 1 or scope_key(checked_book) != key
                or checked_book.get('exportVerified') is not True
                or checked_book.get('wordContentsVerification') != verified_word):
            raise ValueError('Final export did not verify the exact Word candidate')
        if checked_book.get('sha256') != final_hashes['docxSHA256'] or checked_book.get('pdfSha256') != final_hashes['pdfSHA256']:
            raise ValueError('Final exported pair differs from the visually accepted files')
        require_complete_references(checked_book)
        checked_book['independentWordLayoutVerification'] = {
            'word': checked_book['wordContentsVerification'], 'pdf': checked_book['pdfContentsVerification']}
        checked_book['finalVisualAcceptance'] = _visual_record(wanted, accepted, acceptance_bytes)
        snapshot = capture(root, checked)
        write_json(staged / 'index.json', checked)
        write_json(staged / 'library-snapshot.json', snapshot)
        (staged / 'handoff.json').write_bytes(handoff_bytes)
        (staged / 'visual-acceptance.json').write_bytes(acceptance_bytes)
        verify_final_visual_acceptance(staged, checked_book)
        result = {'schema': FINAL_SCHEMA, 'state': 'verified-release-candidate',
                  'language': key[0], 'collection': key[1], 'sourceCommit': queued['sourceCommit'],
                  'publicationCommit': commit, 'inputFingerprint': queued['inputFingerprint'],
                  'handoffSHA256': sha(encoded(wanted)), 'visualAcceptanceSHA256': sha(acceptance_bytes),
                  'reviewer': accepted['reviewer'], 'reviewedAt': accepted['reviewedAt'],
                  'preparedDocxSHA256': book['sha256'], 'preparedPdfSHA256': book['pdfSha256'],
                  'docxSHA256': final_hashes['docxSHA256'], 'pdfSHA256': final_hashes['pdfSHA256'],
                  'wordReadbackSHA256': final_hashes['wordReadbackSHA256'], 'wordProofSHA256': final_hashes['wordProofSHA256'],
                  'librarySnapshotSHA256': file_hash(staged, 'library-snapshot.json'), 'folder': destination.name}
        write_json(staged / 'finalization-receipt.json', result)
        # Recheck both the live source and the immutable accepted bytes after
        # expensive validators. Concurrent source/reviewer changes abort safely.
        if plan(root, prepared) != wanted or git_head(root) != commit:
            raise ValueError('Source or checkout changed during finalization')
        if handoff.read_bytes() != handoff_bytes or acceptance.read_bytes() != acceptance_bytes:
            raise ValueError('Handoff or visual acceptance changed during finalization')
        _acceptance(wanted, staged, accepted)
        if (report_path.read_bytes() if report_path.exists() else None) != report_bytes:
            raise ValueError('Build report changed during finalization; retry with current output')
        report['built'].append({'language': key[0], 'collection': key[1], 'folder': destination.name})
        for field in ('prepared', 'unchanged', 'failed', 'preparedAwaitingReleaseQC'):
            if field in report:
                report[field] = [row for row in report[field] if scope_key(row) != key]
        os.replace(staged, destination)
        try:
            _atomic_json(report_path, report)
        except Exception:
            shutil.rmtree(destination)
            raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    handoff = sub.add_parser('plan', help='Bind a prepared scope to a desktop QC handoff')
    handoff.add_argument('--root', type=Path, required=True)
    handoff.add_argument('--prepared', type=Path, required=True)
    handoff.add_argument('--handoff', type=Path, required=True)
    template = sub.add_parser('acceptance-template', help='Write exact final hashes, with approval fields still false')
    template.add_argument('--handoff', type=Path, required=True)
    template.add_argument('--candidate', type=Path, required=True)
    template.add_argument('--acceptance', type=Path, required=True)
    finish = sub.add_parser('finalize', help='Verify evidence and stage one existing-publisher candidate')
    for flag in ('root', 'prepared', 'candidate', 'handoff', 'acceptance', 'out'):
        finish.add_argument('--' + flag, type=Path, required=True)
    for flag in ('commit', 'repo', 'tag'):
        finish.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            value = plan(args.root, args.prepared)
            if args.handoff.exists():
                raise ValueError('Handoff output already exists; preserve the existing evidence')
            write_json(args.handoff, value)
            result = {'handoff': str(args.handoff), 'handoffSHA256': sha(encoded(value)), 'pendingChecks': value['pendingChecks']}
        elif args.action == 'acceptance-template':
            if args.acceptance.exists():
                raise ValueError('Acceptance output already exists; preserve the reviewer evidence')
            value = acceptance_template(evidence_json(args.handoff.read_bytes()), args.candidate)
            write_json(args.acceptance, value)
            result = {'acceptance': str(args.acceptance), 'accepted': False}
        else:
            result = finalize(args.root, args.prepared, args.candidate, args.handoff,
                              args.acceptance, args.out, args.commit, args.repo, args.tag)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, 'Prepared candidate was not finalized: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
