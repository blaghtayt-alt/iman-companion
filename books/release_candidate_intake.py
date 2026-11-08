"""Transport finalized desktop candidates to the existing checked publisher.

Packing preserves supplied evidence byte for byte. It never creates an approval,
changes a release declaration, or publishes a release. Extraction requires an
out-of-band exact archive SHA256 and an exact inventory of the payload files.
"""
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, NamedTemporaryFile
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import zipfile

from download_tables import COLLECTIONS, COPY

SCHEMA = 'iman-finalized-book-intake-v1'
FILES_SCHEMA = 'iman-finalized-book-intake-files-v1'
MANIFEST = 'bundle.json'
INVENTORY = 'bundle-files.json'
MAX_BYTES = 2 * 1024 ** 3
MAX_FILES = 10000
MAX_JSON_BYTES = 4 * 1024 ** 2
MAX_CENTRAL_BYTES = 8 * 1024 ** 2
CHUNK = 1024 ** 2
PATH_FIELDS = ('prepared', 'candidate', 'handoff', 'acceptance')
HASH = re.compile(r'[a-f0-9]{64}\Z')
RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{n}' for n in range(1, 10)), *(f'LPT{n}' for n in range(1, 10))}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def json_bytes(raw, label):
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError(label + ' exceeds the JSON metadata limit')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid UTF-8 JSON: ' + label) from error


def safe_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or len(value.encode('utf8')) > 4096):
        raise ValueError('Unsafe bundle path: ' + repr(value))
    pieces = value.split('/')
    if any(piece in ('', '.', '..') or len(piece.encode('utf8')) > 255
           or piece.endswith((' ', '.')) or piece.split('.', 1)[0].upper() in RESERVED_NAMES for piece in pieces):
        raise ValueError('Bundle paths must be confined forward-slash relative paths: ' + value)
    return PurePosixPath(value)


def _under(path, parent):
    return path == parent or parent in path.parents


def manifest_bytes(raw):
    manifest = json_bytes(raw, MANIFEST)
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'scopes'} or manifest.get('schema') != SCHEMA:
        raise ValueError('Invalid finalized-candidate bundle schema')
    scopes = manifest['scopes']
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= len(COPY) * len(COLLECTIONS):
        raise ValueError('A bundle needs one or more supported book scopes')
    seen = set()
    roots = []
    for scope in scopes:
        if not isinstance(scope, dict) or set(scope) != {'language', 'collection', *PATH_FIELDS}:
            raise ValueError('Each scope needs its language, collection, prepared, candidate, handoff and acceptance')
        language, collection = scope['language'], scope['collection']
        if not isinstance(language, str) or not isinstance(collection, str) or language not in COPY or collection not in COLLECTIONS:
            raise ValueError('Unsupported bundle language or collection')
        key = (language, collection)
        if key in seen:
            raise ValueError('Duplicate bundle scope: ' + language + '/' + collection)
        seen.add(key)
        for field in PATH_FIELDS:
            path = safe_path(scope[field])
            lowered = PurePosixPath(path.as_posix().casefold())
            if lowered in {PurePosixPath(MANIFEST), PurePosixPath(INVENTORY)}:
                raise ValueError('A scope cannot use the bundle metadata paths')
            if any(_under(lowered, previous) or _under(previous, lowered) for previous in roots):
                raise ValueError('Bundle scope paths overlap: ' + scope[field])
            roots.append(lowered)
    return manifest


def _allowed_payload(manifest, paths):
    """Reject unrelated uploads and require every declared directory/file."""
    directories = [safe_path(scope[field]) for scope in manifest['scopes'] for field in ('prepared', 'candidate')]
    documents = {safe_path(scope[field]) for scope in manifest['scopes'] for field in ('handoff', 'acceptance')}
    files = {safe_path(path) for path in paths}
    for document in documents:
        if document not in files:
            raise ValueError('Missing declared evidence file: ' + document.as_posix())
    for directory in directories:
        if not any(path != directory and _under(path, directory) for path in files):
            raise ValueError('Missing or empty declared scope directory: ' + directory.as_posix())
    for path in files:
        if path in {PurePosixPath(MANIFEST), PurePosixPath(INVENTORY)} or path in documents:
            continue
        if not any(path != directory and _under(path, directory) for directory in directories):
            raise ValueError('Unreferenced file in bundle: ' + path.as_posix())


