"""Run the genuine preparation path for two isolated, technical TEST articles.

The production checkout is read-only. This creates a fresh local Git repository
with no remote, copied unmodified production code and pinned assets, and only
the explicitly marked synthetic sources. It never invokes a publisher, Word,
or visual acceptance. The isolated scope retains its explicit release hold.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


FIXTURE = 'test-fixtures/automation-test-material'
TITLE = 'automation test material'
BODY = 'TEST'
SCOPE = {'language': 'en', 'collection': 'articles'}
REPOSITORY_LABEL = 'isolated-test/automation-test-material'
TAG = 'technical-test-only-not-published'
RELEASE_HOLD = 'Technical TEST-only fixture; public publication is not approved.'
PROTECTED = ('materials/catalog.json', 'books/reviewed-books.json',
             'books/published-library.json', 'books/published-bundles.json',
             'books/prepared-library.json', 'books/config.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    require(path.is_file() and not path.is_symlink(), 'Expected regular file: ' + str(path))
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode('utf8')


def read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'Duplicate JSON field: ' + key)
            value[key] = item
        return value
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encoded(value))


def safe_file(root, relative):
    relative = PurePosixPath(relative)
    require(not relative.is_absolute() and '..' not in relative.parts
            and str(relative) not in ('', '.'), 'Unsafe relative path')
    path = root.joinpath(*relative.parts)
    require(path.resolve().is_relative_to(root.resolve()), 'File escapes its root')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'Symlink is not allowed: ' + str(parent))
        if parent == root:
            break
    require(path.is_file(), 'Missing file: ' + str(path))
    return path


def environment():
    # No auth or inherited repository/action identity enters local subprocesses.
    value = {key: val for key, val in os.environ.items()
             if not key.startswith(('GIT_', 'GITHUB_', 'ACTIONS_'))
             and not re.search(r'TOKEN|PASSWORD|SECRET|CREDENTIAL', key, re.I)}
    value.update(PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1',
                 GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    return value


def command(args, cwd, *, env=None, timeout=120, capture=True):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env or environment(),
                          capture_output=capture, check=True, timeout=timeout).stdout


def git(root, *args):
    return command(['git', '-c', 'core.hooksPath=' + os.devnull,
                    '-c', 'commit.gpgSign=false', '-c', 'core.fsmonitor=false',
                    '-c', 'core.autocrlf=false', *args], root)


def tree_snapshot(root):
    names = [name.decode('utf8') for name in git(root, 'ls-files', '-z').split(b'\0') if name]
    files = {name: file_hash(safe_file(root, name)) for name in names}
    return {'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'tree': git(root, 'rev-parse', 'HEAD^{tree}').decode().strip(),
            'trackedFileCount': len(files), 'trackedFilesSHA256': digest(encoded(files)),
            'protectedFiles': {name: file_hash(safe_file(root, name)) for name in PROTECTED}}


def inventory(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), 'Symlink in artifact')
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = {'sha256': file_hash(path), 'bytes': path.stat().st_size}
    return result


def copy_exact(source, destination, expected=None):
    actual = file_hash(source)
    require(expected is None or actual == expected, 'Input hash differs: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as target:
        target.write(source.read_bytes())
    require(file_hash(destination) == actual, 'Copy differs')
    return actual


def validate_fixture(root):
    manifest_path = safe_file(root, FIXTURE + '/fixture-manifest.json')
    manifest = read(manifest_path)
    require(manifest.get('schema') == 'iman-automation-test-material-fixture-v1'
            and manifest.get('testOnly') is True and manifest.get('language') == 'en'
            and manifest.get('collection') == 'articles' and manifest.get('title') == TITLE
            and manifest.get('bodyText') == BODY, 'Wrong TEST fixture marker')
    isolation = manifest.get('isolation', {})
    require(isolation.get('required') is True and isolation.get('productionRegistration') is False
            and isolation.get('publicRelease') is False, 'Fixture must forbid production registration/release')
    rows = manifest.get('materials', [])
    require(len(rows) == 2 and [row['order'] for row in rows] == [1, 2]
            and [row['id'] for row in rows] == ['automation-test-material-001', 'automation-test-material-002'],
            'Expected exactly the two distinct ordered TEST materials')
    bindings = {FIXTURE + '/fixture-manifest.json': file_hash(manifest_path)}
    for row in rows:
        for kind in ('source', 'reader', 'review'):
            item = row[kind]
            require(item['path'].startswith(FIXTURE + '/' + {'source': 'sources', 'reader': 'readers', 'review': 'reviews'}[kind] + '/'),
                    'Fixture binding is outside its assigned directory')
            require(re.fullmatch('[a-f0-9]{64}', item['sha256']), 'Invalid fixture hash')
            require(file_hash(safe_file(root, item['path'])) == item['sha256'], 'Changed fixture: ' + item['path'])
            require(item['path'] not in bindings, 'Duplicate fixture path')
            bindings[item['path']] = item['sha256']
        reader, review = read(root / row['reader']['path']), read(root / row['review']['path'])
        material = {**SCOPE, 'id': row['id']}
        require(reader.get('testOnly') is True and reader.get('title') == TITLE
                and reader.get('id') == row['id'] and reader.get('order') == row['order']
                and reader.get('catalogBindings') == [material], 'Reader identity/title differs')
        blocks = [block for section in reader['sections'] for block in section['blocks']]
        require(blocks and all(block == {'kind': 'paragraph', 'text': BODY} for block in blocks),
                'TEST reader has extra body content')
        require(all(set(section) == {'blocks'} for section in reader['sections']), 'Unexpected section content')
        require(reader['readerTextSHA256'] == digest(''.join(block['text'] for block in blocks).encode()),
                'Reader text hash differs')
        require(review.get('schema') == 'iman-automation-test-technical-review-v1'
                and review.get('testOnly') is True and review.get('temporaryIsolationRequired') is True
                and review.get('decision') == 'approved' and review.get('wholeMaterial') is True
                and review.get('material') == material and review.get('sourceBindings') == [row['source']]
                and review.get('readerUnit') == row['reader']
                and review.get('readerTextSHA256') == reader['readerTextSHA256']
                and review.get('approvalId') and review.get('reviewer')
                and review.get('claims') and all(value is False for value in review['claims'].values()),
                'Missing truthful, exact, limited technical review')
    return manifest, bindings


def commit(root, message):
    git(root, 'add', '--', '.')
    git(root, 'commit', '-m', message)
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Read-only production checkout')
    parser.add_argument('--out', type=Path, required=True, help='Fresh owned directory outside input roots')
    parser.add_argument('--assets-root', type=Path, help='Optional already-installed pinned asset source')
    parser.add_argument('--uno-python', default='/usr/bin/python3')
    parser.add_argument('--stage-only', action='store_true', help='Validate/stage real intake; do not render')
    args = parser.parse_args()
    root, assets_root = args.root.resolve(), (args.assets_root or args.root).resolve()
    out = args.out.absolute()
    require(root.is_dir() and assets_root.is_dir(), 'Input roots must exist')
    require(not os.path.lexists(out), 'Output already exists; preserve it and choose a fresh path')
    for path in (out, *out.parents):
        require(not path.is_symlink(), 'Output has a symlink parent')
    out = out.resolve()
    require(all(not out.is_relative_to(parent) and not parent.is_relative_to(out)
                for parent in (root, assets_root)), 'Output must not overlap an input root')
    baseline = tree_snapshot(root)
    manifest, fixture_bindings = validate_fixture(root)
    conf = read(root / 'books/config.json')
    production_files = {}
    candidates = sorted((root / 'books').glob('*.py'))
    candidates += [root / 'books/requirements.txt', root / 'books/assets.json', root / 'tools/finalize_word_batch.py']
    for path in candidates:
        if path.name.startswith('test_'):
            continue
        relative = path.relative_to(root).as_posix()
        raw = git(root, 'show', baseline['head'] + ':' + relative)
        require(path.read_bytes() == raw, 'Production code differs from recorded HEAD: ' + relative)
        production_files[relative] = digest(raw)
    selected_fonts = ('Latin', 'Arabic', 'SymbolsLTR', 'SymbolsRTL', 'FiqhSymbols')
    pinned_assets = {item['path']: item['sha256'] for item in (conf['quranText'], conf['surahNames'])}
    for key in selected_fonts:
        for style, relative in conf['fonts'][key]['files'].items():
            pinned_assets[relative] = conf['fonts'][key]['sha256'][style]
    language = conf['languages']['en']
    pinned_assets[language['covers']['articles']] = language['coverHashes']['articles']
    asset_sources = {}
    for relative, wanted in pinned_assets.items():
        source_root = root if (root / relative).is_file() else assets_root
        source = safe_file(source_root, relative)
        require(file_hash(source) == wanted, 'Pinned production asset differs: ' + relative)
        asset_sources[relative] = source
    out.mkdir(parents=True)
    isolated = out / 'isolated-root'
    isolated.mkdir()
    try:
        for relative, wanted in production_files.items():
            copy_exact(root / relative, isolated / relative, wanted)
        for relative, wanted in fixture_bindings.items():
            copy_exact(root / relative, isolated / relative, wanted)
        for relative, wanted in pinned_assets.items():
            copy_exact(asset_sources[relative], isolated / relative, wanted)
        scoped = copy.deepcopy(conf)
        scoped['fonts'] = {key: scoped['fonts'][key] for key in selected_fonts}
        scoped['languages'] = {'en': scoped['languages']['en']}
        scoped['languages']['en']['titles']['articles'] = TITLE
        scoped['languages']['en']['covers'] = {'articles': language['covers']['articles']}
        scoped['languages']['en']['coverHashes'] = {'articles': language['coverHashes']['articles']}
        audio = {'schema': 'iman-material-audio-v1', 'playerBase': 'https://blaghtayt-alt.github.io/iman-companion/listen/', 'entries': []}
        write(isolated / 'materials/audio/registry.json', audio)
        scoped['audioRegistry'] = {'path': 'materials/audio/registry.json', 'sha256': digest(encoded(audio))}
        write(isolated / 'books/config.json', scoped)
        write(isolated / 'materials/catalog.json', {'schema': 'iman-material-catalog-v1', 'languages': ['en'],
              'scope': 'isolated technical TEST-only', 'notice': RELEASE_HOLD, 'entries': []})
        declaration = {**SCOPE, 'adapter': 'published-reader-units-v1', 'state': 'reviewed-current',
                       'scopePolicy': 'reviewed-source-edition-v1', 'sourceReviewBindings': [],
                       'automaticBuild': True, 'automaticRelease': False, 'requireActualWordLayout': True,
                       'releaseHold': RELEASE_HOLD}
        write(isolated / 'books/reviewed-books.json', {'schema': 'iman-reviewed-books-v1', 'books': [declaration]})
        write(isolated / 'books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': []})
        write(isolated / 'books/published-library.json', {'schema': 'iman-published-book-library-v1', 'entries': []})
        write(isolated / 'books/published-bundles.json', {'schema': 'iman-published-book-bundles-v1', 'languages': {}})
        write(isolated / 'ISOLATED-AUTOMATION-TEST.json', {'schema': 'iman-isolated-automation-test-root-v1',
              'testOnly': True, 'sourceProductionCommit': baseline['head'], 'scope': SCOPE,
              'publicPublicationApproved': False, 'releaseHold': RELEASE_HOLD})
        (isolated / '.gitignore').write_text('__pycache__/\n*.pyc\nbooks/.cache/\nbooks/manifest.json\nbooks/units/generated/\n', encoding='utf8')
        (isolated / 'README.md').write_text('# Isolated automation test\n\nTechnical TEST-only fixture. No public publication is approved.\n', encoding='utf8')
        git(isolated, 'init', '-b', 'technical-test')
        git(isolated, 'config', 'user.name', 'Automation TEST Fixture')
        git(isolated, 'config', 'user.email', 'automation-test@example.invalid')
        git(isolated, 'config', 'core.autocrlf', 'false')
        initial_commit = commit(isolated, 'Initialize isolated technical TEST-only source root')
        catalog_hash = file_hash(isolated / 'materials/catalog.json')
        for row in manifest['materials']:
            review = read(isolated / row['review']['path'])
            approval = {key: copy.deepcopy(review[key]) for key in
                        ('decision', 'wholeMaterial', 'approvalId', 'reviewer', 'material', 'readerTextSHA256')}
            approval['reviewArtifacts'] = [row['review']]
            approval['technicalTestOnly'] = True
            approval['publicPublicationApproval'] = False
            envelope = {'schema': 'iman-approved-material-publication-v1',
                        'expectedCatalogSHA256': catalog_hash,
                        'catalogEntry': {**SCOPE, 'id': row['id'], 'title': TITLE,
                                         'json': row['source']['path'], 'current': True, 'testOnly': True},
                        'sourceBindings': [row['source']], 'canonicalOrder': row['order'],
                        'readerUnit': row['reader'], 'approval': approval}
            write(isolated / 'materials/book-publication-intake' / (row['id'] + '.json'), envelope)
        raw = command([sys.executable, '-B', 'books/material_publication_intake.py', '--root', isolated], isolated)
        intake = json.loads(raw)
        require(intake['errors'] == [] and len(intake['accepted']) == 2
                and intake['sourceApprovalCreated'] is False, 'Normal technical source intake did not accept both exact fixtures')
        require(len(read(isolated / 'materials/catalog.json')['entries']) == 2, 'Unexpected synthetic catalog members')
        source_commit = commit(isolated, 'Register two exact technical TEST articles through normal intake')
        require(not git(isolated, 'remote').strip(), 'Synthetic root must have no Git remote')
        require(not git(isolated, 'status', '--porcelain').strip(), 'Synthetic source checkout is not clean')
        provenance = {'schema': 'iman-isolated-automation-test-provenance-v1',
                      'productionSourceCommit': baseline['head'], 'productionTree': baseline['tree'],
                      'productionFiles': production_files, 'fixtureBindings': fixture_bindings,
                      'pinnedAssets': pinned_assets, 'originalConfigSHA256': file_hash(root / 'books/config.json'),
                      'isolatedConfigSHA256': file_hash(isolated / 'books/config.json'),
                      'configChanges': ['English only; five pinned font families and Article cover only',
                                        'English Articles title is exactly automation test material',
                                        'Empty explicitly synthetic audio registry'],
                      'productionBefore': baseline, 'initialCommit': initial_commit,
                      'isolatedInputCommit': source_commit, 'scope': SCOPE,
                      'automaticRelease': False, 'releaseHold': RELEASE_HOLD,
                      'gitRemotes': [], 'credentialsCopied': False}
        write(out / 'provenance.json', provenance)
        write(out / 'source-intake-report.json', intake)
        queue_commit, handoff = None, None
        if not args.stage_only:
            print('Running unchanged production preparation for isolated en/articles.', flush=True)
            command([sys.executable, '-B', 'books/automatic_publication.py', 'build',
                     '--root', isolated, '--out', out / 'preparation', '--commit', source_commit,
                     '--repo', REPOSITORY_LABEL, '--tag', TAG, '--uno-python', args.uno_python],
                    isolated, timeout=4800, capture=False)
            build = read(out / 'preparation/build-report.json')
            require(build.get('buildComplete') is True and build['failed'] == []
                    and build['built'] == [] and len(build['prepared']) == 1,
                    'Normal build failed or unexpectedly finalized a test')
            queue = read(isolated / 'books/prepared-library.json')
            require(len(queue['entries']) == 1, 'Unexpected preparation scope count')
            row = queue['entries'][0]
            require((row['language'], row['collection']) == ('en', 'articles')
                    and row['sourceCommit'] == source_commit and row['releaseVerified'] is False
                    and {item['check'] for item in row['pendingChecks']} ==
                    {'scope-release-hold', 'actual-word-layout', 'final-visual-inspection'},
                    'Expected real Word, visual and TEST-only release holds are missing')
            queue_commit = commit(isolated, 'Record immutable held technical TEST preparation')
            command([sys.executable, '-B', 'books/finalize_prepared.py', 'plan', '--root', isolated,
                     '--prepared', out / 'preparation/en-articles', '--handoff', out / 'handoff.json'], isolated)
            handoff = read(out / 'handoff.json')
            word_manifest = {'schema': 'iman-automation-test-word-launch-v1', 'scope': SCOPE,
                             'productionSourceCommit': baseline['head'], 'productionFiles': production_files,
                             'isolatedInputCommit': source_commit, 'isolatedQueueCommit': queue_commit,
                             'fixtureBindings': fixture_bindings,
                             'artifactFiles': {name: record['sha256'] for name, record in inventory(out / 'preparation').items()},
                             'queueSHA256': file_hash(isolated / 'books/prepared-library.json'),
                             'handoff': handoff, 'expectedTitle': TITLE, 'expectedBody': BODY,
                             'expectedMaterialCount': 2, 'automaticRelease': False, 'releaseHold': RELEASE_HOLD,
                             'pinnedAssets': pinned_assets,
                             'isolatedConfigSHA256': file_hash(isolated / 'books/config.json')}
            write(out / 'word-launch-manifest.json', word_manifest)
        require(read(isolated / 'books/published-library.json')['entries'] == []
                and read(isolated / 'books/published-bundles.json')['languages'] == {},
                'Synthetic root unexpectedly has a public library')
        require(not git(isolated, 'remote').strip() and not git(isolated, 'status', '--porcelain').strip(),
                'Synthetic root acquired a remote or uncommitted changes')
        git(isolated, 'bundle', 'create', out / 'isolated-root.bundle', 'technical-test')
        git(isolated, 'bundle', 'verify', out / 'isolated-root.bundle')
        final_baseline = tree_snapshot(root)
        require(final_baseline == baseline, 'Original production tracked tree/catalog/library/bundle/queue changed')
        root_files = {name.decode(): file_hash(safe_file(isolated, name.decode()))
                      for name in git(isolated, 'ls-files', '-z').split(b'\0') if name}
        write(out / 'isolated-root-files.json', {'schema': 'iman-isolated-test-root-files-v1',
              'commit': queue_commit or source_commit, 'files': root_files})
        receipt = {'schema': 'iman-isolated-automation-test-receipt-v1',
                   'createdAtUTC': datetime.now(timezone.utc).isoformat(),
                   'state': 'stage-only-no-render' if args.stage_only else 'prepared-awaiting-owned-word-and-visual-review',
                   'testOnly': True, 'scope': SCOPE, 'productionSourceCommit': baseline['head'],
                   'initialCommit': initial_commit, 'isolatedInputCommit': source_commit,
                   'isolatedQueueCommit': queue_commit, 'fixtureManifestSHA256': fixture_bindings[FIXTURE + '/fixture-manifest.json'],
                   'sourceIntakeAccepted': 2, 'expectedTitle': TITLE, 'expectedBody': BODY,
                   'handoffSHA256': digest(encoded(handoff)) if handoff else None,
                   'gitBundleSHA256': file_hash(out / 'isolated-root.bundle'),
                   'productionBefore': baseline, 'productionAfter': final_baseline,
                   'productionUnchanged': True, 'productionCodeUnchanged': True,
                   'actualWordRun': False, 'visualAcceptanceCreated': False,
                   'publicPublicationApproved': False, 'publicationInvoked': False,
                   'automaticRelease': False, 'releaseHold': RELEASE_HOLD, 'gitRemotes': [],
                   'credentialsCopied': False,
                   'packageRestore': 'In a fresh owned root, git init -b technical-test; git fetch <bundle-path> technical-test; git reset --hard FETCH_HEAD. Do not configure any remote.',
                   'limitations': ['Only synthetic English Articles are exercised.',
                       'The unchanged English template retains its standard front-matter notice; the synthetic TEST text itself is authored, not translated.',
                       'No live source registration, GitHub release, download-table commit or public deployment is performed.',
                       'Actual Word and visual review remain separate. The explicit TEST-only release hold must remain.']}
        write(out / 'isolated-test-receipt.json', receipt)
        names = ['provenance.json', 'source-intake-report.json', 'isolated-root.bundle',
                 'isolated-root-files.json', 'isolated-test-receipt.json']
        if not args.stage_only:
            names += ['handoff.json', 'word-launch-manifest.json']
            names += ['preparation/' + name for name in inventory(out / 'preparation')]
        transfer_files = {name: {'sha256': file_hash(out / name), 'bytes': (out / name).stat().st_size}
                          for name in sorted(names)}
        write(out / 'transfer-files.json', {'schema': 'iman-isolated-test-transfer-files-v1', 'files': transfer_files})
        with ZipFile(out / 'transfer.zip', 'x', ZIP_DEFLATED, compresslevel=6) as archive:
            for name in sorted([*names, 'transfer-files.json']):
                info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, (out / name).read_bytes())
        with ZipFile(out / 'transfer.zip') as archive:
            require(len(archive.namelist()) == len(names) + 1, 'Unexpected transfer ZIP membership')
            for name, item in transfer_files.items():
                require(digest(archive.read(name)) == item['sha256'], 'Packaged bytes changed')
        print(json.dumps({'state': receipt['state'], 'out': str(out),
                          'receiptSHA256': file_hash(out / 'isolated-test-receipt.json'),
                          'transferSHA256': file_hash(out / 'transfer.zip'),
                          'isolatedInputCommit': source_commit, 'isolatedQueueCommit': queue_commit,
                          'wordLaunchManifestSHA256': file_hash(out / 'word-launch-manifest.json') if handoff else None,
                          'productionUnchanged': True, 'publicationInvoked': False}), flush=True)
    finally:
        # A failure is never allowed to conceal a production-side mutation.
        require(tree_snapshot(root) == baseline, 'Production checkout changed during the isolated test')


if __name__ == '__main__':
    main()
