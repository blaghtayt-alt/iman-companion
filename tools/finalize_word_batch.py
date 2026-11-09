"""Stage exact queued preparations and run the existing Word finalizer serially.

This local helper never publishes, changes the queue, supplies source approval,
or accepts a visual review. Its bookkeeping stays outside the transfer bundle.
"""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / 'books'))
import finalize_prepared as finish
from preparation_queue import load as load_queue
from published_library import scope_key
from release_candidate_intake import SCHEMA as BUNDLE_SCHEMA, manifest_bytes, validate_bundle
from word_layout_check import verify as verify_word

STATE_SCHEMA = 'iman-local-word-finalization-batch-v1'
REVIEW_FIELDS = {'accepted', 'allPdfPagesInspected', 'allWordPagesInspected',
                 'reviewer', 'reviewedAt'}


def is_windows():
    return sys.platform == 'win32'


def reject_symlink_parents(path):
    for current in (path, *path.parents):
        if current.is_symlink():
            raise ValueError('Symlink in batch output path: ' + str(current))


def sha_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Expected a regular file: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Expected a non-symlink scope directory: ' + str(folder))
    result = {}
    for parent, directories, files in os.walk(folder, followlinks=False):
        for name in directories:
            if (Path(parent) / name).is_symlink():
                raise ValueError('Symlink in scope directory')
        for name in files:
            path = Path(parent) / name
            result[path.relative_to(folder).as_posix()] = sha_file(path)
    return result


def read_json(path):
    sha_file(path)
    return finish.evidence_json(path.read_bytes())


def save_json(path, value):
    reject_symlink_parents(path)
    raw = finish.encoded(value)
    if path.exists() or path.is_symlink():
        sha_file(path)
        if path.read_bytes() == raw:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = mkstemp(dir=path.parent, prefix='.' + path.name + '-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def owned_lock(out):
    """An OS-held lock releases after a crash; never kill another process."""
    path = out / '.word-batch.lock'
    if path.is_symlink():
        raise ValueError('Batch lock must not be a symlink')
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'r+b', buffering=0) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Batch lock must be a regular file')
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'\0')
        stream.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('Another batch process owns this output directory') from error
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def scope_name(key):
    scope_key({'language': key[0], 'collection': key[1]})
    return key[0] + '-' + key[1]


def selected_rows(root, artifact, requested):
    queued = {scope_key(row): row for row in load_queue(root)['entries']}
    if requested:
        keys = []
        for item in requested:
            parts = item.split('/')
            if len(parts) != 2:
                raise ValueError('Use --scope LANGUAGE/COLLECTION')
            key = scope_key({'language': parts[0], 'collection': parts[1]})
            if key not in queued:
                raise ValueError('Requested scope is absent from the current queue: ' + item)
            if key in keys:
                raise ValueError('Duplicate selected scope: ' + item)
            keys.append(key)
    else:
        keys = [key for key in queued if (artifact / scope_name(key)).exists()]
    if not keys:
        raise ValueError('No queued preparation folders found in this artifact')
    for key in keys:
        if queued[key].get('folder') != scope_name(key):
            raise ValueError('Queue has a noncanonical preparation folder')
    return [(key, queued[key]) for key in sorted(keys)]


def stage_scope(root, artifact, out, key, old):
    name = scope_name(key)
    source = artifact / name
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Missing non-symlink artifact scope: ' + name)
    handoff = finish.plan(root, source)
    digest = hashlib.sha256(finish.encoded(handoff)).hexdigest()
    if old and old.get('handoffSHA256') != digest:
        raise ValueError('Batch scope belongs to different preparation inputs; use a new output directory')
    staged = out / 'staged' / name
    reject_symlink_parents(staged)
    expected = {kind + '/' + file: value for kind in ('prepared', 'candidate')
                for file, value in handoff['preparation'].items()}
    expected['handoff.json'] = digest
    if not staged.exists() and not staged.is_symlink():
        staged.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=out, prefix='.stage-') as temporary:
            work = Path(temporary) / 'scope'
            for kind in ('prepared', 'candidate'):
                (work / kind).mkdir(parents=True)
                for file in handoff['preparation']:
                    shutil.copyfile(finish.checked_file(source, file), work / kind / file)
            save_json(work / 'handoff.json', handoff)
            if inventory(work) != expected or finish.plan(root, source) != handoff:
                raise ValueError('Preparation changed while staging')
            os.replace(work, staged)
    if inventory(staged) != expected or finish.plan(root, staged / 'prepared') != handoff:
        raise ValueError('Staged preparation, candidate or handoff was changed; preserved without overwriting')
    return handoff, staged, {
        'handoffSHA256': digest, 'sourceCommit': handoff['sourceCommit'],
        'inputFingerprint': handoff['inputFingerprint'], 'state': 'staged',
    }