def _regular(path):
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Bundle payload must be a regular file: ' + str(path))


def _directory(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Bundle root must be an existing non-symlink directory')
    return path.resolve()


def _new_output(path):
    path = Path(path).absolute()
    if os.path.lexists(path):
        raise FileExistsError('Output already exists: ' + str(path))
    return path


def _file_hash(path, limit=MAX_BYTES):
    _regular(path)
    result = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while raw := stream.read(CHUNK):
            size += len(raw)
            if size > limit:
                raise ValueError('Bundle exceeds its uncompressed size limit')
            result.update(raw)
    return {'sha256': result.hexdigest(), 'bytes': size}


def _walk(bundle):
    files, identities, directories = {}, {}, []
    for parent, children, names in os.walk(bundle, followlinks=False):
        for name in children + names:
            path = Path(parent) / name
            relative = path.relative_to(bundle).as_posix()
            safe_path(relative)
            key = relative.casefold()
            if key in identities:
                raise ValueError('Duplicate or case-colliding bundle path: ' + relative)
            identities[key] = relative
            if path.is_symlink():
                raise ValueError('Symlinks are not permitted in a candidate bundle: ' + relative)
            if path.is_dir():
                directories.append(relative)
            else:
                _regular(path)
                files[relative] = path
            if len(identities) > MAX_FILES:
                raise ValueError('Too many bundle entries')
    for directory in directories:
        if not any(name.startswith(directory + '/') for name in files):
            raise ValueError('Empty or unreferenced bundle directory: ' + directory)
    return files


def _inventory(raw, names):
    inventory = json_bytes(raw, INVENTORY)
    if not isinstance(inventory, dict) or set(inventory) != {'schema', 'files'} or inventory.get('schema') != FILES_SCHEMA:
        raise ValueError('Invalid bundle file inventory schema')
    records = inventory['files']
    if not isinstance(records, dict) or set(records) != set(names) - {INVENTORY}:
        raise ValueError('Bundle file inventory does not match the exact payload')
    total = 0
    for name, record in records.items():
        safe_path(name)
        if (not isinstance(record, dict) or set(record) != {'sha256', 'bytes'}
                or not isinstance(record['sha256'], str) or not HASH.fullmatch(record['sha256'])
                or type(record['bytes']) is not int or record['bytes'] < 0):
            raise ValueError('Invalid file digest or size: ' + name)
        total += record['bytes']
    if total + len(raw) > MAX_BYTES:
        raise ValueError('Bundle exceeds its uncompressed size limit')
    return records


def validate_bundle(bundle, require_inventory=True):
    bundle = _directory(Path(bundle))
    files = _walk(bundle)
    if MANIFEST not in files:
        raise ValueError('Missing ' + MANIFEST)
    if files[MANIFEST].stat().st_size > MAX_JSON_BYTES:
        raise ValueError('Bundle manifest is too large')
    manifest = manifest_bytes(files[MANIFEST].read_bytes())
    _allowed_payload(manifest, files)
    records, total = {}, 0
    for name, file in sorted(files.items()):
        if name == INVENTORY:
            continue
        record = _file_hash(file, MAX_BYTES - total)
        total += record['bytes']
        records[name] = record
    if require_inventory:
        if INVENTORY not in files or files[INVENTORY].stat().st_size > MAX_JSON_BYTES:
            raise ValueError('Missing or oversized ' + INVENTORY)
        expected = _inventory(files[INVENTORY].read_bytes(), files)
        if records != expected:
            raise ValueError('A candidate bundle file changed after packing')
    return bundle, manifest, files, records


def _zip_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info._compresslevel = 9
    return info


def pack(bundle, out):
    """Write a new deterministic ZIP without changing source evidence."""
    out = _new_output(out)
    bundle, manifest, files, records = validate_bundle(bundle, require_inventory=False)
    if out.resolve().is_relative_to(bundle):
        raise ValueError('Archive output must be outside the bundle directory')
    hashes = encoded({'schema': FILES_SCHEMA, 'files': records})
    if (len(records) + 1 > MAX_FILES or len(hashes) > MAX_JSON_BYTES
            or sum(record['bytes'] for record in records.values()) + len(hashes) > MAX_BYTES):
        raise ValueError('Bundle exceeds its metadata or uncompressed size limit')
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with NamedTemporaryFile(dir=out.parent, prefix='.candidate-', suffix='.zip', delete=False) as temporary:
            staged = Path(temporary.name)
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted([*records, INVENTORY]):
                info = _zip_info(name)
                if name == INVENTORY:
                    archive.writestr(info, hashes)
                    continue
                _regular(files[name])
                info.file_size = records[name]['bytes']
                checked, size = hashlib.sha256(), 0
                with files[name].open('rb') as source, archive.open(info, 'w') as target:
                    while raw := source.read(CHUNK):
                        size += len(raw)
                        if size > records[name]['bytes']:
                            raise ValueError('Source file changed during packing: ' + name)
                        checked.update(raw)
                        target.write(raw)
                if {'sha256': checked.hexdigest(), 'bytes': size} != records[name]:
                    raise ValueError('Source file changed during packing: ' + name)
        with staged.open('rb') as checked_archive:
            _archive_limits(checked_archive)
            with zipfile.ZipFile(checked_archive) as archive:
                _zip_entries(archive)
        receipt = _file_hash(staged, MAX_BYTES + MAX_CENTRAL_BYTES)
        # Linking installs a completely written file and cannot replace an existing output.
        os.link(staged, out)
        return {'archive': str(out), **receipt, 'files': len(records), 'scopes': len(manifest['scopes'])}
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                # A cleanup error must not misreport a completely installed ZIP as failed.
                pass


def _archive_limits(stream):
    """Bound central-directory allocation before ZipFile parses entry metadata."""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if size > MAX_BYTES + MAX_CENTRAL_BYTES:
        raise ValueError('Candidate archive exceeds its size limit')
    stream.seek(max(0, size - 65557))
    tail = stream.read()
    position = tail.rfind(b'PK\x05\x06')
    if position < 0 or position + 22 > len(tail):
        raise ValueError('Missing ZIP end record')
    _, disk, central_disk, disk_count, count, central_size, central_offset, comment_size = struct.unpack(
        '<4s4H2LH', tail[position:position + 22])
    if position + 22 + comment_size != len(tail) or disk or central_disk or disk_count != count:
        raise ValueError('Unsupported multipart or ambiguous ZIP archive')
    if count == 65535 or central_size == 0xffffffff or central_offset == 0xffffffff:
        locator_position = size - len(tail) + position - 20
        if locator_position < 0:
            raise ValueError('Missing ZIP64 locator')
        stream.seek(locator_position)
        signature, disk64, offset, disks = struct.unpack('<4sLQL', stream.read(20))
        if signature != b'PK\x06\x07' or disk64 or disks != 1 or offset > locator_position - 56:
            raise ValueError('Invalid ZIP64 locator')
        stream.seek(offset)
        signature, record_size, _, _, disk, central_disk, disk_count, count, central_size, central_offset = struct.unpack(
            '<4sQ2H2L4Q', stream.read(56))
        if signature != b'PK\x06\x06' or record_size < 44 or disk or central_disk or disk_count != count:
            raise ValueError('Invalid ZIP64 end record')
    if count > MAX_FILES or central_size > MAX_CENTRAL_BYTES or central_offset + central_size > size:
        raise ValueError('ZIP metadata exceeds its entry or size limit')
    stream.seek(0)


def _zip_entries(archive):
    entries, folded, total = {}, set(), 0
    if len(archive.infolist()) > MAX_FILES:
        raise ValueError('Too many ZIP entries')
    for info in archive.infolist():
        if info.orig_filename != info.filename:
            raise ValueError('Ambiguous ZIP filename')
        name = info.filename[:-1] if info.is_dir() else info.filename
        path = safe_path(name)
        key = name.casefold()
        if key in folded:
            raise ValueError('Duplicate or case-colliding ZIP path: ' + name)
        folded.add(key)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or (mode == stat.S_IFDIR and not info.is_dir()):
            raise ValueError('ZIP symlinks and special files are not allowed')
        if info.is_dir() and (mode == stat.S_IFREG or info.file_size):
            raise ValueError('Invalid ZIP directory entry')
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('Encrypted or unsupported ZIP entries are not allowed')
        total += info.file_size
        if total > MAX_BYTES or (info.file_size > CHUNK and info.file_size > max(1, info.compress_size) * 1000):
            raise ValueError('ZIP exceeds its uncompressed size or compression-ratio limit')
        entries[name] = info
        for parent in path.parents:
            previous = entries.get(parent.as_posix())
            if previous is not None and not previous.is_dir():
                raise ValueError('ZIP file and directory paths overlap')
    file_paths = {name.casefold() for name, info in entries.items() if not info.is_dir()}
    for name in entries:
        if any(parent.as_posix().casefold() in file_paths for parent in safe_path(name).parents):
            raise ValueError('ZIP file and directory paths overlap')
    return {name: info for name, info in entries.items() if not info.is_dir()}, entries


def _stream_hash(stream):
    stream.seek(0)
    result = hashlib.sha256()
    while raw := stream.read(CHUNK):
        result.update(raw)
    stream.seek(0)
    return result.hexdigest()


def extract(archive, sha256, out):
    """Validate a pinned ZIP into staging; install only a fully checked new directory."""
    if not isinstance(sha256, str) or not HASH.fullmatch(sha256):
        raise ValueError('An exact lowercase archive SHA256 is required')
    archive, out = Path(archive).absolute(), _new_output(out)
    _regular(archive)
    with archive.open('rb') as source:
        _archive_limits(source)
        if _stream_hash(source) != sha256:
            raise ValueError('Candidate archive SHA256 does not match the supplied value')
        with zipfile.ZipFile(source) as zipped:
            files, entries = _zip_entries(zipped)
            if MANIFEST not in files or INVENTORY not in files:
                raise ValueError('Candidate archive needs its manifest and file inventory')
            if any(files[name].file_size > MAX_JSON_BYTES for name in (MANIFEST, INVENTORY)):
                raise ValueError('Candidate archive metadata is too large')
            manifest = manifest_bytes(zipped.read(files[MANIFEST]))
            _allowed_payload(manifest, files)
            for name, info in entries.items():
                if info.is_dir() and not any(file.startswith(name + '/') for file in files):
                    raise ValueError('Empty or unreferenced ZIP directory: ' + name)
            expected = _inventory(zipped.read(files[INVENTORY]), files)
            if any(files[name].file_size != record['bytes'] for name, record in expected.items()):
                raise ValueError('ZIP file sizes differ from the pinned inventory')
            out.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=out.parent, prefix='.candidate-extract-') as temporary:
                staging = Path(temporary)
                total = 0
                for name, info in sorted(files.items()):
                    target = staging.joinpath(*safe_path(name).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    checked, size = hashlib.sha256(), 0
                    with zipped.open(info) as payload, target.open('xb') as destination:
                        while raw := payload.read(CHUNK):
                            size += len(raw)
                            total += len(raw)
                            if size > info.file_size or total > MAX_BYTES:
                                raise ValueError('ZIP expanded beyond its declared size')
                            checked.update(raw)
                            destination.write(raw)
                    if size != info.file_size:
                        raise ValueError('Truncated ZIP payload')
                    if name != INVENTORY and {'sha256': checked.hexdigest(), 'bytes': size} != expected[name]:
                        raise ValueError('Candidate file differs from its pinned digest: ' + name)
                if _stream_hash(source) != sha256:
                    raise ValueError('Candidate archive changed during extraction')
                # mkdir is exclusive. No existing output, even an empty directory, is replaced.
                out.mkdir()
                try:
                    for child in staging.iterdir():
                        child.rename(out / child.name)
                except BaseException:
                    shutil.rmtree(out)
                    raise
    return {'bundle': str(out), 'archiveSHA256': sha256,
            'manifestSHA256': expected[MANIFEST]['sha256'], 'files': len(expected), 'scopes': len(manifest['scopes'])}


def _report(out, commit):
    path = out / 'build-report.json'
    if path.exists():
        report = json_bytes(path.read_bytes(), 'build-report.json')
    else:
        report = {'sourceCommit': commit, 'built': [], 'prepared': [], 'unchanged': [], 'failed': []}
    if (not isinstance(report, dict) or report.get('sourceCommit') != commit
            or not all(isinstance(report.get(field), list) for field in ('built', 'failed'))):
        raise ValueError('Build report does not match this publication commit')
    return report


def _write_report(out, report):
    with NamedTemporaryFile(dir=out, prefix='.intake-report-', delete=False) as file:
        temporary = Path(file.name)
        file.write(encoded(report))
    try:
        os.replace(temporary, out / 'build-report.json')
    finally:
        temporary.unlink(missing_ok=True)


def process(root, bundle, out, commit, repo, tag, finalizer=None):
    """Isolate per-scope evidence failures; the finalizer alone adds built rows."""
    root, out = Path(root).resolve(), Path(out).resolve()
    bundle, manifest, _, records = validate_bundle(bundle)
    if out == bundle or out.is_relative_to(bundle) or bundle.is_relative_to(out):
        raise ValueError('Build output and candidate bundle must be separate directories')
    _report(out, commit)
    if finalizer is None:
        from finalize_prepared import finalize
        finalizer = finalize
    out.mkdir(parents=True, exist_ok=True)
    result = {'sourceCommit': commit, 'manifestSHA256': records[MANIFEST]['sha256'], 'finalized': [], 'failed': []}
    for scope in manifest['scopes']:
        try:
            paths = [bundle.joinpath(*safe_path(scope[field]).parts) for field in PATH_FIELDS]
            receipt = finalizer(root, *paths, out, commit, repo, tag)
            result['finalized'].append(receipt)
        except Exception as error:
            failure = {'language': scope['language'], 'collection': scope['collection'],
                       'stage': 'finalized-candidate-intake', 'error': str(error)}
            report = _report(out, commit)
            report['failed'].append(failure)
            _write_report(out, report)
            result['failed'].append(failure)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    packing = commands.add_parser('pack', help='Package supplied desktop evidence without creating approvals')
    packing.add_argument('--bundle', type=Path, required=True)
    packing.add_argument('--out', type=Path, required=True)
    extracting = commands.add_parser('extract', help='Verify an exact ZIP and install a new input directory')
    extracting.add_argument('--archive', type=Path, required=True)
    extracting.add_argument('--sha256', required=True)
    extracting.add_argument('--out', type=Path, required=True)
    processing = commands.add_parser('process', help='Validate finalized candidates for the existing publisher')
    for flag in ('root', 'bundle', 'out'):
        processing.add_argument('--' + flag, type=Path, required=True)
    for flag in ('commit', 'repo', 'tag'):
        processing.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'pack':
            result = pack(args.bundle, args.out)
        elif args.action == 'extract':
            result = extract(args.archive, args.sha256, args.out)
        else:
            result = process(args.root, args.bundle, args.out, args.commit, args.repo, args.tag)
    except (OSError, ValueError, zipfile.BadZipFile, struct.error) as error:
        parser.exit(1, 'Candidate intake rejected: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
