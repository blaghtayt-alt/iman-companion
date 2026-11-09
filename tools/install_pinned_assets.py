"""Install the unchanged book-asset pins using authenticated GitHub API transport.

The helper stays outside books/ so transport fixes do not invalidate prepared
editions. It uses existing gh authentication; it creates no token or permission.
"""
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile

REPOSITORY = 'blaghtayt-alt/iman-companion'
PREFIX = 'https://github.com/' + REPOSITORY + '/releases/download/'
DESTINATIONS = {'books/assets/covers', 'books/assets/fonts'}
ATTEMPTS = 3
METADATA_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 180
MAX_EXPANDED_BYTES = 2_000_000_000


class TransportError(ValueError):
    pass


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def confined(root, path):
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Asset destination contains a symlink')
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError('Asset destination escapes the repository')
    return path


def archive_specs(root):
    manifest = root / 'books/assets.json'
    confined(root, manifest)
    source = manifest.read_bytes()
    conf = json.loads(source)
    if not isinstance(conf, dict) or not isinstance(conf.get('archives'), list) or not conf['archives']:
        raise ValueError('Invalid pinned book assets manifest')
    specs, seen = [], set()
    for entry in conf['archives']:
        if not isinstance(entry, dict) or set(entry) != {'url', 'sha256', 'destination'}:
            raise ValueError('Invalid archive declaration')
        url, expected, destination = (entry[name] for name in ('url', 'sha256', 'destination'))
        if not isinstance(url, str) or not url.startswith(PREFIX):
            raise ValueError('Archive must use the existing repository release URL')
        parsed = urlsplit(url)
        if parsed.netloc != 'github.com' or parsed.query or parsed.fragment:
            raise ValueError('Unexpected archive URL components')
        parts = url[len(PREFIX):].split('/')
        if len(parts) != 2 or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', unquote(part)) for part in parts):
            raise ValueError('Archive URL must identify one exact release asset')
        tag, name = map(unquote, parts)
        if not name.endswith('.zip') or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Expected a ZIP archive with an exact SHA256 pin')
        if destination not in DESTINATIONS or destination in seen:
            raise ValueError('Unexpected or duplicate asset destination')
        seen.add(destination)
        target = confined(root, root / destination)
        if target.exists() and not target.is_dir():
            raise ValueError('Asset destination is not a directory')
        specs.append({**entry, 'tag': tag, 'name': name})
    return source, specs


def metadata_asset(spec, data):
    if not isinstance(data, dict) or data.get('tag_name') != spec['tag'] or data.get('draft') is not False or data.get('prerelease') is not False:
        raise ValueError('Pinned asset release identity changed')
    rows = [row for row in data.get('assets', []) if row.get('name') == spec['name']]
    if len(rows) != 1:
        raise ValueError('Missing or ambiguous exact pinned asset')
    asset = rows[0]
    identifier = asset.get('id')
    if (type(identifier) is not int or identifier < 1 or asset.get('state') != 'uploaded'
            or type(asset.get('size')) is not int or asset['size'] < 1
            or asset.get('digest') != 'sha256:' + spec['sha256']
            or asset.get('browser_download_url') != spec['url']
            or asset.get('url') != f'https://api.github.com/repos/{REPOSITORY}/releases/assets/{identifier}'):
        raise ValueError('Release asset metadata differs from its unchanged pin')
    return asset


def gh(runner, arguments, timeout, output=None):
    kwargs = {'stderr': subprocess.PIPE, 'timeout': timeout, 'check': False}
    kwargs['stdout'] = output if output is not None else subprocess.PIPE
    try:
        result = runner(['gh', 'api', '--method', 'GET', *arguments], **kwargs)
    except (subprocess.TimeoutExpired, OSError) as error:
        raise TransportError('GitHub API transport did not complete') from error
    if result.returncode:
        # gh stderr can contain temporary redirect URLs. Do not print it.
        raise TransportError('GitHub API download request failed')
    return result.stdout


