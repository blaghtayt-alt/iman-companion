"""Propose recovery of exact interrupted preparations; never apply or approve.

The artifact API metadata is a separately fetched trusted input, not an online
attestation. Its digest pins the ZIP. The original planner checks each snapshot
against a private copy of current sources with only its proposed queue added.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile
import argparse
import json
import os
import re
import shutil
import stat
import sys

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / 'books'))
import finalize_prepared as finish
from preparation_queue import PATH as QUEUE_PATH, SCHEMA as QUEUE_SCHEMA, load, signature
from published_library import declaration, scope_key, sha
from finalize_word_batch import inventory, reject_symlink_parents, sha_file

SCHEMA = 'iman-preparation-recovery-proposal-v1'
REPOSITORY = 'blaghtayt-alt/iman-companion'
MAX_FILES = 20000
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
SKIP_DIRECTORIES = {'.git', '.cache', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv'}


def read_json(path):
    sha_file(path)
    return finish.evidence_json(path.read_bytes())


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf8')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def overlaps(first, second):
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def artifact_identity(metadata, repository):
    """Bind one GitHub artifact API record without claiming to authenticate it."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid expected repository')
    if 'artifacts' in metadata:
        if not isinstance(metadata['artifacts'], list) or len(metadata['artifacts']) != 1:
            raise ValueError('Supply API metadata for exactly one selected artifact')
        metadata = metadata['artifacts'][0]
    if not isinstance(metadata, dict):
        raise ValueError('Artifact API metadata must be an object')
    identity = metadata.get('id')
    name = metadata.get('name', '')
    match = re.fullmatch(r'current-book-publication-([1-9][0-9]*)-([1-9][0-9]*)', name)
    if type(identity) is not int or identity <= 0 or not match:
        raise ValueError('Not an identified production preparation artifact')
    run, attempt = match.groups()
    workflow = metadata.get('workflow_run', {})
    if not isinstance(workflow, dict):
        raise ValueError('Artifact workflow identity must be an object')
    commit = workflow.get('head_sha', '')
    repository_id = workflow.get('repository_id')
    if (type(workflow.get('id')) is not int or workflow['id'] != int(run)
            or workflow.get('head_branch') != 'main'
            or type(repository_id) is not int or repository_id <= 0
            or workflow.get('head_repository_id') != repository_id
            or not re.fullmatch(r'[a-f0-9]{40}', commit)):
        raise ValueError('Artifact run, main branch, repository or source identity differs')
    url = f'https://api.github.com/repos/{repository}/actions/artifacts/{identity}'
    if metadata.get('url') != url or metadata.get('archive_download_url') != url + '/zip':
        raise ValueError('Artifact API URLs belong to a different repository or artifact')
    digest = metadata.get('digest', '')
    size = metadata.get('size_in_bytes')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest) or type(size) is not int or size <= 0:
        raise ValueError('Artifact metadata needs its original SHA-256 digest and size')
    if not isinstance(metadata.get('expires_at'), str):
        raise ValueError('Artifact metadata needs an explicit expiry')
    try:
        expires = datetime.fromisoformat(metadata['expires_at'].replace('Z', '+00:00'))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Artifact metadata needs an explicit expiry') from error
    if metadata.get('expired') is not False or expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError('Expired artifacts cannot be proposed as current queue entries')
    return {'repository': repository, 'id': identity, 'name': name, 'runId': run,
            'runAttempt': attempt, 'sourceCommit': commit, 'sha256': digest[7:],
            'sizeBytes': size, 'expiresAt': metadata['expires_at'],
            'runURL': f'https://github.com/{repository}/actions/runs/{run}'}


