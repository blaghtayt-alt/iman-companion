"""Move exact owned-desktop evidence through pinned Git blobs, never approvals.

``prepare`` makes a minimal public-safe transfer before any connector upload.
``process`` uses the existing extractor/finalizer. Only the normal publisher
records consumption, after its remote pair checks, in the same catalog commit.
"""
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from threading import Timer
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess

import release_candidate_intake as intake

SCHEMA = 'iman-book-connector-transfer-v1'
RECEIPT_SCHEMA = 'iman-book-connector-consumption-v1'
INTAKE = 'materials/book-finalization-intake'
HISTORY = 'materials/book-finalization-intake-history'
MAX_ARCHIVE_BYTES = 512 * 1024 ** 2
MAX_CHUNK_BYTES = 8 * 1024 ** 2
DEFAULT_CHUNK_BYTES = 512 * 1024
MAX_CHUNKS = 4096
MAX_MANIFESTS = 256
HEX40 = re.compile(r'[a-f0-9]{40}\Z')
HEX64 = re.compile(r'[a-f0-9]{64}\Z')
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')
SCOPE_KEYS = {'language', 'collection', 'sourceCommit', 'inputFingerprint'}
PUBLISHED_KEYS = SCOPE_KEYS | {'docxSHA256', 'pdfSHA256', 'releaseTag', 'publicationCommit'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob_sha(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


def key(scope):
    return scope['language'], scope['collection']


def safe_file(root, relative):
    parts = intake.safe_path(relative).parts
    path = Path(root)
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlinked transfer/evidence paths are not permitted')
    if not path.is_file():
        raise ValueError('Missing required transfer/evidence file: ' + relative)
    return path


def read_json(path):
    if path.stat().st_size > intake.MAX_JSON_BYTES:
        raise ValueError('Transfer metadata exceeds its size limit')
    return intake.json_bytes(path.read_bytes(), 'transfer metadata')


def validate_scope(scope):
    if (not isinstance(scope, dict) or set(scope) != SCOPE_KEYS
            or not isinstance(scope.get('language'), str) or scope['language'] not in intake.COPY
            or not isinstance(scope.get('collection'), str) or scope['collection'] not in intake.COLLECTIONS
            or not isinstance(scope.get('sourceCommit'), str)
            or not HEX40.fullmatch(scope['sourceCommit'])
            or not isinstance(scope.get('inputFingerprint'), str)
            or not HEX64.fullmatch(scope['inputFingerprint'])):
        raise ValueError('Invalid declared prepared scope')


def validate_manifest(value, repo):
    fields = {'schema', 'repository', 'archiveSHA256', 'archiveBytes', 'chunks', 'scopes'}
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise ValueError('Invalid workflow repository identity')
    if (not isinstance(value, dict) or set(value) != fields or value.get('schema') != SCHEMA
            or value.get('repository') != repo):
        raise ValueError('Transfer must name exactly the workflow repository and supported schema')
    if (not isinstance(value['archiveSHA256'], str) or not HEX64.fullmatch(value['archiveSHA256'])
            or type(value['archiveBytes']) is not int or not 0 < value['archiveBytes'] <= MAX_ARCHIVE_BYTES):
        raise ValueError('Invalid archive digest or size')
    chunks = value['chunks']
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_CHUNKS:
        raise ValueError('Invalid transfer chunk count')
    for chunk in chunks:
        if (not isinstance(chunk, dict) or set(chunk) != {'blobSHA', 'sha256', 'bytes'}
                or not isinstance(chunk['blobSHA'], str) or not HEX40.fullmatch(chunk['blobSHA'])
                or not isinstance(chunk['sha256'], str) or not HEX64.fullmatch(chunk['sha256'])
                or type(chunk['bytes']) is not int or not 0 < chunk['bytes'] <= MAX_CHUNK_BYTES):
            raise ValueError('Invalid pinned Git blob identity, digest or size')
    if sum(chunk['bytes'] for chunk in chunks) != value['archiveBytes']:
        raise ValueError('Chunk sizes do not equal the exact archive size')
    scopes = value['scopes']
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= len(intake.COPY) * len(intake.COLLECTIONS):
        raise ValueError('Transfer needs supported prepared scopes')
    for scope in scopes:
        validate_scope(scope)
    if len({key(scope) for scope in scopes}) != len(scopes):
        raise ValueError('Duplicate transfer scope')
    return value


def scope_files(scope):
    docx = 'Iman_Companion_' + scope['language'] + '_' + scope['collection'] + '.docx'
    pdf = str(Path(docx).with_suffix('.pdf'))
    prepared = [docx, pdf, docx + '.reader-checks.json', 'index.json',
                'source-manifest.json', 'prepared-snapshot.json']
    candidate = [docx, pdf, docx + '.word-layout.json', 'word-proof/Word-visual-proof.pdf']
    return prepared, candidate


def public_metadata(value):
    """Reject machine paths before upload without rewriting accepted evidence."""
    if isinstance(value, dict):
        if 'localArtifacts' in value:
            raise ValueError('Use the committed Actions preparation; localArtifacts are not public evidence')
        for item in value.values():
            public_metadata(item)
    elif isinstance(value, list):
        for item in value:
            public_metadata(item)
    elif isinstance(value, str) and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\|file://|/)', value, re.I):
        raise ValueError('Absolute machine paths are not permitted in transfer metadata')


def public_payload(bundle, require_inventory=True):
    bundle, manifest, files, _ = intake.validate_bundle(bundle, require_inventory=require_inventory)
    allowed = {'bundle.json'} | ({intake.INVENTORY} if intake.INVENTORY in files else set())
    declarations = []
    for scope in manifest['scopes']:
        prepared, candidate = scope_files(scope)
        required = [scope['handoff'], scope['acceptance']]
        required += [scope['prepared'] + '/' + name for name in prepared]
        required += [scope['candidate'] + '/' + name for name in candidate]
        allowed.update(required)
        for relative in required:
            file = safe_file(bundle, relative)
            if relative.endswith('.json') and not relative.endswith('.reader-checks.json'):
                public_metadata(read_json(file))
        handoff = read_json(safe_file(bundle, scope['handoff']))
        declaration = {name: handoff.get(name) for name in SCOPE_KEYS}
        validate_scope(declaration)
        if handoff.get('schema') != 'iman-prepared-book-handoff-v1' or key(declaration) != key(scope):
            raise ValueError('Bundle handoff scope differs from its manifest')
        declarations.append(declaration)
    if set(files) != allowed:
        raise ValueError('Transfer contains files beyond the minimal public evidence inventory')
    return manifest, declarations


def check_local_evidence(root, bundle, scope):
    from finalize_prepared import plan, _acceptance
    from word_layout_check import verify
    prepared = bundle / scope['prepared']
    candidate = bundle / scope['candidate']
    handoff = read_json(safe_file(bundle, scope['handoff']))
    if plan(root, prepared) != handoff:
        raise ValueError('Local handoff is stale or differs from the committed preparation')
    _acceptance(handoff, candidate, read_json(safe_file(bundle, scope['acceptance'])))
    docx = scope_files(scope)[1][0]
    verify(candidate / docx, candidate / (docx + '.word-layout.json'))


def prepare(root, bundle, out, repo, chunk_bytes=DEFAULT_CHUNK_BYTES, verifier=None):
    """Copy only required evidence; produce exact upload chunks and their manifest."""
    root, bundle, out = Path(root).resolve(), Path(bundle).resolve(), Path(out).absolute()
    if os.path.lexists(out) or out.resolve().is_relative_to(bundle):
        raise ValueError('Use a new output directory outside the review bundle')
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_CHUNK_BYTES:
        raise ValueError('Invalid requested chunk size')
    manifest_file = safe_file(bundle, 'bundle.json')
    original = manifest_file.read_bytes()
    manifest = intake.manifest_bytes(original)
    verifier = verifier or check_local_evidence
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent, prefix='.connector-prepare-') as temporary:
        staging = Path(temporary)
        minimal = staging / 'evidence'
        minimal.mkdir()
        (minimal / 'bundle.json').write_bytes(original)
        for scope in manifest['scopes']:
            prepared, candidate = scope_files(scope)
            paths = [scope['handoff'], scope['acceptance']]
            paths += [scope['prepared'] + '/' + name for name in prepared]
            paths += [scope['candidate'] + '/' + name for name in candidate]
            for relative in paths:
                source = safe_file(bundle, relative)
                target = minimal / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        _, declarations = public_payload(minimal, require_inventory=False)
        for scope in manifest['scopes']:
            verifier(root, minimal, scope)
        archive = staging / 'finalized-books.zip'
        packed = intake.pack(minimal, archive)
        if packed['bytes'] > MAX_ARCHIVE_BYTES:
            raise ValueError('Candidate archive exceeds connector transport size limit')
        transfer = {'schema': SCHEMA, 'repository': repo, 'archiveSHA256': packed['sha256'],
                    'archiveBytes': packed['bytes'], 'chunks': [], 'scopes': declarations}
        chunks = staging / 'chunks'
        chunks.mkdir()
        with archive.open('rb') as stream:
            while raw := stream.read(chunk_bytes):
                number = len(transfer['chunks'])
                if number >= MAX_CHUNKS:
                    raise ValueError('Candidate archive requires too many chunks')
                transfer['chunks'].append({'blobSHA': git_blob_sha(raw), 'sha256': sha(raw), 'bytes': len(raw)})
                (chunks / f'{number:04d}.b64').write_bytes(base64.b64encode(raw))
        validate_manifest(transfer, repo)
        name = transfer['archiveSHA256'] + '.json'
        (staging / name).write_bytes(intake.encoded(transfer))
        shutil.rmtree(minimal)
        out.mkdir()
        try:
            for child in staging.iterdir():
                child.rename(out / child.name)
        except BaseException:
            shutil.rmtree(out)
            raise
    return {'manifest': str(out / name), 'archiveSHA256': transfer['archiveSHA256'],
            'archiveBytes': transfer['archiveBytes'], 'chunks': len(transfer['chunks']),
            'scopes': len(declarations), 'commitPath': INTAKE + '/' + name}


def fetch_blob(repo, chunk):
    """GET a bounded response from this repository only; never use a supplied URL."""
    endpoint = f'repos/{repo}/git/blobs/{chunk["blobSHA"]}'
    limit = chunk['bytes'] * 2 + 16384
    with TemporaryFile() as errors:
        process = subprocess.Popen(['gh', 'api', '--hostname', 'github.com', '--method', 'GET', endpoint],
                                   stdout=subprocess.PIPE, stderr=errors)
        timer = Timer(90, process.kill)
        timer.start()
        try:
            response = process.stdout.read(limit + 1)
            if len(response) > limit:
                raise ValueError('Git blob response exceeded its declared size bound')
            if process.wait(timeout=5):
                raise ValueError('Pinned Git blob could not be read from the workflow repository')
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
    try:
        value = json.loads(response.decode('utf8'), object_pairs_hook=intake._unique_object)
        if (not isinstance(value, dict) or value.get('sha') != chunk['blobSHA']
                or value.get('size') != chunk['bytes'] or value.get('encoding') != 'base64'
                or not isinstance(value.get('content'), str)):
            raise ValueError()
        encoded = value['content'].replace('\n', '').replace('\r', '')
        if len(encoded) != 4 * ((chunk['bytes'] + 2) // 3):
            raise ValueError()
        return base64.b64decode(encoded, validate=True)
    except (UnicodeError, ValueError, TypeError) as error:
        raise ValueError('Git blob response differs from its pinned identity or size') from error


def assemble(manifest, archive, fetcher=None):
    fetcher = fetcher or fetch_blob
    digest = hashlib.sha256()
    size = 0
    with Path(archive).open('xb') as destination:
        for chunk in manifest['chunks']:
            raw = fetcher(manifest['repository'], chunk)
            if (not isinstance(raw, bytes) or len(raw) != chunk['bytes']
                    or sha(raw) != chunk['sha256'] or git_blob_sha(raw) != chunk['blobSHA']):
                raise ValueError('Pinned Git blob content, size or hashes differ')
            size += len(raw)
            digest.update(raw)
            destination.write(raw)
    if size != manifest['archiveBytes'] or digest.hexdigest() != manifest['archiveSHA256']:
        raise ValueError('Ordered chunks do not match the exact candidate archive')


def read_consumed(root, digest, manifest):
    relative = HISTORY + '/' + digest + '.json'
    path = root / relative
    if not os.path.lexists(path):
        return {}
    receipt = read_json(safe_file(root, relative))
    if (not isinstance(receipt, dict)
            or set(receipt) != {'schema', 'manifestSHA256', 'archiveSHA256', 'repository', 'scopes'}
            or receipt.get('schema') != RECEIPT_SCHEMA or receipt.get('manifestSHA256') != digest
            or receipt.get('archiveSHA256') != manifest['archiveSHA256']
            or receipt.get('repository') != manifest['repository'] or not isinstance(receipt.get('scopes'), list)):
        raise ValueError('Consumed transfer receipt does not match its immutable manifest')
    declared = {key(scope): scope for scope in manifest['scopes']}
    result = {}
    for scope in receipt['scopes']:
        if not isinstance(scope, dict) or set(scope) != PUBLISHED_KEYS:
            raise ValueError('Invalid consumed scope receipt')
        identity = {name: scope[name] for name in SCOPE_KEYS}
        validate_scope(identity)
        if (declared.get(key(scope)) != identity or key(scope) in result
                or not all(isinstance(scope[name], str) and HEX64.fullmatch(scope[name]) for name in ('docxSHA256', 'pdfSHA256'))
                or not isinstance(scope['publicationCommit'], str) or not HEX40.fullmatch(scope['publicationCommit'])
                or not isinstance(scope['releaseTag'], str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', scope['releaseTag'])):
            raise ValueError('Consumed scope identity or published pair is invalid')
        result[key(scope)] = scope
    return result


def add_error(out, commit, relative, error, scope=None):
    report = intake._report(out, commit)
    message = re.sub(r'[A-Za-z]:[\\/]\S+', '[local path]', str(error))[:1500]
    record = {'manifest': relative, 'stage': 'connector-candidate-transfer', 'error': message}
    if scope:
        record.update({name: scope[name] for name in ('language', 'collection')})
    report.setdefault('finalizedIntakeErrors', []).append(record)
    intake._write_report(out, report)
    return record


def process(root, out, commit, repo, tag, fetcher=None, finalizer=None):
    root, out = Path(root).resolve(), Path(out).resolve()
    intake._report(out, commit)
    directory = root / INTAKE
    if not directory.exists():
        return {'finalized': [], 'failed': [], 'skipped': 0}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Symlinked connector intake directory is not permitted')
    paths = sorted(directory.glob('*.json'))
    if len(paths) > MAX_MANIFESTS:
        raise ValueError('Too many connector manifests')
    queue_file = root / 'books/prepared-library.json'
    queue = read_json(safe_file(root, 'books/prepared-library.json')) if queue_file.exists() else {'entries': []}
    queued = {key(row): row for row in queue['entries']}
    result = {'finalized': [], 'failed': [], 'skipped': 0}
    pending = []
    claims = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            source = safe_file(root, relative)
            if source.stat().st_size > intake.MAX_JSON_BYTES:
                raise ValueError('Connector manifest exceeds its size limit')
            raw = source.read_bytes()
            manifest = validate_manifest(intake.json_bytes(raw, 'connector manifest'), repo)
            if path.name != manifest['archiveSHA256'] + '.json':
                raise ValueError('Manifest filename must be its exact archive SHA256')
            digest = sha(raw)
            consumed = read_consumed(root, digest, manifest)
            scopes = []
            for scope in manifest['scopes']:
                if key(scope) in consumed:
                    result['skipped'] += 1
                    continue
                row = queued.get(key(scope), {})
                if (row.get('sourceCommit') != scope['sourceCommit']
                        or row.get('inputFingerprint') != scope['inputFingerprint']
                        or row.get('state') != 'prepared-awaiting-release-qc'
                        or row.get('releaseVerified') is not False):
                    result['failed'].append(add_error(out, commit, relative, 'Transfer no longer matches the current preparation queue', scope))
                    continue
                scopes.append(scope)
                claims.setdefault(key(scope), []).append(relative)
            if scopes:
                pending.append((relative, raw, manifest, digest, scopes))
        except Exception as error:
            result['failed'].append(add_error(out, commit, relative, error))
    if finalizer is None:
        from finalize_prepared import finalize
        finalizer = finalize
    for relative, raw, manifest, digest, scopes in pending:
        eligible = []
        for scope in scopes:
            if len(claims[key(scope)]) != 1:
                result['failed'].append(add_error(out, commit, relative, 'Conflicting pending transfers claim the same prepared scope', scope))
            else:
                eligible.append(scope)
        if not eligible:
            continue
        try:
            with TemporaryDirectory(prefix='iman-connector-transfer-') as temporary:
                temporary = Path(temporary)
                archive, bundle = temporary / 'candidate.zip', temporary / 'bundle'
                assemble(manifest, archive, fetcher)
                intake.extract(archive, manifest['archiveSHA256'], bundle)
                bundle_manifest, declarations = public_payload(bundle)
                if sorted(declarations, key=key) != sorted(manifest['scopes'], key=key):
                    raise ValueError('Archive handoff identities differ from the committed declarations')
                if safe_file(root, relative).read_bytes() != raw:
                    raise ValueError('Committed transfer manifest changed during retrieval')
                by_scope = {key(scope): scope for scope in bundle_manifest['scopes']}
                for scope in eligible:
                    selected = by_scope[key(scope)]
                    try:
                        paths = [bundle / selected[field] for field in intake.PATH_FIELDS]
                        finalized = finalizer(root, *paths, out, commit, repo, tag)
                        if ({name: finalized.get(name) for name in SCOPE_KEYS} != scope
                                or finalized.get('state') != 'verified-release-candidate'):
                            raise ValueError('Finalizer returned a different candidate identity')
                        report = intake._report(out, commit)
                        report.setdefault('connectorFinalizedCandidates', []).append({
                            'manifestPath': relative, 'manifestSHA256': digest, 'candidate': finalized})
                        intake._write_report(out, report)
                        result['finalized'].append({'language': scope['language'], 'collection': scope['collection']})
                    except Exception as error:
                        result['failed'].append(add_error(out, commit, relative, error, scope))
        except Exception as error:
            result['failed'].append(add_error(out, commit, relative, error))
    return result


def record_published(root, out, entries, repo):
    """Called only by the sole publisher after merge verified remote assets."""
    root, out = Path(root).resolve(), Path(out).resolve()
    report = json.loads((out / 'build-report.json').read_bytes())
    published = {key(entry['book']): entry for entry in entries}
    for item in report.get('connectorFinalizedCandidates', []):
        relative, digest, candidate = item['manifestPath'], item['manifestSHA256'], item['candidate']
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError('Invalid finalized transfer manifest identity')
        raw = safe_file(root, relative).read_bytes()
        manifest = validate_manifest(intake.json_bytes(raw, 'connector manifest'), repo)
        if relative != INTAKE + '/' + manifest['archiveSHA256'] + '.json' or sha(raw) != digest:
            raise ValueError('Transfer manifest changed before publication')
        entry = published.get(key(candidate))
        if entry is None:
            raise ValueError('Finalized transfer has no remotely verified published pair')
        book = entry['book']
        final = read_json(safe_file(out, candidate['folder'] + '/finalization-receipt.json'))
        if final != candidate or any(book.get(name) != candidate.get(name) for name in ('language', 'collection', 'sourceCommit')):
            raise ValueError('Transfer finalization receipt differs from the published candidate')
        if book['sha256'] != candidate['docxSHA256'] or book['pdfSha256'] != candidate['pdfSHA256']:
            raise ValueError('Published pair differs from the consumed transfer hashes')
        identity = {name: candidate[name] for name in SCOPE_KEYS}
        if identity not in manifest['scopes']:
            raise ValueError('Published scope was not declared by the transfer')
        consumed = read_consumed(root, digest, manifest)
        record = {**identity, 'docxSHA256': book['sha256'], 'pdfSHA256': book['pdfSha256'],
                  'releaseTag': entry['releaseTag'], 'publicationCommit': candidate['publicationCommit']}
        if key(record) in consumed and consumed[key(record)] != record:
            raise ValueError('An immutable consumed scope cannot be replaced')
        consumed[key(record)] = record
        receipt = {'schema': RECEIPT_SCHEMA, 'manifestSHA256': digest, 'archiveSHA256': manifest['archiveSHA256'],
                   'repository': manifest['repository'], 'scopes': sorted(consumed.values(), key=key)}
        directory = root / HISTORY
        if directory.is_symlink():
            raise ValueError('Symlinked transfer history directory is not permitted')
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (digest + '.json')
        if target.is_symlink():
            raise ValueError('Symlinked transfer receipt is not permitted')
        target.write_bytes(intake.encoded(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    packing = actions.add_parser('prepare', help='Check and minimize supplied evidence before public blob upload')
    for name in ('root', 'bundle', 'out'):
        packing.add_argument('--' + name, type=Path, required=True)
    packing.add_argument('--repo', required=True)
    packing.add_argument('--chunk-bytes', type=int, default=DEFAULT_CHUNK_BYTES)
    processing = actions.add_parser('process', help='Retrieve pinned blobs and invoke the existing checked finalizer')
    for name in ('root', 'out'):
        processing.add_argument('--' + name, type=Path, required=True)
    for name in ('commit', 'repo', 'tag'):
        processing.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            result = prepare(args.root, args.bundle, args.out, args.repo, args.chunk_bytes)
        else:
            result = process(args.root, args.out, args.commit, args.repo, args.tag)
    except Exception as error:
        parser.exit(1, 'Connector candidate transfer rejected: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
