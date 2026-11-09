"""Exercise the actual published corpus and reject wrong-format presentation."""
from pathlib import Path
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import update_download_display as display


def snapshot(root):
    return {name: (root / name).read_bytes() for name in display.paths()}


def copy_corpus(destination):
    for relative in display.paths():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def legacy_labels(root):
    catalog = json.loads((root / display.CATALOG).read_bytes())
    for row in catalog['languages'].values():
        for extension in ('docx', 'pdf'):
            row['downloads'][extension] = display.SUFFIX.sub('', row['downloads'][extension])
    (root / display.CATALOG).write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    for relative in display.paths():
        if not relative.endswith('.md'):
            continue
        path = root / relative
        text = path.read_text(encoding='utf8')
        text = display.LINK.sub(lambda match: '[' + display.SUFFIX.sub('', match.group(1)) + '](' + match.group(2) + ')', text)
        text = text.replace(' (Word) |', ' |').replace(' (PDF) |', ' |')
        text = text.replace('<br>', ' · ')
        text = re.sub(r'(\]\(https://github\.com/[^\s)]+\.docx\))\n\n(\[)', r'\1 · \2', text)
        if relative == 'README.md':
            text = text.replace('[Editable](', '[Editable book](').replace('[Readable](', '[Reading copy](')
            text = text.replace('Iman_Companion_ar_hadith.pdf) |', 'Iman_Companion_ar_hadith.pdf) * † |')
            old = tuple(display.LEGEND_REPLACEMENTS)[:2]
            for new, previous in zip(display.LEGENDS, old):
                text = text.replace(new, previous)
        path.write_text(text, encoding='utf8')


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'repository'
        self.root.mkdir()
        copy_corpus(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_real_catalog_metadata_urls_and_idempotence(self):
        before = snapshot(self.root)
        old = json.loads(before[display.CATALOG])
        pairs = sum(len(row['books']) for row in old['languages'].values())
        self.assertIn('hadith', {book['collection'] for book in old['languages']['ar']['books']})
        display.update(self.root)
        after = snapshot(self.root)
        new = json.loads(after[display.CATALOG])
        restored = copy.deepcopy(new)
        for language, row in old['languages'].items():
            restored['languages'][language]['downloads'] = row['downloads']
            for extension in ('docx', 'pdf'):
                self.assertTrue(new['languages'][language]['downloads'][extension].endswith(' (' + display.FORMATS[extension] + ')'))
        self.assertEqual(old, restored)
        for relative in before:
            if relative.endswith('.md'):
                original_urls = [match.group(2) for match in display.LINK.finditer(before[relative].decode())]
                final_urls = [match.group(2) for match in display.LINK.finditer(after[relative].decode())]
                self.assertEqual(original_urls, final_urls, relative)
        for text_before, text_after in [(before['README.md'].decode(), after['README.md'].decode())]:
            self.assertEqual(text_before.split(display.START)[0], text_after.split(display.START)[0])
            self.assertEqual(text_before.split(display.END)[1], text_after.split(display.END)[1])
        self.assertEqual(display.update(self.root)['filesChanged'], [])
        self.assertEqual(snapshot(self.root), after)
        self.assertEqual(after['README.md'].decode().count('<br>'), pairs)

    def test_legacy_markers_and_labels(self):
        legacy_labels(self.root)
        original = snapshot(self.root)
        result = display.update(self.root)
        self.assertEqual(set(result['filesChanged']), set(display.paths()))
        readme = (self.root / 'README.md').read_text(encoding='utf8')
        block = readme.split(display.START)[1].split(display.END)[0]
        self.assertNotIn('†', block)
        self.assertNotRegex(block, r'\)\s+\*')
        self.assertIn('[Editable (Word)](', block)
        self.assertIn('[Readable (PDF)](', block)
        self.assertNotIn('[Editable book]', block)
        for language in display.LANGUAGES:
            page = (self.root / f'books/downloads/{language}/README.md').read_text(encoding='utf8')
            self.assertNotRegex(page, r'\.docx\) · \[')
        self.assertEqual(original['README.md'].decode().split(display.END)[1], readme.split(display.END)[1])
        self.assertEqual(display.update(self.root)['filesChanged'], [])

    def test_bad_catalog_pdf_aborts_every_write(self):
        legacy_labels(self.root)
        path = self.root / display.CATALOG
        catalog = json.loads(path.read_bytes())
        book = next(book for book in catalog['languages']['ar']['books'] if book['collection'] == 'hadith')
        book['pdf'] = book['docx']
        path.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf8')
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'format, language or collection'):
            display.update(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_swapped_markdown_links_abort_every_write(self):
        for relative in ('README.md', 'books/downloads/ar/README.md', 'books/downloads/fil/README.md'):
            with self.subTest(relative=relative):
                copy_corpus(self.root)
                legacy_labels(self.root)
                path = self.root / relative
                text = path.read_text(encoding='utf8')
                changed, count = re.subn(r'(Iman_Companion_[^\s)]+)\.pdf\)', r'\1.docx)', text, count=1)
                self.assertEqual(count, 1)
                path.write_text(changed, encoding='utf8')
                before = snapshot(self.root)
                with self.assertRaisesRegex(ValueError, 'Table link differs'):
                    display.update(self.root)
                self.assertEqual(snapshot(self.root), before)

    def test_wrong_bundle_language_rejected(self):
        path = self.root / 'books/downloads/ar/README.md'
        text = path.read_text(encoding='utf8').replace('Iman_Companion_ar_all-books.pdf', 'Iman_Companion_en_all-books.pdf')
        path.write_text(text, encoding='utf8')
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'Combined link differs'):
            display.update(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_ambiguous_marker_and_symlink_rejected(self):
        readme = self.root / 'README.md'
        readme.write_text(readme.read_text(encoding='utf8') + display.START, encoding='utf8')
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            display.update(self.root)
        self.assertEqual(snapshot(self.root), before)
        copy_corpus(self.root)
        target = self.root / 'books/downloads/ar/README.md'
        external = Path(self.temporary.name) / 'external.md'
        shutil.copyfile(target, external)
        target.unlink()
        target.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            display.update(self.root)

    def git(self, *args, root=None):
        result = subprocess.run(['git', *args], cwd=root or self.root, capture_output=True, check=True)
        return result.stdout.decode().strip()

    def init_publish_fixture(self):
        legacy_labels(self.root)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Download display test')
        self.git('config', 'user.email', 'download-display@example.invalid')
        (self.root / 'unrelated.txt').write_text('keep\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Local test fixture')
        remote = Path(self.temporary.name) / 'remote.git'
        self.git('init', '--bare', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        return self.git('rev-parse', 'HEAD'), remote

    def test_publish_commits_only_planned_files_to_local_test_remote(self):
        old, remote = self.init_publish_fixture()
        (self.root / 'untracked.txt').write_text('not committed\n')
        result = display.update(self.root, publish=True, expected_head=old)
        self.assertTrue(result['published'])
        changed = self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()
        self.assertEqual(set(changed), set(display.paths()))
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'refs/heads/main', root=remote))
        self.assertEqual((self.root / 'unrelated.txt').read_text(), 'keep\n')
        self.assertNotIn('untracked.txt', self.git('ls-tree', '--name-only', 'HEAD'))
        self.assertEqual(display.update(self.root, publish=True)['filesChanged'], [])

    def test_publish_rejects_dirty_checkout_wrong_head_and_advanced_remote(self):
        old, remote = self.init_publish_fixture()
        before = snapshot(self.root)
        (self.root / 'unrelated.txt').write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'clean tracked'):
            display.update(self.root, publish=True)
        self.assertEqual(before, snapshot(self.root))
        self.git('restore', 'unrelated.txt')
        with self.assertRaisesRegex(ValueError, 'requested HEAD'):
            display.update(self.root, publish=True, expected_head='0' * 40)
        self.git('commit', '--allow-empty', '-m', 'Advance local test remote')
        self.git('push', 'origin', 'HEAD:refs/heads/main')
        self.git('checkout', '--detach', old)
        with self.assertRaisesRegex(ValueError, 'Remote main changed'):
            display.update(self.root, publish=True)
        self.assertEqual(before, snapshot(self.root))


if __name__ == '__main__':
    unittest.main()
