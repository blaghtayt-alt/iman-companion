"""Batch lifecycle fixtures only, never actual Word evidence or approval.

Source/queue identities, hashes, package preservation and the existing Word
receipt/parser gates run for real. Only the native Word invocation is mocked.
Every synthetic file and receipt is confined to TemporaryDirectory.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
sys.path.insert(0, str(ROOT / 'tools'))
import finalize_word_batch as batch
import test_finalize_prepared as fixtures
from preparation_queue import record
from published_library import read, sha
from release_candidate_intake import validate_bundle


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinalizePreparedTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.artifact = Path(self.fixture.temp.name) / 'artifact'
        self.artifact.mkdir()
        self.out = Path(self.fixture.temp.name) / 'batch'
        shutil.copytree(self.fixture.prepared, self.artifact / 'en-articles')
        queue = read(self.root / 'books/prepared-library.json')
        queue['entries'][0]['folder'] = 'en-articles'
        self.fixture.write(self.root / 'books/prepared-library.json', queue)
        self.fixture.write(self.artifact / 'en-articles/prepared-snapshot.json', queue)
        self.invocations = []

    def run_batch(self, *, stage_only=False, requested=None, worker=None):
        with redirect_stdout(StringIO()), patch.object(batch, 'is_windows', return_value=True), \
                patch.object(batch, 'invoke_word', side_effect=worker or self.synthetic_word):
            return batch.run_batch(self.root, self.artifact, self.out, requested, stage_only)

    def synthetic_word(self, root, candidate, key):
        """Synthetic test output; this never launches or represents real Word."""
        self.invocations.append(key)
        name = 'Iman_Companion_' + key[0] + '_' + key[1] + '.docx'
        self.fixture.make_docx(candidate / name, 3)
        self.fixture.make_pdf(candidate / batch.finish.PROOF, 3)
        receipt = {'schema': 'iman-word-layout-readback-v1',
                   'scope': 'SYNTHETIC BATCH TEST FIXTURE, NOT ACTUAL WORD EVIDENCE',
                   'language': key[0], 'docxSHA256': sha((candidate / name).read_bytes()),
                   'engine': {'application': 'Microsoft Word', 'version': 'fixture', 'build': 'fixture'},
                   'readOnly': True, 'savedByWord': False, 'pages': 3,
                   'contents': [{'anchor': 'lesson1', 'cachedPage': 3, 'actualPage': 3, 'physicalPage': 3}]}
        self.fixture.write(candidate / (name + '.word-layout.json'), receipt)

    def add_french_scope(self):
        f = self.fixture
        conf = read(self.root / 'books/config.json')
        conf['languages']['fr'] = {'font': 'Latin'}
        f.write(self.root / 'books/config.json', conf)
        declarations = read(self.root / 'books/reviewed-books.json')
        declarations['books'].append({**declarations['books'][0], 'language': 'fr'})
        f.write(self.root / 'books/reviewed-books.json', declarations)
        source = 'materials/fr-article.json'
        f.write(self.root / source, {'text': 'Fixture reader text.'})
        catalog = read(self.root / 'materials/catalog.json')
        catalog['entries'].append({'collection': 'articles', 'language': 'fr', 'id': 'article-fr',
                                   'status': 'published', 'json': source})
        f.write(self.root / 'materials/catalog.json', catalog)
        unit = {'id': 'article-fr', 'readerTextSHA256': sha(b'Fixture reader text.'),
                'sourceHashes': [sha((self.root / source).read_bytes())],
                'inputBindings': [{'path': source, 'sha256': sha((self.root / source).read_bytes())}]}
        f.write(self.root / 'books/units/fr.json', unit)
        manifest = deepcopy(f.manifest)
        manifest['scope']['language'] = 'fr'
        manifest['units'] = [{'language': 'fr', 'collection': 'articles', 'id': unit['id'],
                              'path': 'books/units/fr.json', 'sha256': sha((self.root / 'books/units/fr.json').read_bytes())}]
        f.write(self.root / 'books/manifest.json', manifest)
        prepared = self.artifact / 'fr-articles'
        prepared.mkdir()
        name = 'Iman_Companion_fr_articles.docx'
        f.make_docx(prepared / name, 2)
        f.make_pdf(prepared / Path(name).with_suffix('.pdf'), 3)
        f.write(prepared / (name + '.reader-checks.json'), {'body': ['Fixture reader text.']})
        f.write(prepared / 'source-manifest.json', manifest)
        index = deepcopy(f.index)
        index['books'][0].update(language='fr', file=name,
            units=[{k: unit[k] for k in ('id', 'readerTextSHA256', 'sourceHashes')}],
            sha256=sha((prepared / name).read_bytes()),
            pdfSha256=sha((prepared / Path(name).with_suffix('.pdf')).read_bytes()))
        f.write(prepared / 'index.json', index)
        row = record(self.root, index, prepared, f.source_commit,
                     [{'check': 'actual-word-layout'}, {'check': 'final-visual-inspection'}])
        queue = read(self.root / 'books/prepared-library.json')
        queue['entries'].append(row)
        f.write(self.root / 'books/prepared-library.json', queue)

    def test_stage_only_preserves_source_and_creates_no_word_or_acceptance(self):
        original = batch.inventory(self.artifact)
        queue = (self.root / 'books/prepared-library.json').read_bytes()
        with redirect_stdout(StringIO()), patch.object(batch, 'is_windows', return_value=False), \
                patch.object(batch, 'invoke_word') as word:
            result = batch.run_batch(self.root, self.artifact, self.out, stage_only=True)
        word.assert_not_called()
        self.assertEqual(result['staged'], ['en/articles'])
        self.assertFalse(result['failed'])
        self.assertEqual(self.invocations, [])
        self.assertIsNone(result['bundle'])
        self.assertEqual(batch.inventory(self.artifact), original)
        self.assertEqual((self.root / 'books/prepared-library.json').read_bytes(), queue)
        self.assertFalse(list(self.out.rglob('visual-acceptance.json')))
        staged = self.out / 'staged/en-articles'
        self.assertEqual(batch.inventory(staged / 'prepared'), batch.inventory(staged / 'candidate'))
        self.assertEqual(batch.finish.plan(self.root, staged / 'prepared'), read(staged / 'handoff.json'))

    def test_stage_resume_is_idempotent_and_uses_exact_inputs(self):
        first = self.run_batch(stage_only=True)
        before = batch.inventory(self.out)
        second = self.run_batch(stage_only=True)
        self.assertEqual(first, second)
        self.assertEqual(batch.inventory(self.out), before)

    def test_stale_source_is_rejected_without_running_word_or_overwriting(self):
        self.run_batch(stage_only=True)
        before = batch.inventory(self.out / 'staged')
        self.fixture.write(self.root / 'materials/article.json', {'text': 'Changed source.'})
        result = self.run_batch()
        self.assertEqual(len(result['failed']), 1)
        self.assertIn('inputs changed', result['failed'][0]['error'])
        self.assertEqual(self.invocations, [])
        self.assertEqual(batch.inventory(self.out / 'staged'), before)

    def test_wrong_artifact_identity_and_changed_pdf_cannot_stage(self):
        index_path = self.artifact / 'en-articles/index.json'
        index = read(index_path)
        index['books'][0]['sourceCommit'] = 'f' * 40
        self.fixture.write(index_path, index)
        result = self.run_batch(stage_only=True)
        self.assertIn('identity differs', result['failed'][0]['error'])
        self.assertFalse((self.out / 'staged/en-articles').exists())
        index['books'][0]['sourceCommit'] = self.fixture.source_commit
        self.fixture.write(index_path, index)
        with (self.artifact / 'en-articles' / self.fixture.pdf).open('ab') as stream:
            stream.write(b'changed fixture PDF')
        result = self.run_batch(stage_only=True)
        self.assertIn('pair changed', result['failed'][0]['error'])

    def test_tampered_staged_candidate_is_preserved_and_never_reused(self):
        self.run_batch(stage_only=True)
        file = self.out / 'staged/en-articles/candidate' / self.fixture.docx
        file.write_bytes(b'tampered fixture')
        result = self.run_batch()
        self.assertIn('was changed', result['failed'][0]['error'])
        self.assertEqual(file.read_bytes(), b'tampered fixture')
        self.assertEqual(self.invocations, [])

    def test_word_batch_emits_compatible_bundle_with_unaccepted_templates(self):
        result = self.run_batch()
        self.assertFalse(result['failed'])
        self.assertEqual(result['wordComplete'], ['en/articles'])
        self.assertEqual(self.invocations, [('en', 'articles')])
        root, manifest, files, _ = validate_bundle(self.out / 'bundle', require_inventory=False)
        self.assertEqual(len(manifest['scopes']), 1)
        self.assertEqual(root, (self.out / 'bundle').resolve())
        self.assertNotIn('state.json', files)
        self.assertNotIn('report.json', files)
        self.assertNotIn('.word-batch.lock', files)
        acceptance = read(root / 'en-articles/visual-acceptance.json')
        for key in ('accepted', 'allPdfPagesInspected', 'allWordPagesInspected'):
            self.assertIs(acceptance[key], False)
        self.assertEqual(acceptance['reviewer'], '')
        self.assertEqual(acceptance['reviewedAt'], '')
        self.assertEqual(batch.finish.acceptance_template(read(root / 'en-articles/handoff.json'),
                         root / 'en-articles/candidate'), acceptance)

    def test_completed_resume_skips_word_and_preserves_exact_reviewer_acceptance(self):
        self.run_batch()
        acceptance = self.out / 'bundle/en-articles/visual-acceptance.json'
        evidence = read(acceptance)
        evidence.update(accepted=True, allPdfPagesInspected=True, allWordPagesInspected=True,
                        reviewer='SYNTHETIC TEST REVIEW ONLY', reviewedAt='2025-01-01T00:00:00+00:00')
        self.fixture.write(acceptance, evidence)
        before = acceptance.read_bytes()
        self.invocations.clear()
        result = self.run_batch()
        self.assertFalse(result['failed'])
        self.assertEqual(self.invocations, [])
        self.assertEqual(acceptance.read_bytes(), before)

    def test_changed_completed_file_or_acceptance_binding_is_rejected(self):
        self.run_batch()
        candidate = self.out / 'bundle/en-articles/candidate'
        file = candidate / self.fixture.pdf
        before = file.read_bytes()
        file.write_bytes(before + b'changed fixture PDF')
        self.invocations.clear()
        result = self.run_batch()
        self.assertTrue(result['failed'])
        self.assertIsNone(result['bundle'])
        self.assertEqual(self.invocations, [])
        file.write_bytes(before)
        acceptance = self.out / 'bundle/en-articles/visual-acceptance.json'
        data = read(acceptance)
        data['docxSHA256'] = 'f' * 64
        self.fixture.write(acceptance, data)
        result = self.run_batch()
        self.assertIn('not bound', result['failed'][0]['error'])

    def test_one_native_failure_does_not_block_other_scopes_or_pollute_bundle(self):
        self.add_french_scope()
        def worker(root, candidate, key):
            if key[0] == 'en':
                (candidate / 'partial-fixture.log').write_text('Interrupted synthetic attempt')
                raise RuntimeError('Synthetic Word invocation failure')
            return self.synthetic_word(root, candidate, key)
        result = self.run_batch(worker=worker)
        self.assertEqual([row['scope'] for row in result['failed']], ['en/articles'])
        self.assertEqual(result['wordComplete'], ['fr/articles'])
        _, manifest, _, _ = validate_bundle(self.out / 'bundle', require_inventory=False)
        self.assertEqual([row['language'] for row in manifest['scopes']], ['fr'])
        self.assertFalse(list((self.out / 'staged').rglob('partial-fixture.log')))
        resumed = self.run_batch()
        self.assertFalse(resumed['failed'])
        self.assertEqual(set(resumed['wordComplete']), {'en/articles', 'fr/articles'})
        self.assertEqual(self.invocations.count(('fr', 'articles')), 1)

    def test_resume_recovers_atomic_candidate_before_state_checkpoint(self):
        self.run_batch()
        state = read(self.out / 'state.json')
        state['scopes']['en/articles']['state'] = 'staged'
        state['scopes']['en/articles'].pop('finalFiles')
        self.fixture.write(self.out / 'state.json', state)
        self.invocations.clear()
        result = self.run_batch()
        self.assertFalse(result['failed'])
        self.assertEqual(self.invocations, [])
        self.assertEqual(read(self.out / 'state.json')['scopes']['en/articles']['state'], 'word-complete')

    def test_source_change_during_word_never_promotes_candidate(self):
        def worker(root, candidate, key):
            self.synthetic_word(root, candidate, key)
            self.fixture.write(root / 'materials/article.json', {'text': 'Changed during native run.'})
        result = self.run_batch(worker=worker)
        self.assertTrue(result['failed'])
        self.assertFalse((self.out / 'bundle/en-articles').exists())
        self.assertEqual(read(self.out / 'state.json')['scopes']['en/articles']['state'], 'staged')

    def test_exclusive_output_lock_prevents_overlapping_workers(self):
        self.out.mkdir()
        with batch.owned_lock(self.out):
            with self.assertRaisesRegex(ValueError, 'Another batch process'):
                self.run_batch(stage_only=True)
        self.assertFalse((self.out / 'state.json').exists())
        self.assertFalse(self.run_batch(stage_only=True)['failed'])

    def test_actual_run_is_rejected_off_windows_before_writing(self):
        with patch.object(batch, 'is_windows', return_value=False):
            with self.assertRaisesRegex(ValueError, 'stage-only'):
                batch.run_batch(self.root, self.artifact, self.out)
        self.assertFalse(self.out.exists())

    def test_cli_rejects_different_checkout_before_running(self):
        errors = StringIO()
        with redirect_stderr(errors), patch.object(batch, 'run_batch') as run:
            with self.assertRaises(SystemExit) as stopped:
                batch.main(['--root', str(self.root), '--artifact', str(self.artifact),
                            '--out', str(self.out), '--stage-only'])
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn('checkout containing this batch helper', errors.getvalue())
        run.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_cli_accepts_its_own_checkout_and_passes_explicit_arguments(self):
        result = {'failed': []}
        with patch.object(batch, 'CODE_ROOT', self.root), redirect_stdout(StringIO()), \
                patch.object(batch, 'run_batch', return_value=result) as run:
            code = batch.main(['--root', str(self.root), '--artifact', str(self.artifact),
                               '--out', str(self.out), '--scope', 'en/articles', '--stage-only'])
        self.assertEqual(code, 0)
        run.assert_called_once_with(self.root, self.artifact, self.out, ['en/articles'], True)

    def test_repository_output_overlap_is_rejected_without_writes(self):
        before = batch.inventory(self.root)
        for output in (self.root, self.root.parent, self.root / 'batch'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'outside and separate'):
                batch.run_batch(self.root, self.artifact, output, stage_only=True)
        self.assertEqual(batch.inventory(self.root), before)
        self.assertFalse((self.root / '.word-batch.lock').exists())
        self.assertFalse((self.root.parent / '.word-batch.lock').exists())

    def test_symlinked_staging_parent_cannot_write_outside_work_directory(self):
        self.out.mkdir()
        outside = Path(self.fixture.temp.name) / 'outside'
        outside.mkdir()
        try:
            (self.out / 'staged').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Directory symlinks unavailable for this test account')
        result = self.run_batch(stage_only=True)
        self.assertIn('Symlink', result['failed'][0]['error'])
        self.assertEqual(list(outside.iterdir()), [])

    def test_unreferenced_bundle_file_prevents_transfer_ready_report(self):
        self.run_batch()
        (self.out / 'bundle/private-diagnostic.txt').write_text('Synthetic local diagnostic')
        result = self.run_batch()
        self.assertIsNone(result['bundle'])
        self.assertEqual(result['failed'][-1]['scope'], 'bundle')
        self.assertIn('Unreferenced file', result['failed'][-1]['error'])

    def test_wrong_language_word_readback_cannot_enter_bundle(self):
        def worker(root, candidate, key):
            self.synthetic_word(root, candidate, key)
            file = candidate / (self.fixture.docx + '.word-layout.json')
            receipt = read(file)
            receipt['language'] = 'fr'
            self.fixture.write(file, receipt)
        result = self.run_batch(worker=worker)
        self.assertIn('another language', result['failed'][0]['error'])
        self.assertFalse((self.out / 'bundle/en-articles').exists())

    def test_native_runner_calls_only_existing_finalizer_with_exact_scope(self):
        script = self.root / 'books/finalize_word.py'
        script.write_text('# Synthetic command fixture; never executed.\n')
        candidate = self.out / 'candidate'
        with patch.object(batch, 'is_windows', return_value=True), patch.object(batch.subprocess, 'run') as run:
            run.return_value.returncode = 0
            batch.invoke_word(self.root, candidate, ('en', 'articles'))
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, str(script)])
        self.assertEqual(command[command.index('--docx') + 1], str(candidate / self.fixture.docx))
        self.assertEqual(command[command.index('--language') + 1], 'en')
        self.assertEqual(command[command.index('--proof-dir') + 1], str(candidate / 'word-proof'))


if __name__ == '__main__':
    unittest.main()