def extract_archive(archive, out):
    """Reject unsafe/ambiguous ZIP entries before extracting any member."""
    with ZipFile(archive) as source:
        entries = source.infolist()
        if not entries or len(entries) > MAX_FILES or sum(row.file_size for row in entries) > MAX_EXPANDED_BYTES:
            raise ValueError('Preparation archive exceeds the bounded file inventory')
        names = {}
        checked = []
        for row in entries:
            name = row.orig_filename
            stripped = name[:-1] if name.endswith('/') else name
            path = PurePosixPath(stripped)
            parts = stripped.split('/')
            kind = stat.S_IFMT(row.external_attr >> 16)
            if (not stripped or path.is_absolute() or any(part in {'', '.', '..'} for part in parts)
                    or any(char in name for char in '\\:<>"|?*') or any(ord(char) < 32 for char in name)
                    or any(part.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)
                           for part in parts)
                    or row.flag_bits & 1 or row.file_size > MAX_FILE_BYTES
                    or kind not in ({0, stat.S_IFDIR} if row.is_dir() else {0, stat.S_IFREG})):
                raise ValueError('Unsafe or unsupported preparation archive member: ' + repr(name))
            folded = stripped.casefold()
            if folded in names:
                raise ValueError('Duplicate or case-colliding preparation archive member: ' + name)
            names[folded] = (stripped, row.is_dir())
            checked.append((row, path))
        # Check implicit directories as well as explicit ZIP entries, including
        # case collisions that would alias on the owned Windows desktop.
        directories = {}
        for row, path in checked:
            parents = list(path.parents)[:-1]
            if row.is_dir():
                parents.append(path)
            for parent in parents:
                name = str(parent)
                folded = name.casefold()
                if folded in names and (not names[folded][1] or names[folded][0] != name):
                    raise ValueError('Archive file/directory collision: ' + name)
                if folded in directories and directories[folded] != name:
                    raise ValueError('Archive directory case collision: ' + name)
                directories[folded] = name
        out.mkdir()
        for row, relative in checked:
            target = out.joinpath(*relative.parts)
            if row.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(row) as incoming, target.open('xb') as destination:
                shutil.copyfileobj(incoming, destination, 1024 * 1024)
            if target.stat().st_size != row.file_size:
                raise ValueError('Extracted preparation member size differs')


def copy_sources(root, target):
    """Copy regular current files; never copy Git history, caches or symlinks."""
    def ignore(parent, names):
        skipped = []
        for name in names:
            path = Path(parent) / name
            if name == '.git' or (name in SKIP_DIRECTORIES and path.is_dir()):
                skipped.append(name)
            elif path.is_symlink():
                raise ValueError('Repository source must not be a symlink: ' + str(path.relative_to(root)))
        return skipped

    def copy_file(source, destination):
        original = sha_file(Path(source))
        shutil.copyfile(source, destination)
        if sha_file(Path(destination)) != original:
            raise ValueError('Current source changed during isolation')
        return destination

    shutil.copytree(root, target, ignore=ignore, copy_function=copy_file)


def validate_row(row, folder, identity, root):
    if not isinstance(row, dict) or not isinstance(row.get('candidate'), dict) or not isinstance(row['candidate'].get('book'), dict):
        raise ValueError('Malformed original preparation snapshot entry')
    key = scope_key(row)
    name = '-'.join(key)
    if folder.name != name or row.get('folder') != name:
        raise ValueError('Prepared scope has a noncanonical folder identity')
    if row.get('sourceCommit') != identity['sourceCommit']:
        raise ValueError('Prepared source commit differs from the pinned artifact run')
    expected = {field: identity[field] for field in ('repository', 'runId', 'name', 'runURL')}
    if (not isinstance(row.get('artifact'), dict)
            or any(row['artifact'].get(field) != value for field, value in expected.items())
            or 'localArtifacts' in row):
        raise ValueError('Prepared snapshot artifact provenance differs')
    if not isinstance(row['artifact'].get('expiresAt'), str):
        raise ValueError('Original preparation artifact expiry is missing')
    try:
        expires = datetime.fromisoformat(row['artifact']['expiresAt'].replace('Z', '+00:00'))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Original preparation artifact expiry is missing') from error
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError('Original preparation artifact entry is expired')
    # Check the live source before considering queue conflicts, so an old
    # artifact cannot be mistaken for a newer candidate needing replacement.
    if row.get('inputFingerprint') != signature(root, key):
        raise ValueError('Preparation inputs changed; rebuild this scope before recovery')
    checks = row.get('pendingChecks')
    if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
        raise ValueError('Missing preparation review holds')
    names = [check.get('check') for check in checks]
    if (any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)
            or set(names) - finish.KNOWN_CHECKS
            or not {'actual-word-layout', 'final-visual-inspection'}.issubset(names)):
        raise ValueError('Recovery requires the original Word and visual review holds')
    if declaration(root, key, for_release=False).get('automaticRelease') is not True and 'scope-release-hold' not in names:
        raise ValueError('Prepared snapshot omits its scope release hold')
    try:
        finish.require_complete_references(row['candidate']['book'])
    except ValueError:
        if 'source-references' not in names:
            raise ValueError('Prepared snapshot omits its source-reference hold')
    return key