def invoke_word(root, candidate, key):
    if not is_windows():
        raise ValueError('Actual Word finalization requires Windows and installed Microsoft Word')
    script = root / 'books/finalize_word.py'
    sha_file(script)
    docx = 'Iman_Companion_' + key[0] + '_' + key[1] + '.docx'
    command = [sys.executable, str(script), '--root', str(root), '--docx', str(candidate / docx),
               '--language', key[0], '--proof-dir', str(candidate / 'word-proof')]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                            encoding='utf8', errors='replace')
    if result.returncode:
        raise ValueError('Microsoft Word finalization failed:\n' + result.stderr[-2500:] + '\n' + result.stdout[-1000:])


def verify_candidate(root, folder, handoff):
    """Check the existing Word receipt and allowed finalizer-only changes."""
    key = scope_key(handoff)
    prepared, candidate = folder / 'prepared', folder / 'candidate'
    if finish.plan(root, prepared) != handoff or read_json(folder / 'handoff.json') != handoff:
        raise ValueError('Finalized scope handoff or source is stale')
    docx = 'Iman_Companion_' + key[0] + '_' + key[1] + '.docx'
    receipt_name = docx + '.word-layout.json'
    original = handoff['preparation']
    files = inventory(candidate)
    if set(files) != set(original) | {receipt_name, finish.PROOF}:
        raise ValueError('Candidate has missing or unexpected files')
    if any(files[name] != digest for name, digest in original.items() if name != docx):
        raise ValueError('Word finalization changed the canonical PDF or preparation metadata')
    receipt = read_json(candidate / receipt_name)
    if receipt.get('language') != key[0]:
        raise ValueError('Word readback belongs to another language')
    verified = verify_word(candidate / docx, candidate / receipt_name)
    from pypdf import PdfReader
    if len(PdfReader(candidate / finish.PROOF).pages) != verified['pages']:
        raise ValueError('Word proof page count differs from the Word readback')
    with TemporaryDirectory(prefix='.reader-check-', dir=folder.parent) as temporary:
        finish._unchanged_reader(root, prepared / docx, candidate / docx, key[0], Path(temporary))
    if key[0] in {'ar', 'ur', 'fa'}:
        from native_word_footer import verify_rendered_footer
        footer = verify_rendered_footer(candidate / finish.PROOF, root, key[0])
        if receipt.get('nativeFooter', {}).get('actualWordOutput') != footer:
            raise ValueError('Word native-footer proof differs from its receipt')


def verified_final(root, folder, handoff, old=None):
    reject_symlink_parents(folder)
    verify_candidate(root, folder, handoff)
    expected = finish.acceptance_template(handoff, folder / 'candidate')
    accepted = read_json(folder / 'visual-acceptance.json')
    if set(accepted) != set(expected) or any(accepted[field] != expected[field]
            for field in set(expected) - REVIEW_FIELDS):
        raise ValueError('Existing visual review is not bound to these exact final files')
    for field in ('accepted', 'allPdfPagesInspected', 'allWordPagesInspected'):
        if type(accepted[field]) is not bool:
            raise ValueError('Invalid visual review checkbox')
    if not isinstance(accepted['reviewer'], str) or not isinstance(accepted['reviewedAt'], str):
        raise ValueError('Invalid visual review identity')
    if accepted['accepted']:
        finish._acceptance(handoff, folder / 'candidate', accepted)
    hashes = inventory(folder)
    docx = 'Iman_Companion_' + handoff['language'] + '_' + handoff['collection'] + '.docx'
    expected_files = {kind + '/' + name for kind in ('prepared', 'candidate')
                      for name in handoff['preparation']}
    expected_files.update({'handoff.json', 'visual-acceptance.json',
                           'candidate/' + docx + '.word-layout.json', 'candidate/' + finish.PROOF})
    if set(hashes) != expected_files:
        raise ValueError('Completed scope contains missing or unexpected evidence files')
    # The reviewer may edit only the existing acceptance's review fields.
    hashes.pop('visual-acceptance.json')
    if old and old.get('finalFiles') != hashes:
        raise ValueError('Completed candidate files changed since the recorded Word run')
    return hashes


def finalize_scope(root, artifact, out, key, handoff, staged, old):
    destination = out / 'bundle' / scope_name(key)
    reject_symlink_parents(destination)
    if destination.exists() or destination.is_symlink():
        return verified_final(root, destination, handoff, old if old and old.get('state') == 'word-complete' else None)
    if old and old.get('state') == 'word-complete':
        raise ValueError('Recorded completed candidate is missing; preserve the batch state')
    before = inventory(staged)
    with TemporaryDirectory(dir=out, prefix='.word-attempt-') as temporary:
        work = Path(temporary) / 'scope'
        shutil.copytree(staged, work)
        invoke_word(root, work / 'candidate', key)
        verify_candidate(root, work, handoff)
        save_json(work / 'visual-acceptance.json', finish.acceptance_template(handoff, work / 'candidate'))
        hashes = verified_final(root, work, handoff)
        if inventory(staged) != before or finish.plan(root, artifact / scope_name(key)) != handoff:
            raise ValueError('Original preparation changed during the Word run')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise ValueError('Candidate destination appeared during the Word run')
        os.replace(work, destination)
    return hashes


