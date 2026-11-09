"""Add download format labels without changing prepared-book input fingerprints.

Run after the existing publisher commits its generated tables. This transforms
only already-published presentation files; it does not generate or approve books.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit


LANGUAGES = ('en', 'ar', 'ur', 'id', 'ms', 'bn', 'tr', 'fr', 'pt-BR', 'hi',
             'ru', 'es', 'fa', 'de', 'zh-CN', 'uz', 'th', 'vi', 'ja', 'fil')
COLLECTIONS = ('tadabbur-extended', 'hadith', 'seerah', 'articles')
REPOSITORY = 'blaghtayt-alt/iman-companion'
RELEASE_PREFIX = 'https://github.com/' + REPOSITORY + '/releases/download/'
START = '<!-- IMAN-BOOK-DOWNLOADS:START -->'
END = '<!-- IMAN-BOOK-DOWNLOADS:END -->'
CATALOG = 'docs/books/catalog.json'
LINK = re.compile(r'\[([^\]\n]+)\]\(([^()\s]+)\)')
SUFFIX = re.compile(r'\s+\((Word|PDF)\)$')
FORMATS = {'docx': 'Word', 'pdf': 'PDF'}
LEGENDS = (
    'Verified earlier editions include only the listed contents; new material is awaiting release checks.',
    'Each language page lists the exact included lesson or surah numbers and any material awaiting publication or a coverage check.',
)
LEGEND_REPLACEMENTS = {
    '* Verified earlier edition: only the listed contents are included; new material is awaiting release checks.': LEGENDS[0],
    '† Partial contents or coverage check pending. Each language page lists the exact included lesson or surah numbers and the material not included in that download.': LEGENDS[1],
    **{mark + ' ' + legend: legend for mark in ('*', '†') for legend in LEGENDS},
}


def paths():
    return ('README.md', CATALOG, *(f'books/downloads/{lang}/README.md' for lang in LANGUAGES))


def checked_path(root, relative):
    path = root / relative
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Presentation path must not be a symbolic link: ' + relative)
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Missing or unconfined presentation file: ' + relative)
    return path


def route(url, language, extension, collections):
    """Validate format and identity without rewriting or following the URL."""
    if not isinstance(url, str) or not url.startswith(RELEASE_PREFIX):
        raise ValueError('Download must use the existing repository release origin')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment:
        raise ValueError('Unexpected download URL components')
    tail = url[len(RELEASE_PREFIX):].split('/')
    if len(tail) != 2 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', unquote(tail[0])):
        raise ValueError('Invalid release tag or download path')
    allowed = {f'Iman_Companion_{language}_{collection}.{extension}' for collection in collections}
    if unquote(tail[1]) not in allowed:
        raise ValueError('Download format, language or collection differs from its label')
    return url


def format_label(label, extension, english=False):
    if not isinstance(label, str) or not label.strip() or any(c in label for c in '\r\n[]'):
        raise ValueError('Invalid download label')
    suffix = SUFFIX.search(label)
    if suffix and suffix.group(1) != FORMATS[extension]:
        raise ValueError('Existing explicit format label contradicts its download')
    base = SUFFIX.sub('', label).rstrip()
    if english:
        base = {'docx': 'Editable', 'pdf': 'Readable'}[extension]
    return base + ' (' + FORMATS[extension] + ')'


def validate_catalog(catalog):
    if catalog.get('schema') != 'iman-book-downloads-v1' or set(catalog.get('languages', {})) != set(LANGUAGES):
        raise ValueError('Expected the complete current 20-language download catalog')
    for language, row in catalog['languages'].items():
        if row.get('language') != language or not isinstance(row.get('books'), list):
            raise ValueError('Invalid catalog language identity')
        for extension in FORMATS:
            format_label(row.get('downloads', {}).get(extension), extension)
        seen = set()
        for book in row['books']:
            collection = book.get('collection')
            if book.get('language') != language or collection not in COLLECTIONS or collection in seen:
                raise ValueError('Invalid or duplicate catalog book identity')
            seen.add(collection)
            for extension in FORMATS:
                route(book.get(extension), language, extension, (collection,))
        bundle = row.get('bundle')
        if bundle is not None:
            if not isinstance(bundle, dict) or not seen or type(bundle.get('parts')) is not int or bundle['parts'] != len(seen):
                raise ValueError('Combined download inventory differs from current books')
            for extension in ('docx', 'pdf', 'zip'):
                allowed = ('all-books', *seen) if len(seen) == 1 and extension != 'zip' else ('all-books',)
                route(bundle.get(extension), language, extension, allowed)


def cells(line):
    if not line.startswith('| ') or not line.rstrip().endswith('|'):
        raise ValueError('Unexpected generated download-table row')
    return [part.strip() for part in re.split(r'(?<!\\)\|', line.strip())[1:-1]]


def table_line(values, original):
    return '| ' + ' | '.join(values) + ' |' + ('\n' if original.endswith('\n') else '')


def link_value(text):
    found = LINK.fullmatch(text)
    if found is None:
        raise ValueError('Expected one exact generated download link')
    return found.group(1), found.group(2)


def formatted_link(text, expected_url, extension, english=False):
    label, url = link_value(text)
    if url != expected_url:
        raise ValueError('Table link differs from the catalog or selects the wrong format')
    return '[' + format_label(label, extension, english) + '](' + url + ')'


def pair_links(text, book, english=False):
    matches = list(LINK.finditer(text))
    if len(matches) != 2 or text[:matches[0].start()].strip():
        raise ValueError('Expected exactly a Word/PDF download pair')
    between = text[matches[0].end():matches[1].start()].strip()
    tail = text[matches[1].end():].strip()
    if between not in ('·', '<br>', '<br/>', '<br />') or not re.fullmatch(r'[\s*†]*', tail):
        raise ValueError('Unexpected content around a generated download pair')
    return '<br>'.join(formatted_link(m.group(0), book[extension], extension, english)
                       for m, extension in zip(matches, ('docx', 'pdf')))


def root_readme(original, catalog):
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError('Expected one unambiguous README download block')
    start = original.index(START) + len(START)
    end = original.index(END)
    if end <= start:
        raise ValueError('README download markers are out of order')
    lines = original[start:end].splitlines(keepends=True)
    seen = set()
    for index, line in enumerate(lines):
        if not line.startswith('| ['):
            if line.strip() in LEGEND_REPLACEMENTS:
                lines[index] = LEGEND_REPLACEMENTS[line.strip()] + ('\n' if line.endswith('\n') else '')
            continue
        values = cells(line)
        _, language_url = link_value(values[0])
        match = re.fullmatch(r'https://github\.com/blaghtayt-alt/iman-companion/blob/main/books/downloads/([^/]+)/README\.md', language_url)
        if not match or match.group(1) not in LANGUAGES or match.group(1) in seen or len(values) not in (5, 6):
            raise ValueError('Invalid or duplicate root language row')
        language = match.group(1)
        seen.add(language)
        row = catalog['languages'][language]
        books = {book['collection']: book for book in row['books']}
        for column, collection in enumerate(COLLECTIONS, 1):
            if collection in books:
                values[column] = pair_links(values[column], books[collection], english=language == 'en')
            elif LINK.search(values[column]) or RELEASE_PREFIX in values[column]:
                raise ValueError('Root table exposes an unpublished book')
        if len(values) == 6:
            if row.get('bundle'):
                _, url = link_value(values[5])
                if url != f'https://blaghtayt-alt.github.io/iman-companion/books/?lang={language}':
                    raise ValueError('Combined chooser belongs to another language')
            elif LINK.search(values[5]):
                raise ValueError('Root table exposes an unpublished bundle')
        lines[index] = table_line(values, line)
    if seen != set(LANGUAGES):
        raise ValueError('Root table is missing a language')
    return original[:start] + ''.join(lines) + original[end:]


def language_readme(original, language, row):
    lines = original.splitlines(keepends=True)
    tables = [index for index, line in enumerate(lines) if line.startswith('| ')]
    if len(tables) != 6 or tables != list(range(tables[0], tables[0] + 6)):
        raise ValueError('Expected one four-collection language download table')
    header = cells(lines[tables[0]])
    if len(header) != 4 or any(LINK.search(value) for value in header):
        raise ValueError('Invalid language download table header')
    for column, extension in ((1, 'docx'), (2, 'pdf')):
        header[column] = format_label(header[column], extension, english=language == 'en')
    lines[tables[0]] = table_line(header, lines[tables[0]])
    books = {book['collection']: book for book in row['books']}
    for index, collection in zip(tables[2:], COLLECTIONS):
        values = cells(lines[index])
        if len(values) != 4:
            raise ValueError('Invalid language book row')
        if collection in books:
            for column, extension in ((1, 'docx'), (2, 'pdf')):
                values[column] = formatted_link(values[column], books[collection][extension], extension)
        elif any(LINK.search(values[column]) or RELEASE_PREFIX in values[column] for column in (1, 2)):
            raise ValueError('Language table exposes an unpublished book')
        lines[index] = table_line(values, lines[index])
    # Outside the four book rows, the only release links are the three bundle
    # links. Validate them in Word/PDF/ZIP order before splitting the old pair.
    expected = [(extension, row['bundle'][extension]) for extension in ('docx', 'pdf', 'zip')] if row.get('bundle') else []
    found = []
    for index, line in enumerate(lines):
        if index in tables:
            continue
        links = [match for match in LINK.finditer(line) if match.group(2).startswith(RELEASE_PREFIX)]
        if not links:
            if RELEASE_PREFIX in line:
                raise ValueError('Malformed release link outside the download table')
            continue
        if len(links) > 2:
            raise ValueError('Unexpected bundle link layout')
        pieces = []
        for match in links:
            if len(found) >= len(expected):
                raise ValueError('Unexpected extra combined download')
            extension, url = expected[len(found)]
            if match.group(2) != url:
                raise ValueError('Combined link differs from catalog or format order')
            found.append((extension, url))
            pieces.append(formatted_link(match.group(0), url, extension) if extension != 'zip' else match.group(0))
        before = line[:links[0].start()].strip()
        after = line[links[-1].end():].strip()
        between = line[links[0].end():links[-1].start()].strip() if len(links) == 2 else ''
        if before or after or (len(links) == 2 and between not in ('·', '<br>', '<br/>', '<br />')):
            raise ValueError('Unexpected text around combined downloads')
        lines[index] = '\n\n'.join(pieces) + ('\n' if line.endswith('\n') else '')
    if found != expected:
        raise ValueError('Missing combined download formats')
    return ''.join(lines)


def plan(root):
    root = Path(root).resolve()
    original = {relative: checked_path(root, relative).read_bytes() for relative in paths()}
    catalog = json.loads(original[CATALOG])
    validate_catalog(catalog)
    transformed = copy.deepcopy(catalog)
    for row in transformed['languages'].values():
        for extension in FORMATS:
            row['downloads'][extension] = format_label(row['downloads'][extension], extension)
    output = {CATALOG: (json.dumps(transformed, ensure_ascii=False, indent=2) + '\n').encode('utf8')}
    output['README.md'] = root_readme(original['README.md'].decode('utf8'), catalog).encode('utf8')
    for language in LANGUAGES:
        relative = f'books/downloads/{language}/README.md'
        output[relative] = language_readme(original[relative].decode('utf8'), language,
                                         catalog['languages'][language]).encode('utf8')
    # This explicit comparison protects every URL, content, coverage, hash and
    # date in the catalog. Only the two display labels per language may differ.
    restored = copy.deepcopy(transformed)
    for language in LANGUAGES:
        restored['languages'][language]['downloads'] = catalog['languages'][language]['downloads']
    if restored != catalog:
        raise ValueError('Display transformation changed catalog metadata')
    changes = {relative: data for relative, data in output.items() if data != original[relative]}
    return original, changes


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True)
    if result.returncode:
        # Do not print git stderr, which can contain credential-bearing URLs.
        raise ValueError('Git operation failed: ' + args[0])
    return result.stdout


def head_guard(root, expected):
    if git(root, 'rev-parse', 'HEAD').decode().strip() != expected:
        raise ValueError('Checkout HEAD changed during display update')
    remote = git(root, 'ls-remote', 'origin', 'refs/heads/main').decode().split()
    if len(remote) != 2 or remote[0] != expected or remote[1] != 'refs/heads/main':
        raise ValueError('Remote main changed; preserve the current publication and retry from its latest HEAD')


def write_atomic(root, original, changes):
    with tempfile.TemporaryDirectory(prefix='.download-display-', dir=root) as temporary:
        staging = Path(temporary)
        for index, (relative, data) in enumerate(changes.items()):
            staged = staging / str(index)
            staged.write_bytes(data)
            staged.chmod(stat.S_IMODE(checked_path(root, relative).stat().st_mode))
        for relative, before in original.items():
            if checked_path(root, relative).read_bytes() != before:
                raise ValueError('Presentation input changed while validation was running: ' + relative)
        applied = []
        try:
            for index, relative in enumerate(changes):
                os.replace(staging / str(index), root / relative)
                applied.append(relative)
        except Exception:
            for index, relative in enumerate(reversed(applied)):
                rollback = staging / ('rollback-' + str(index))
                rollback.write_bytes(original[relative])
                rollback.chmod(stat.S_IMODE((root / relative).stat().st_mode))
                os.replace(rollback, root / relative)
            raise


def update(root, publish=False, expected_head=None):
    root = Path(root).resolve()
    expected = None
    if publish:
        if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
            raise ValueError('Publish root must be the repository root')
        expected = git(root, 'rev-parse', 'HEAD').decode().strip()
        if expected_head is not None and expected != expected_head:
            raise ValueError('Checkout does not match the requested HEAD')
        if git(root, 'status', '--porcelain', '--untracked-files=no').strip():
            raise ValueError('Display publication requires a clean tracked checkout and no staged changes')
        git(root, 'ls-files', '--error-unmatch', '--', *paths())
        head_guard(root, expected)
    elif expected_head is not None:
        raise ValueError('--expected-head is only meaningful with --publish')
    original, changes = plan(root)
    if publish:
        head_guard(root, expected)
    if changes:
        write_atomic(root, original, changes)
    committed = False
    if publish and changes:
        head_guard(root, expected)
        if git(root, 'diff', '--cached', '--name-only').strip():
            raise ValueError('Unexpected staged change appeared during display update')
        git(root, 'add', '--', *changes)
        staged = git(root, 'diff', '--cached', '--name-only', '-z').decode().rstrip('\0').split('\0')
        if set(staged) != set(changes):
            raise ValueError('Unexpected staged presentation paths')
        for relative, data in changes.items():
            if git(root, 'show', ':' + relative) != data:
                raise ValueError('Staged presentation bytes changed: ' + relative)
        head_guard(root, expected)
        git(root, 'commit', '-m', 'Clarify Word and PDF download labels')
        committed = True
        committed_files = git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').decode().splitlines()
        if set(committed_files) != set(changes):
            raise ValueError('Presentation commit contains unexpected paths; not pushing')
        remote = git(root, 'ls-remote', 'origin', 'refs/heads/main').decode().split()
        if len(remote) != 2 or remote[0] != expected:
            raise ValueError('Remote main advanced; presentation commit retained locally without pushing')
        git(root, 'push', 'origin', 'HEAD:refs/heads/main')
    return {'filesChanged': list(changes), 'committed': committed, 'published': committed and publish}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--expected-head')
    args = parser.parse_args()
    print(json.dumps(update(args.root, args.publish, args.expected_head), ensure_ascii=False))


if __name__ == '__main__':
    main()
