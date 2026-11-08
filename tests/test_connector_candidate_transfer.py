"""Synthetic transport fixtures; no real Word/visual acceptance is manufactured."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
import base64
import io
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import connector_candidate_transfer as bridge
import release_candidate_intake as intake


class ConnectorTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = 'example/fixture'
        self.commit = 'a' * 40
        self.source = 'b' * 40
        self.out = self.root / 'build'
        self.out.mkdir()
        self.reset_report()
        self.bundle = self.root / 'review'
        self.bundle.mkdir()
        self.bundle_manifest = {'schema': intake.SCHEMA, 'scopes': []}
        self.serial = 0
        self.blobs = {}
        self.fetcher = Mock(side_effect=lambda repo, chunk: self.blobs[chunk['blobSHA']])
        self.add_scope('articles')

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(intake.encoded(value))

    def reset_report(self):
        self.write(self.out / 'build-report.json', {'sourceCommit': self.commit, 'built': [], 'prepared': [],
                                                  'unchanged': [], 'failed': [], 'fixtureData': 'preserve'})

    def add_scope(self, collection):
        prefix = 'ar-' + collection
        scope = {'language': 'ar', 'collection': collection, 'prepared': prefix + '/prepared',
                 'candidate': prefix + '/candidate', 'handoff': prefix + '/handoff.json',
                 'acceptance': prefix + '/visual-acceptance.json'}
        self.bundle_manifest['scopes'].append(scope)
        prepared, candidate = bridge.scope_files(scope)
        for field, names in [('prepared', prepared), ('candidate', candidate)]:
            for name in names:
                target = self.bundle / scope[field] / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'{}\n' if name.endswith('.json') else ('Synthetic fixture ' + field + ' ' + name).encode())
        self.write(self.bundle / scope['handoff'], {'schema': 'iman-prepared-book-handoff-v1',
                   'language': 'ar', 'collection': collection, 'sourceCommit': self.source,
                   'inputFingerprint': ('c' if collection == 'articles' else 'd') * 64})
        self.write(self.bundle / scope['acceptance'], {'accepted': False, 'fixture': 'NOT visual acceptance'})
        self.write(self.bundle / 'bundle.json', self.bundle_manifest)
        queue = [{'language': s['language'], 'collection': s['collection'], 'sourceCommit': self.source,
                  'inputFingerprint': ('c' if s['collection'] == 'articles' else 'd') * 64,
                  'state': 'prepared-awaiting-release-qc', 'releaseVerified': False}
                 for s in self.bundle_manifest['scopes']]
        self.write(self.root / 'books/prepared-library.json', {'entries': queue})
        return scope

    def transferred(self, minimum=True):
        self.serial += 1
        output = self.root / ('transport-' + str(self.serial))
        if minimum:
            verifier = Mock()
            result = bridge.prepare(self.root, self.bundle, output, self.repo, 1024, verifier)
            self.assertEqual(verifier.call_count, len(self.bundle_manifest['scopes']))
            source = Path(result['manifest'])
            manifest = json.loads(source.read_bytes())
            for index, chunk in enumerate(manifest['chunks']):
                self.blobs[chunk['blobSHA']] = base64.b64decode((output / 'chunks' / f'{index:04d}.b64').read_bytes())
        else:
            output.mkdir()
            archive = output / 'candidate.zip'
            packed = intake.pack(self.bundle, archive)
            raw = archive.read_bytes()
            chunk = {'blobSHA': bridge.git_blob_sha(raw), 'sha256': bridge.sha(raw), 'bytes': len(raw)}
            self.blobs[chunk['blobSHA']] = raw
            manifest = {'schema': bridge.SCHEMA, 'repository': self.repo, 'archiveSHA256': packed['sha256'],
                        'archiveBytes': packed['bytes'], 'chunks': [chunk],
                        'scopes': [{name: json.loads((self.bundle / s['handoff']).read_bytes())[name]
                                    for name in bridge.SCOPE_KEYS} for s in self.bundle_manifest['scopes']]}
            source = output / (manifest['archiveSHA256'] + '.json')
            self.write(source, manifest)
        target = self.root / bridge.INTAKE / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return manifest, target, output

    def process(self, finalizer):
        return bridge.process(self.root, self.out, self.commit, self.repo, 'fixture-release', self.fetcher, finalizer)

    def synthetic_finalizer(self, root, prepared, candidate, handoff, acceptance, out, commit, repo, tag):
        """Lifecycle stand-in only; release checks are independently tested below."""
        identity = {name: json.loads(handoff.read_bytes())[name] for name in bridge.SCOPE_KEYS}
        docx = 'Iman_Companion_ar_' + identity['collection'] + '.docx'
        folder = 'ar-' + identity['collection'] + '-finalized'
        result = {**identity, 'schema': 'iman-finalized-book-candidate-v1', 'state': 'verified-release-candidate',
                  'publicationCommit': commit, 'folder': folder,
                  'docxSHA256': bridge.sha((candidate / docx).read_bytes()),
                  'pdfSHA256': bridge.sha((candidate / Path(docx).with_suffix('.pdf')).read_bytes())}
        self.write(out / folder / 'finalization-receipt.json', result)
        report = json.loads((out / 'build-report.json').read_bytes())
        report['built'].append({'language': identity['language'], 'collection': identity['collection'], 'folder': folder})
        self.write(out / 'build-report.json', report)
        return result

    def published_entries(self):
        report = json.loads((self.out / 'build-report.json').read_bytes())
        return [{'book': {**item['candidate'], 'sha256': item['candidate']['docxSHA256'],
                          'pdfSha256': item['candidate']['pdfSHA256']}, 'releaseTag': 'fixture-release'}
                for item in report.get('connectorFinalizedCandidates', [])]

    def test_prepare_excludes_private_extras_and_preserves_exact_required_bytes(self):
        scope = self.bundle_manifest['scopes'][0]
        audit = self.bundle / scope['candidate'] / 'private-audit.json'
        self.write(audit, {'root': 'C:\\Users\\Private\\Documents', 'pids': [123]})
        before = {p.relative_to(self.bundle).as_posix(): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        manifest, _, output = self.transferred()
        unpacked = self.root / 'unpacked'
        intake.extract(output / 'finalized-books.zip', manifest['archiveSHA256'], unpacked)
        self.assertFalse((unpacked / scope['candidate'] / audit.name).exists())
        self.assertEqual({p.relative_to(self.bundle).as_posix(): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}, before)
        for name, raw in before.items():
            if name != scope['candidate'] + '/' + audit.name:
                self.assertEqual((unpacked / name).read_bytes(), raw)
        self.assertFalse((output / 'evidence').exists())

    def test_public_metadata_rejected_before_any_output_or_upload(self):
        scope = self.bundle_manifest['scopes'][0]
        file = self.bundle / scope['prepared'] / 'prepared-snapshot.json'
        for data in [{'localArtifacts': []}, {'file': 'C:\\Users\\Private\\book.docx'},
                     {'root': '/home/private/review'}, {'proof': '\\\\private\\share\\book.pdf'}]:
            with self.subTest(data=data):
                self.write(file, data)
                verifier = Mock()
                output = self.root / 'rejected'
                with self.assertRaisesRegex(ValueError, 'localArtifacts|machine paths'):
                    bridge.prepare(self.root, self.bundle, output, self.repo, verifier=verifier)
                self.assertFalse(output.exists())
                verifier.assert_not_called()

    def test_manifest_rejects_wrong_repository_unknown_fields_duplicate_scopes_and_bad_sizes(self):
        manifest, _, _ = self.transferred()
        alternatives = []
        for name, value in [('repository', 'different/private'), ('archiveBytes', True), ('archiveSHA256', 'A' * 64)]:
            changed = deepcopy(manifest); changed[name] = value; alternatives.append(changed)
        changed = deepcopy(manifest); changed['url'] = 'https://external.invalid'; alternatives.append(changed)
        changed = deepcopy(manifest); changed['scopes'].append(changed['scopes'][0]); alternatives.append(changed)
        changed = deepcopy(manifest); changed['chunks'][0]['bytes'] += 1; alternatives.append(changed)
        for changed in alternatives:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    bridge.validate_manifest(changed, self.repo)

    def test_chunks_are_checked_against_git_sha_sha256_size_order_and_archive(self):
        manifest, _, _ = self.transferred()
        for field in ['blobSHA', 'sha256', 'bytes']:
            changed = deepcopy(manifest)
            changed['chunks'][0][field] = 1 if field == 'bytes' else '0' * (40 if field == 'blobSHA' else 64)
            self.serial += 1
            fetcher = lambda repo, chunk: self.blobs[manifest['chunks'][0]['blobSHA']]
            with self.subTest(field=field), self.assertRaises(ValueError):
                bridge.assemble(changed, self.root / f'bad-{self.serial}.zip', fetcher)
        for changed in [dict(manifest, chunks=list(reversed(manifest['chunks']))), dict(manifest, archiveSHA256='0' * 64)]:
            self.serial += 1
            with self.assertRaisesRegex(ValueError, 'exact candidate archive'):
                bridge.assemble(changed, self.root / f'bad-{self.serial}.zip', self.fetcher)

    def test_fetch_uses_fixed_host_and_repository_and_bounds_the_response(self):
        raw = b'synthetic pinned blob'
        chunk = {'blobSHA': bridge.git_blob_sha(raw), 'sha256': bridge.sha(raw), 'bytes': len(raw)}
        payload = {'sha': chunk['blobSHA'], 'size': len(raw), 'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
        process = Mock(stdout=io.BytesIO(json.dumps(payload).encode()))
        process.wait.return_value = 0; process.poll.return_value = 0
        with patch.object(bridge.subprocess, 'Popen', return_value=process) as start, patch.object(bridge, 'Timer'):
            self.assertEqual(bridge.fetch_blob(self.repo, chunk), raw)
        args = start.call_args.args[0]
        self.assertEqual(args, ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                               'repos/' + self.repo + '/git/blobs/' + chunk['blobSHA']])
        process = Mock(stdout=io.BytesIO(b'x' * 20000)); process.poll.return_value = None
        with patch.object(bridge.subprocess, 'Popen', return_value=process), patch.object(bridge, 'Timer'):
            with self.assertRaisesRegex(ValueError, 'size bound'):
                bridge.fetch_blob(self.repo, chunk)
        process.kill.assert_called_once()

    def test_stale_declaration_and_duplicate_keys_never_fetch_blobs(self):
        manifest, target, _ = self.transferred()
        manifest['scopes'][0]['inputFingerprint'] = 'e' * 64
        self.write(target, manifest)
        finalizer = Mock()
        result = self.process(finalizer)
        self.assertIn('current preparation queue', result['failed'][0]['error'])
        self.fetcher.assert_not_called(); finalizer.assert_not_called()
        target.write_bytes(b'{"schema":"x","schema":"y"}')
        result = self.process(finalizer)
        self.assertIn('Duplicate JSON key', result['failed'][0]['error'])
        self.fetcher.assert_not_called()

    def test_conflicting_current_transfers_are_both_rejected_before_download(self):
        self.transferred()
        scope = self.bundle_manifest['scopes'][0]
        (self.bundle / scope['candidate'] / 'Iman_Companion_ar_articles.pdf').write_bytes(b'Another synthetic proof')
        self.transferred()
        finalizer = Mock()
        result = self.process(finalizer)
        self.assertEqual(len(result['failed']), 2)
        self.assertTrue(all('Conflicting pending transfers' in row['error'] for row in result['failed']))
        self.fetcher.assert_not_called(); finalizer.assert_not_called()

    def test_extra_archive_files_are_rejected_before_finalization(self):
        scope = self.bundle_manifest['scopes'][0]
        (self.bundle / scope['candidate'] / 'private.txt').write_bytes(b'Unrelated local diagnostic')
        self.transferred(minimum=False)
        finalizer = Mock()
        result = self.process(finalizer)
        self.assertIn('minimal public evidence inventory', result['failed'][0]['error'])
        finalizer.assert_not_called()

    def test_existing_finalizer_still_rejects_absent_visual_acceptance(self):
        import finalize_prepared
        scope = self.bundle_manifest['scopes'][0]
        handoff = json.loads((self.bundle / scope['handoff']).read_bytes())
        template = finalize_prepared.acceptance_template(handoff, self.bundle / scope['candidate'])
        self.assertIs(template['accepted'], False)
        self.write(self.bundle / scope['acceptance'], template)
        self.transferred()
        def plan(root, prepared):
            return json.loads((prepared.parent / 'handoff.json').read_bytes())
        with patch.object(finalize_prepared, 'git_head', return_value=self.commit), patch.object(finalize_prepared, 'plan', side_effect=plan):
            result = self.process(None)
        self.assertEqual(result['finalized'], [])
        self.assertIn('Explicit visual acceptance', result['failed'][0]['error'])
        self.assertEqual(json.loads((self.out / 'build-report.json').read_bytes())['built'], [])
        self.assertFalse((self.root / bridge.HISTORY).exists())

    def test_finalized_scope_is_consumed_only_after_matching_published_pair(self):
        manifest, target, _ = self.transferred()
        result = self.process(self.synthetic_finalizer)
        self.assertEqual(len(result['finalized']), 1)
        self.assertFalse((self.root / bridge.HISTORY).exists())
        entries = self.published_entries()
        bad = deepcopy(entries); bad[0]['book']['pdfSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'consumed transfer hashes'):
            bridge.record_published(self.root, self.out, bad, self.repo)
        self.assertFalse((self.root / bridge.HISTORY).exists())
        bridge.record_published(self.root, self.out, entries, self.repo)
        history = self.root / bridge.HISTORY / (bridge.sha(target.read_bytes()) + '.json')
        self.assertEqual(len(json.loads(history.read_bytes())['scopes']), 1)
        self.reset_report(); self.fetcher.reset_mock()
        finalizer = Mock()
        retry = self.process(finalizer)
        self.assertEqual(retry, {'finalized': [], 'failed': [], 'skipped': 1})
        self.fetcher.assert_not_called(); finalizer.assert_not_called()

    def test_partial_success_consumes_only_the_verified_scope_and_preserves_other_report_data(self):
        self.add_scope('seerah')
        self.transferred()
        def finalizer(*args):
            if args[1].parent.name == 'ar-articles':
                raise ValueError('Synthetic Word gate failure')
            return self.synthetic_finalizer(*args)
        result = self.process(finalizer)
        self.assertEqual(result['finalized'], [{'language': 'ar', 'collection': 'seerah'}])
        self.assertEqual(len(result['failed']), 1)
        bridge.record_published(self.root, self.out, self.published_entries(), self.repo)
        receipt = json.loads(next((self.root / bridge.HISTORY).glob('*.json')).read_bytes())
        self.assertEqual([s['collection'] for s in receipt['scopes']], ['seerah'])
        self.assertEqual(json.loads((self.out / 'build-report.json').read_bytes())['fixtureData'], 'preserve')
        self.reset_report()
        result = self.process(finalizer)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(len(result['failed']), 1)

    def test_symlinked_manifest_never_reads_an_unrelated_file(self):
        _, target, _ = self.transferred()
        original = target.read_bytes()
        private = self.root / 'unrelated-private.json'; private.write_bytes(original)
        target.unlink(); target.symlink_to(private)
        finalizer = Mock()
        result = self.process(finalizer)
        self.assertIn('Symlinked', result['failed'][0]['error'])
        self.fetcher.assert_not_called(); finalizer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
