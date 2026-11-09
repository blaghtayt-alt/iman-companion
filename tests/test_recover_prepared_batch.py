"""Synthetic interrupted-artifact fixtures; never real Word or review evidence.

Existing source signatures, queue identities and finalize_prepared.plan run
without mocks. ZIP/API fixtures are explicitly local and no network is used.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from contextlib import redirect_stderr
from io import StringIO
import json
import shutil
import stat
import sys
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'books'))
import recover_prepared_batch as recovery
import test_finalize_word_batch as fixtures
from published_library import read, sha


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.batch = fixtures.BatchTests()
        self.batch.setUp()
        self.addCleanup(self.batch.doCleanups)
        self.fixture = self.batch.fixture
        self.root, self.artifact = self.batch.root, self.batch.artifact
        self.work = Path(self.fixture.temp.name)
        self.archive, self.metadata, self.out = self.work / 'original.zip', self.work / 'artifact-api.json', self.work / 'recovery'
        self.repository = 'example/fixture'
        now = datetime.now(timezone.utc)
        self.record = {'repository': self.repository, 'runId': '555',
                       'name': 'current-book-publication-555-2',
                       'runURL': 'https://github.com/example/fixture/actions/runs/555',
                       'createdAt': now.isoformat(), 'expiresAt': (now + timedelta(days=90)).isoformat(), 'retentionDays': 90}
        self.api = {'id': 777, 'name': self.record['name'], 'expired': False,
                    'url': 'https://api.github.com/repos/example/fixture/actions/artifacts/777',
                    'archive_download_url': 'https://api.github.com/repos/example/fixture/actions/artifacts/777/zip',
                    'expires_at': self.record['expiresAt'],
                    'workflow_run': {'id': 555, 'repository_id': 1, 'head_repository_id': 1,
                                     'head_branch': 'main', 'head_sha': self.fixture.source_commit}}
        self.bind_snapshots()
        self.write_queue([])
        self.pack()

    def bind_snapshots(self):
        self.rows = []
        for path in sorted(self.artifact.glob('*/prepared-snapshot.json')):
            data = read(path)
            row = data['entries'][0]
            row.pop('localArtifacts', None)
            row['artifact'] = deepcopy(self.record)
            self.fixture.write(path, data)
            self.rows.append(row)

    def write_queue(self, rows):
        self.fixture.write(self.root / recovery.QUEUE_PATH,
                           {'schema': recovery.QUEUE_SCHEMA, 'entries': deepcopy(rows)})

    def pin(self):
        self.api.update(size_in_bytes=self.archive.stat().st_size, digest='sha256:' + sha(self.archive.read_bytes()))
        self.fixture.write(self.metadata, self.api)

    def pack(self):
        with ZipFile(self.archive, 'w', ZIP_DEFLATED) as archive:
            for path in sorted(self.artifact.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(self.artifact).as_posix())
        self.pin()

    def run_recovery(self, out=None):
        return recovery.run_recovery(self.root, self.archive, self.metadata, out or self.out, self.repository)

    def edit_snapshot(self, change):
        path = self.artifact / 'en-articles/prepared-snapshot.json'
        value = read(path)
        change(value['entries'][0])
        self.fixture.write(path, value)
        self.pack()

    def test_recovers_exact_original_row_with_real_planner_and_no_approvals(self):
        before = recovery.inventory(self.root)
        archive = self.archive.read_bytes()
        result = self.run_recovery()
        self.assertEqual(len(result['recovered']), 1)
        self.assertEqual(result['rejected'], [])
        self.assertEqual(read(self.out / 'proposed-prepared-library.json')['entries'], self.rows)
        self.assertEqual(recovery.inventory(self.root), before)
        self.assertEqual(self.archive.read_bytes(), archive)
        for flag in ('releaseVerified', 'wordExecuted', 'visualAcceptanceGranted', 'queueApplied'):
            self.assertIs(result[flag], False)
        self.assertFalse(list(self.out.rglob('*.word-layout.json')))
        self.assertFalse(list(self.out.rglob('visual-acceptance.json')))
        isolated = self.work / 'verify-only'
        shutil.copytree(self.root, isolated)
        shutil.copyfile(self.out / 'proposed-prepared-library.json', isolated / recovery.QUEUE_PATH)
        plan = recovery.finish.plan(isolated, self.out / 'prepared/en-articles')
        self.assertEqual(plan, read(self.out / 'handoffs/en-articles.json'))
        self.assertEqual((self.out / 'prepared/en-articles/prepared-snapshot.json').read_bytes(),
                         (self.artifact / 'en-articles/prepared-snapshot.json').read_bytes())

    def test_repeat_is_idempotent_but_tampered_existing_output_is_preserved(self):
        first = self.run_recovery()
        before = recovery.inventory(self.out)
        self.assertEqual(self.run_recovery(), first)
        self.assertEqual(recovery.inventory(self.out), before)
        path = self.out / 'proposed-prepared-library.json'
        path.write_bytes(b'SYNTHETIC TAMPERED PROPOSAL')
        with self.assertRaisesRegex(ValueError, 'different evidence'):
            self.run_recovery()
        self.assertEqual(path.read_bytes(), b'SYNTHETIC TAMPERED PROPOSAL')

    def test_identical_current_queue_is_preserved_byte_for_byte(self):
        self.write_queue(self.rows)
        path = self.root / recovery.QUEUE_PATH
        path.write_text(json.dumps(read(path), separators=(',', ':')) + '\n')
        before = path.read_bytes()
        result = self.run_recovery()
        self.assertFalse(result['recovered'])
        self.assertEqual(len(result['alreadyCurrent']), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.out / 'proposed-prepared-library.json').read_bytes(), before)

    def test_conflicting_scope_and_all_unrelated_queue_entries_stay_unchanged(self):
        self.batch.add_french_scope()
        self.bind_snapshots()
        existing = deepcopy(self.rows)
        existing[0]['pendingChecks'][0]['reason'] = 'Different current candidate review hold'
        existing[1]['state'] = 'superseded-source-awaiting-preparation'
        self.write_queue(existing)
        # Only English is in this chosen artifact; French still must survive.
        shutil.rmtree(self.artifact / 'fr-articles')
        self.pack()
        before = (self.root / recovery.QUEUE_PATH).read_bytes()
        result = self.run_recovery()
        self.assertIn('different entry', result['rejected'][0]['error'])
        self.assertFalse(result['recovered'])
        self.assertEqual(read(self.out / 'proposed-prepared-library.json')['entries'], existing)
        self.assertEqual((self.root / recovery.QUEUE_PATH).read_bytes(), before)
        self.assertEqual((self.out / 'proposed-prepared-library.json').read_bytes(), before)

    def test_current_sources_and_rendering_code_invalidate_old_preparations(self):
        for index, path in enumerate((self.root / 'materials/article.json', self.root / 'books/render_fixture.py')):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'\n ')
                result = self.run_recovery(self.work / ('stale-' + str(index)))
                self.assertIn('inputs changed', result['rejected'][0]['error'])
                self.assertEqual(read(self.work / ('stale-' + str(index)) / 'proposed-prepared-library.json')['entries'], [])
                path.write_bytes(original)

    def test_required_word_and_visual_holds_cannot_be_removed(self):
        original = (self.artifact / 'en-articles/prepared-snapshot.json').read_bytes()
        for index, hold in enumerate(('actual-word-layout', 'final-visual-inspection')):
            with self.subTest(hold=hold):
                (self.artifact / 'en-articles/prepared-snapshot.json').write_bytes(original)
                self.edit_snapshot(lambda row: row.update(pendingChecks=[r for r in row['pendingChecks'] if r['check'] != hold]))
                result = self.run_recovery(self.work / ('hold-' + str(index)))
                self.assertIn('Word and visual review holds', result['rejected'][0]['error'])
                self.assertFalse(result['recovered'])

    def test_all_original_holds_survive_unchanged(self):
        additions = [{'check': 'source-references', 'reason': 'SYNTHETIC unresolved original reference'},
                     {'check': 'scope-release-hold', 'reason': 'SYNTHETIC explicit hold'}]
        self.edit_snapshot(lambda row: row['pendingChecks'].extend(additions))
        result = self.run_recovery()
        original = read(self.artifact / 'en-articles/prepared-snapshot.json')['entries'][0]
        self.assertEqual(read(self.out / 'proposed-prepared-library.json')['entries'], [original])
        self.assertEqual(result['recovered'][0]['pendingChecks'], original['pendingChecks'])

    def test_wrong_snapshot_run_or_source_identity_is_rejected(self):
        original = (self.artifact / 'en-articles/prepared-snapshot.json').read_bytes()
        changes = [lambda row: row['artifact'].update(runId='999'),
                   lambda row: row.update(sourceCommit='f' * 40),
                   lambda row: row['artifact'].update(expiresAt='2000-01-01T00:00:00Z')]
        for index, change in enumerate(changes):
            (self.artifact / 'en-articles/prepared-snapshot.json').write_bytes(original)
            self.edit_snapshot(change)
            result = self.run_recovery(self.work / ('identity-' + str(index)))
            self.assertFalse(result['recovered'])
            self.assertEqual(len(result['rejected']), 1)

    def test_zip_digest_and_size_are_bound_to_separate_api_metadata(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'SYNTHETIC CHANGE')
        with self.assertRaisesRegex(ValueError, 'digest or size'):
            self.run_recovery()
        self.assertFalse(self.out.exists())

    def test_api_repository_main_run_expiry_and_unique_artifact_are_required(self):
        changes = [lambda api: api.update(url='https://api.github.com/repos/other/repo/actions/artifacts/777'),
                   lambda api: api['workflow_run'].update(head_branch='untrusted'),
                   lambda api: api['workflow_run'].update(id=556),
                   lambda api: api['workflow_run'].update(head_repository_id=2),
                   lambda api: api.update(expired=True),
                   lambda api: api.update(expires_at='2000-01-01T00:00:00Z')]
        for change in changes:
            api = deepcopy(self.api)
            change(api)
            self.fixture.write(self.metadata, api)
            with self.assertRaises(ValueError):
                self.run_recovery()
            self.assertFalse(self.out.exists())
        self.fixture.write(self.metadata, {'artifacts': [self.api, self.api]})
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.run_recovery()
        self.fixture.write(self.metadata, {'artifacts': [self.api]})
        self.assertEqual(len(self.run_recovery()['recovered']), 1)

    def test_tampered_pair_fails_real_hash_gate_despite_new_zip_pin(self):
        path = self.artifact / 'en-articles' / self.fixture.pdf
        path.write_bytes(path.read_bytes() + b'SYNTHETIC PDF TAMPER')
        self.pack()
        result = self.run_recovery()
        self.assertIn('pair changed', result['rejected'][0]['error'])
        self.assertFalse((self.out / 'prepared/en-articles').exists())

    def test_index_must_match_the_original_snapshot_and_remain_unreleased(self):
        path = self.artifact / 'en-articles/index.json'
        original = path.read_bytes()
        for index, change in enumerate((lambda book: book.update(sourceCommit='e' * 40),
                                        lambda book: book.update(exportVerified=True))):
            path.write_bytes(original)
            value = read(path)
            change(value['books'][0])
            self.fixture.write(path, value)
            self.pack()
            result = self.run_recovery(self.work / ('changed-index-' + str(index)))
            self.assertFalse(result['recovered'])
            self.assertEqual(len(result['rejected']), 1)

    def test_incomplete_source_references_require_the_original_hold(self):
        path = self.artifact / 'en-articles/index.json'
        value = read(path)
        value['books'][0]['referenceReadiness'] = {'units': 1, 'auditedUnits': 0}
        self.fixture.write(path, value)
        self.edit_snapshot(lambda row: row.update(candidate={**row['candidate'], 'book': deepcopy(value['books'][0])}))
        result = self.run_recovery(self.work / 'missing-reference-hold')
        self.assertIn('source-reference hold', result['rejected'][0]['error'])
        self.edit_snapshot(lambda row: row['pendingChecks'].append({'check': 'source-references', 'reason': 'SYNTHETIC unresolved reference'}))
        result = self.run_recovery()
        self.assertEqual(len(result['recovered']), 1)
        self.assertIn('source-references', [row['check'] for row in result['recovered'][0]['pendingChecks']])

    def test_malformed_snapshot_is_isolated_and_other_scope_recovers(self):
        self.batch.add_french_scope()
        self.bind_snapshots()
        self.write_queue([])
        (self.artifact / 'en-articles/prepared-snapshot.json').write_text('{"schema":"x","schema":"duplicate"}')
        interrupted = self.artifact / 'ur-hadith'
        interrupted.mkdir()
        (interrupted / 'partial.docx').write_bytes(b'INCOMPLETE SYNTHETIC OUTPUT')
        self.pack()
        result = self.run_recovery()
        self.assertEqual([row['language'] for row in result['recovered']], ['fr'])
        self.assertEqual([row['folder'] for row in result['rejected']], ['en-articles'])
        self.assertEqual([row['folder'] for row in result['ignored']], ['ur-hadith'])
        self.assertEqual([row['language'] for row in read(self.out / 'proposed-prepared-library.json')['entries']], ['fr'])

    def test_queue_change_during_validation_prevents_any_proposal(self):
        original = recovery.copy_sources
        def concurrent_change(root, target):
            original(root, target)
            self.write_queue(self.rows)
        with patch.object(recovery, 'copy_sources', side_effect=concurrent_change):
            with self.assertRaisesRegex(ValueError, 'queue changed'):
                self.run_recovery()
        self.assertFalse(self.out.exists())
        self.assertEqual(read(self.root / recovery.QUEUE_PATH)['entries'], self.rows)

    def test_zip_traversal_symlinks_aliases_and_collisions_are_rejected(self):
        cases = [[('../outside', b'x')], [('/absolute', b'x')], [('en\\file', b'x')],
                 [('one', b'x'), ('one', b'y')], [('A/file', b'x'), ('a/other', b'y')],
                 [('parent', b'x'), ('parent/child', b'y')], [('NUL.txt', b'x')]]
        link = ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append([(link, b'/outside')])
        for entries in cases:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with ZipFile(self.archive, 'w') as archive:
                    for name, data in entries:
                        archive.writestr(name, data)
            self.pin()
            with self.assertRaises(ValueError):
                self.run_recovery()
            self.assertFalse(self.out.exists())
        self.assertFalse((self.work / 'outside').exists())

    def test_overlapping_outputs_and_symlink_parents_fail_without_external_writes(self):
        for out in (self.root, self.root / 'recovery', self.root.parent, self.archive):
            with self.assertRaisesRegex(ValueError, 'separate'):
                self.run_recovery(out)
        target = self.work / 'outside-output'
        target.mkdir()
        linked = self.work / 'linked'
        linked.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.run_recovery(linked / 'recovery')
        self.assertEqual(list(target.iterdir()), [])

    def test_cached_and_git_directories_are_not_copied(self):
        for name in ('.git', '.cache', '__pycache__'):
            directory = self.root / name
            directory.mkdir()
            (directory / 'local-only').write_bytes(b'SYNTHETIC LOCAL CACHE')
        target = self.work / 'copy-test'
        recovery.copy_sources(self.root, target)
        for name in ('.git', '.cache', '__pycache__'):
            self.assertFalse((target / name).exists())
        self.assertTrue((target / 'materials/article.json').is_file())

    def test_git_worktree_file_is_ignored_and_source_symlinks_are_refused(self):
        (self.root / '.git').write_text('gitdir: /SYNTHETIC/OTHER/WORKTREE')
        target = self.work / 'worktree-copy'
        recovery.copy_sources(self.root, target)
        self.assertFalse((target / '.git').exists())
        (self.root / 'materials/linked.json').symlink_to(self.root / 'materials/article.json')
        with self.assertRaisesRegex(ValueError, 'source must not be a symlink'):
            self.run_recovery()
        self.assertFalse(self.out.exists())

    def test_cli_rejects_cross_checkout_authorities(self):
        errors = StringIO()
        with redirect_stderr(errors), patch.object(recovery, 'run_recovery') as run:
            with self.assertRaises(SystemExit) as stopped:
                recovery.main(['--root', str(self.root), '--archive', str(self.archive),
                               '--artifact-metadata', str(self.metadata), '--out', str(self.out)])
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn('checkout containing this recovery helper', errors.getvalue())
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