def write_bundle(root, out, state):
    scopes = []
    for identity, record in sorted(state['scopes'].items()):
        if record.get('state') != 'word-complete':
            continue
        key = tuple(identity.split('/'))
        name = scope_name(key)
        folder = out / 'bundle' / name
        handoff = read_json(folder / 'handoff.json')
        if hashlib.sha256(finish.encoded(handoff)).hexdigest() != record.get('handoffSHA256'):
            raise ValueError('Completed handoff differs from batch state')
        verified_final(root, folder, handoff, record)
        scopes.append({'language': key[0], 'collection': key[1],
                       'prepared': name + '/prepared', 'candidate': name + '/candidate',
                       'handoff': name + '/handoff.json', 'acceptance': name + '/visual-acceptance.json'})
    if not scopes:
        return None
    manifest = {'schema': BUNDLE_SCHEMA, 'scopes': scopes}
    manifest_bytes(finish.encoded(manifest))
    save_json(out / 'bundle/bundle.json', manifest)
    validate_bundle(out / 'bundle', require_inventory=False)
    return 'bundle/bundle.json'


def run_batch(root, artifact, out, requested=None, stage_only=False):
    if not stage_only and not is_windows():
        raise ValueError('Use --stage-only on this system; actual Word finalization requires Windows')
    root, artifact, out = map(lambda path: Path(path).absolute(), (root, artifact, out))
    for path in (root, artifact, out):
        if path.is_symlink():
            raise ValueError('Repository, artifact and output must not be symlinks')
    root, artifact, out = root.resolve(), artifact.resolve(), out.resolve()
    if not root.is_dir() or not artifact.is_dir():
        raise ValueError('Repository and extracted artifact must be existing directories')
    if out == root or root.is_relative_to(out) or out.is_relative_to(root):
        raise ValueError('Keep batch output outside and separate from the repository')
    if artifact == out or artifact.is_relative_to(out) or out.is_relative_to(artifact):
        raise ValueError('Keep batch output and the immutable downloaded artifact separate')
    rows = selected_rows(root, artifact, requested)
    out.mkdir(parents=True, exist_ok=True)
    with owned_lock(out):
        state_file = out / 'state.json'
        state = read_json(state_file) if state_file.exists() else {'schema': STATE_SCHEMA, 'scopes': {}}
        if state.get('schema') != STATE_SCHEMA or not isinstance(state.get('scopes'), dict):
            raise ValueError('Invalid batch state')
        report = {'stageOnly': stage_only, 'staged': [], 'wordComplete': [], 'failed': [], 'bundle': None}
        for key, _ in rows:
            identity = '/'.join(key)
            print(identity + ': checking exact queued preparation', flush=True)
            old = state['scopes'].get(identity)
            try:
                handoff, staged, record = stage_scope(root, artifact, out, key, old)
                if not old:
                    state['scopes'][identity] = record
                    save_json(state_file, state)
                if not stage_only or (old and old.get('state') == 'word-complete'):
                    if stage_only:
                        hashes = verified_final(root, out / 'bundle' / scope_name(key), handoff, old)
                    else:
                        print(identity + ': checking or running owned Microsoft Word', flush=True)
                        hashes = finalize_scope(root, artifact, out, key, handoff, staged, old)
                    record.update(state='word-complete', finalFiles=hashes)
                    state['scopes'][identity] = record
                    save_json(state_file, state)
                    report['wordComplete'].append(identity)
                    print(identity + ': Word complete; explicit visual review remains separate', flush=True)
                else:
                    report['staged'].append(identity)
                    print(identity + ': staged without Word execution', flush=True)
            except Exception as error:
                report['failed'].append({'scope': identity, 'error': str(error)})
                print(identity + ': failed: ' + str(error), flush=True)
        try:
            report['bundle'] = write_bundle(root, out, state)
        except Exception as error:
            report['failed'].append({'scope': 'bundle', 'error': str(error)})
        save_json(out / 'report.json', report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'artifact', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--scope', action='append', help='Optional LANGUAGE/COLLECTION; repeat to select several')
    parser.add_argument('--stage-only', action='store_true', help='Validate and copy only; never launch Word')
    args = parser.parse_args(argv)
    try:
        if args.root.resolve() != CODE_ROOT.resolve():
            raise ValueError('--root must identify the checkout containing this batch helper; '
                             'run that checkout\'s tools/finalize_word_batch.py')
        report = run_batch(args.root, args.artifact, args.out, args.scope, args.stage_only)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report['failed'] else 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, 'Batch stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