def run_recovery(root, archive, metadata_path, out, repository=REPOSITORY):
    root, archive, metadata_path, out = [Path(path).absolute() for path in (root, archive, metadata_path, out)]
    for path in (root, archive, metadata_path, out):
        reject_symlink_parents(path)
    root, archive, metadata_path, out = [path.resolve() for path in (root, archive, metadata_path, out)]
    if not root.is_dir():
        raise ValueError('Current repository must be an existing directory')
    if (overlaps(root, out) or overlaps(archive, out) or overlaps(metadata_path, out)
            or archive.is_relative_to(root) or metadata_path.is_relative_to(root)):
        raise ValueError('Keep repository, immutable archive and recovery output separate')
    metadata_hash = sha_file(metadata_path)
    identity = artifact_identity(read_json(metadata_path), repository)
    archive_hash = sha_file(archive)
    if archive_hash != identity['sha256'] or archive.stat().st_size != identity['sizeBytes']:
        raise ValueError('Archive differs from the separately fetched API digest or size')
    queue_path = root / QUEUE_PATH
    original_queue = queue_path.read_bytes() if queue_path.exists() else None
    if original_queue is not None:
        read_json(queue_path)  # Reject duplicate JSON fields before using the existing loader.
    current = load(root)
    proposed = deepcopy(current)
    existing = {scope_key(row): row for row in current['entries']}
    report = {'schema': SCHEMA, 'artifact': identity, 'metadataSHA256': metadata_hash,
              'provenanceBoundary': 'Separately fetched trusted GitHub API metadata; no online attestation performed',
              'baseQueueSHA256': sha(original_queue) if original_queue is not None else None,
              'existingEntries': len(current['entries']), 'recovered': [], 'alreadyCurrent': [],
              'rejected': [], 'ignored': [], 'releaseVerified': False,
              'wordExecuted': False, 'visualAcceptanceGranted': False, 'queueApplied': False}
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.preparation-recovery-', dir=out.parent) as temporary:
        work = Path(temporary)
        extracted, isolated, result = work / 'artifact', work / 'sources', work / 'result'
        extract_archive(archive, extracted)
        copy_sources(root, isolated)
        result.mkdir()
        if (extracted / 'build-report.json').exists():
            checkpoint = read_json(extracted / 'build-report.json')
            if checkpoint.get('sourceCommit') != identity['sourceCommit']:
                raise ValueError('Build checkpoint belongs to a different source commit')
            report['buildComplete'] = checkpoint.get('buildComplete')
        accepted = []
        for folder in sorted(extracted.iterdir()):
            if not folder.is_dir():
                continue
            if not (folder / 'prepared-snapshot.json').is_file():
                report['ignored'].append({'folder': folder.name, 'reason': 'No completed preparation snapshot'})
                continue
            try:
                snapshot = read_json(folder / 'prepared-snapshot.json')
                if (snapshot.get('schema') != QUEUE_SCHEMA or not isinstance(snapshot.get('entries'), list)
                        or len(snapshot['entries']) != 1):
                    raise ValueError('Expected exactly one original prepared snapshot entry')
                row = snapshot['entries'][0]
                key = validate_row(row, folder, identity, root)
                if key in existing and existing[key] != row:
                    raise ValueError('Current queue has a different entry; preserved without replacement')
                # Only this private queue is changed. Artifact bytes and the
                # actual checkout stay untouched, including stale prior rows.
                validation_queue = deepcopy(current)
                if key not in existing:
                    validation_queue['entries'].append(row)
                write_json(isolated / QUEUE_PATH, validation_queue)
                read_json(folder / 'index.json')
                read_json(folder / 'source-manifest.json')
                handoff = finish.plan(isolated, folder)
                if handoff['inputFingerprint'] != signature(root, key):
                    raise ValueError('Current source changed during recovery validation')
                destination = result / 'prepared' / folder.name
                destination.mkdir(parents=True)
                for name, digest in handoff['preparation'].items():
                    shutil.copyfile(finish.checked_file(folder, name), destination / name)
                    if sha_file(destination / name) != digest:
                        raise ValueError('Prepared file changed during recovery copy')
                if finish.plan(isolated, destination) != handoff:
                    raise ValueError('Recovered copy differs from its exact handoff')
                write_json(result / 'handoffs' / (folder.name + '.json'), handoff)
                detail = {'language': key[0], 'collection': key[1], 'folder': folder.name,
                          'inputFingerprint': handoff['inputFingerprint'],
                          'preparedSnapshotSHA256': handoff['preparation']['prepared-snapshot.json'],
                          'handoffSHA256': sha(json_bytes(handoff)),
                          'pendingChecks': deepcopy(row['pendingChecks'])}
                if key in existing:
                    report['alreadyCurrent'].append(detail)
                else:
                    proposed['entries'].append(deepcopy(row))
                    report['recovered'].append(detail)
                accepted.append((key, handoff['inputFingerprint']))
            except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
                shutil.rmtree(result / 'prepared' / folder.name, ignore_errors=True)
                report['rejected'].append({'folder': folder.name, 'error': str(error)})
        # The proposal is bound to the complete original queue, not just the
        # recovered scopes. A concurrent queue update requires a fresh proposal.
        after_queue = queue_path.read_bytes() if queue_path.exists() else None
        if after_queue != original_queue:
            raise ValueError('Current preparation queue changed during recovery; rerun against the new queue')
        if sha_file(archive) != archive_hash or sha_file(metadata_path) != metadata_hash:
            raise ValueError('Immutable recovery inputs changed during validation')
        if any(signature(root, key) != fingerprint for key, fingerprint in accepted):
            raise ValueError('Current source changed before the recovery proposal completed')
        proposal = original_queue if not report['recovered'] and original_queue is not None else json_bytes(proposed)
        (result / 'proposed-prepared-library.json').write_bytes(proposal)
        report['proposedQueueSHA256'] = sha(proposal)
        write_json(result / 'recovery-audit.json', report)
        if out.exists():
            if inventory(out) != inventory(result):
                raise ValueError('Recovery output already contains different evidence; use a new output directory')
        else:
            os.replace(result, out)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('root', 'archive', 'artifact-metadata', 'out'):
        parser.add_argument('--' + field, type=Path, required=True)
    parser.add_argument('--repository', default=REPOSITORY)
    args = parser.parse_args(argv)
    try:
        if args.root.resolve() != CODE_ROOT.resolve():
            raise ValueError('--root must identify the checkout containing this recovery helper')
        report = run_recovery(args.root, args.archive, args.artifact_metadata, args.out, args.repository)
    except (ValueError, OSError, KeyError, TypeError, BadZipFile, NotImplementedError) as error:
        print('Preparation recovery rejected: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({'recovered': len(report['recovered']), 'alreadyCurrent': len(report['alreadyCurrent']),
                      'rejected': report['rejected'], 'queueApplied': False,
                      'audit': str(args.out / 'recovery-audit.json')}, ensure_ascii=False))
    if report['rejected'] or not (report['recovered'] or report['alreadyCurrent']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