def fetch_archive(spec, folder, runner, pause):
    for attempt in range(1, ATTEMPTS + 1):
        archive = folder / f'archive-attempt-{attempt}.zip'
        try:
            raw = gh(runner, [f'repos/{REPOSITORY}/releases/tags/{spec["tag"]}'], METADATA_TIMEOUT)
            asset = metadata_asset(spec, json.loads(raw))
            endpoint = f'repos/{REPOSITORY}/releases/assets/{asset["id"]}'
            with archive.open('xb') as output:
                gh(runner, [endpoint, '-H', 'Accept: application/octet-stream'], DOWNLOAD_TIMEOUT, output)
        except TransportError:
            if attempt == ATTEMPTS:
                raise TransportError(f'Pinned asset download failed after {ATTEMPTS} attempts: {spec["name"]}') from None
            pause(attempt)
            continue
        if archive.stat().st_size != asset['size'] or digest(archive) != spec['sha256']:
            raise ValueError('Downloaded asset size or SHA256 differs from the unchanged pin')
        return archive, attempt, asset['size']
    raise AssertionError('Unreachable retry state')


def preflight_archive(archive):
    """Validate the entire member inventory before extracting any member."""
    members, seen, total = [], {}, 0
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            name = member.filename
            plain = name[:-1] if member.is_dir() else name
            if not plain or '\\' in name or ':' in name or '\0' in name or any(part in ('', '.', '..') for part in plain.split('/')):
                raise ValueError('Unsafe asset archive member path')
            path = PurePosixPath(plain)
            if path.is_absolute():
                raise ValueError('Asset archive member is absolute')
            key = path.as_posix().casefold()
            kind = stat.S_IFMT(member.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                raise ValueError('Asset archive contains a symlink, special or encrypted member')
            if key in seen:
                raise ValueError('Duplicate asset archive member path')
            seen[key] = member.is_dir()
            total += member.file_size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError('Asset archive expands beyond its bounded installation size')
            members.append((member.filename, path.as_posix(), member.is_dir()))
        for _, name, _ in members:
            if any(parent.as_posix().casefold() in seen and not seen[parent.as_posix().casefold()]
                   for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
                raise ValueError('Archive file conflicts with a parent directory')
    if not members or all(is_directory for _, _, is_directory in members):
        raise ValueError('Asset archive contains no files')
    return members


def install(root, runner=None, pause=None):
    root = Path(root).resolve()
    runner = runner or subprocess.run
    pause = pause or time.sleep
    manifest, specs = archive_specs(root)
    plans, report = [], []
    # Stage all verified archives on the destination filesystem. Hash, metadata,
    # ZIP CRC and path failures leave existing asset files untouched.
    with TemporaryDirectory(prefix='.pinned-book-assets-', dir=root) as temporary:
        temporary = Path(temporary)
        for index, spec in enumerate(specs):
            folder = temporary / str(index)
            folder.mkdir()
            archive, attempts, size = fetch_archive(spec, folder, runner, pause)
            members = preflight_archive(archive)
            target = confined(root, root / spec['destination'])
            stage = folder / 'extracted'
            with zipfile.ZipFile(archive) as package:
                for source_name, relative, is_directory in members:
                    destination = confined(root, target / relative)
                    if destination.exists() and (destination.is_dir() != is_directory):
                        raise ValueError('Existing asset path has a conflicting type')
                    for parent in destination.parents:
                        if parent == root:
                            break
                        if parent.exists() and not parent.is_dir():
                            raise ValueError('Asset destination parent is not a directory')
                    staged = stage / relative
                    if is_directory:
                        staged.mkdir(parents=True, exist_ok=True)
                    else:
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        with package.open(source_name) as source, staged.open('xb') as output:
                            shutil.copyfileobj(source, output)
                        plans.append((staged, destination))
            report.append({'name': spec['name'], 'sha256': spec['sha256'], 'bytes': size,
                           'attempts': attempts, 'files': sum(not directory for _, _, directory in members)})
        if (root / 'books/assets.json').read_bytes() != manifest:
            raise ValueError('Asset pins changed during installation')
        for _, destination in plans:
            confined(root, destination)
        for staged, destination in plans:
            destination.parent.mkdir(parents=True, exist_ok=True)
            confined(root, destination)
            os.replace(staged, destination)
    return {'archives': report, 'pinsUnchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.root)))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, 'Pinned asset installation stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
