"""Transport fixtures only: no real review, Word receipt, or approval is created."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import release_candidate_intake as intake


class CandidateTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'desktop-bundle'
        self.bundle.mkdir()
        self.manifest = {'schema': intake.SCHEMA, 'scopes': []}
        for collection in ['articles', 'seerah']:
            prefix = 'ar-' + collection
            scope = {'language': 'ar', 'collection': collection,
                     'prepared': prefix + '/prepared', 'candidate': prefix + '/candidate',
                     'handoff': prefix + '/handoff.json', 'acceptance': prefix + '/visual-acceptance.json'}
            self.manifest['scopes'].append(scope)
            for field in ['prepared', 'candidate']:
                directory = self.bundle / scope[field]
                directory.mkdir(parents=True)
                (directory / 'fixture.docx').write_bytes(('Synthetic ' + collection + ' ' + field).encode())
            for field in ['handoff', 'acceptance']:
                (self.bundle / scope[field]).write_bytes(b'{"fixture":"NOT review or approval evidence"}\n')
        self.original_manifest = json.dumps(self.manifest, ensure_ascii=False, indent='\t').encode() + b'\n'
        (self.bundle / 'bundle.json').write_bytes(self.original_manifest)
        self.counter = 0

    def next_path(self, suffix):
        self.counter += 1
        return self.root / (str(self.counter) + suffix)

    def packed(self):
        archive = self.next_path('.zip')
        return archive, intake.pack(self.bundle, archive)

    def rewritten(self, archive, changes=None, extra=None, missing=None):
        target = self.next_path('.zip')
        changes, extra, missing = changes or {}, extra or [], missing or set()
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as output:
            for info in source.infolist():
                if info.filename not in missing:
                    output.writestr(info, changes.get(info.filename, source.read(info)))
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                for name, raw, mode in extra:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = mode << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    output.writestr(info, raw)
        return target

    def assert_rejected(self, archive, pattern=None):
        output = self.next_path('-extracted')
        with self.assertRaisesRegex((ValueError, zipfile.BadZipFile), pattern or '.'):
            intake.extract(archive, hashlib.sha256(archive.read_bytes()).hexdigest(), output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob('.candidate-extract-*')), [])

    def extracted(self):
        archive, receipt = self.packed()
        output = self.next_path('-extracted')
        intake.extract(archive, receipt['sha256'], output)
        return output

    def test_deterministic_archive_preserves_manifest_and_every_evidence_byte(self):
        originals = {path.relative_to(self.bundle).as_posix(): path.read_bytes()
                     for path in self.bundle.rglob('*') if path.is_file()}
        first, receipt = self.packed()
        for path in self.bundle.rglob('*'):
            os.utime(path, (1700000000, 1700000000))
        second, repeated = self.packed()
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(receipt['sha256'], repeated['sha256'])
        self.assertEqual(receipt['bytes'], first.stat().st_size)
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), sorted([*originals, intake.INVENTORY]))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            hashes = json.loads(archive.read(intake.INVENTORY))['files']
            for name, raw in originals.items():
                self.assertEqual(archive.read(name), raw)
                self.assertEqual(hashes[name], {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        output = self.next_path('-extracted')
        extracted = intake.extract(first, receipt['sha256'], output)
        self.assertEqual(extracted['manifestSHA256'], hashlib.sha256(self.original_manifest).hexdigest())
        self.assertEqual(extracted['scopes'], 2)
        for name, raw in originals.items():
            self.assertEqual((output / name).read_bytes(), raw)
            self.assertEqual((self.bundle / name).read_bytes(), raw)
        self.assertFalse((self.bundle / intake.INVENTORY).exists())
        intake.validate_bundle(output)

    def test_archive_hash_mismatch_and_existing_outputs_never_replace_files(self):
        archive, receipt = self.packed()
        output = self.next_path('-extracted')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            intake.extract(archive, '0' * 64, output)
        self.assertFalse(output.exists())
        output.mkdir()
        (output / 'keep.txt').write_bytes(b'Keep existing extraction')
        with self.assertRaises(FileExistsError):
            intake.extract(archive, receipt['sha256'], output)
        self.assertEqual((output / 'keep.txt').read_bytes(), b'Keep existing extraction')
        before = archive.read_bytes()
        with self.assertRaises(FileExistsError):
            intake.pack(self.bundle, archive)
        self.assertEqual(archive.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'outside'):
            intake.pack(self.bundle, self.bundle / 'nested.zip')
        self.assertFalse((self.bundle / 'nested.zip').exists())

    def test_unsafe_duplicate_and_case_colliding_zip_paths_are_rejected(self):
        archive, _ = self.packed()
        for name in ['../escape', '/absolute', 'C:/drive', 'ar-articles\\candidate\\bad',
                     'ar-articles//candidate/bad', 'ar-articles/./candidate/bad', 'bundle.json', 'BUNDLE.JSON',
                     'ar-articles/candidate/CON', 'ar-articles/candidate/alias.', 'ar-articles/candidate/alias ']:
            with self.subTest(name=name):
                bad = self.rewritten(archive, extra=[(name, b'unsafe', stat.S_IFREG | 0o600)])
                self.assert_rejected(bad, 'path|Path')
        self.assertFalse((self.root / 'escape').exists())

    def test_zip_symlinks_and_special_files_are_rejected_before_extraction(self):
        archive, _ = self.packed()
        for kind in [stat.S_IFLNK, stat.S_IFIFO]:
            with self.subTest(kind=kind):
                bad = self.rewritten(archive, extra=[('ar-articles/candidate/link', b'../../outside', kind | 0o777)])
                self.assert_rejected(bad, 'symlinks|special')

    def test_file_digest_mismatch_missing_inventory_and_extra_files_leave_no_output(self):
        archive, _ = self.packed()
        name = 'ar-articles/candidate/fixture.docx'
        original = (self.bundle / name).read_bytes()
        changed = self.rewritten(archive, changes={name: b'x' * len(original)})
        self.assert_rejected(changed, 'pinned digest')
        self.assert_rejected(self.rewritten(archive, missing={intake.INVENTORY}), 'inventory')
        self.assert_rejected(self.rewritten(archive, missing={name}), 'Missing|inventory')
        self.assert_rejected(self.rewritten(archive, extra=[('unrelated.txt', b'unrelated', stat.S_IFREG | 0o600)]), 'Unreferenced')

    def test_compression_bomb_and_uncompressed_or_entry_limits_are_enforced(self):
        archive, _ = self.packed()
        bomb = self.rewritten(archive, extra=[('ar-articles/candidate/bomb', b'\0' * (3 * intake.CHUNK), stat.S_IFREG | 0o600)])
        self.assert_rejected(bomb, 'compression-ratio')
        with patch.object(intake, 'MAX_BYTES', 128):
            self.assert_rejected(archive, 'size')
        with patch.object(intake, 'MAX_FILES', 2):
            self.assert_rejected(archive, 'entry|entries')
        (self.bundle / 'ar-articles/candidate/bomb').write_bytes(b'\0' * (3 * intake.CHUNK))
        output = self.next_path('.zip')
        with self.assertRaisesRegex(ValueError, 'compression-ratio'):
            intake.pack(self.bundle, output)
        self.assertFalse(output.exists())

    def test_invalid_scope_envelopes_are_rejected_without_running_any_finalizer(self):
        extracted = self.extracted()
        duplicate = deepcopy(self.manifest)
        duplicate['scopes'].append(deepcopy(duplicate['scopes'][0]))
        unsupported = deepcopy(self.manifest)
        unsupported['scopes'][0]['collection'] = 'combined'
        overlap = deepcopy(self.manifest)
        overlap['scopes'][1]['prepared'] = overlap['scopes'][0]['candidate'] + '/nested'
        traversal = deepcopy(self.manifest)
        traversal['scopes'][0]['handoff'] = '../handoff.json'
        for manifest, pattern in [(duplicate, 'Duplicate'), (unsupported, 'Unsupported'),
                                  (overlap, 'overlap'), (traversal, 'confined')]:
            with self.subTest(pattern=pattern):
                (extracted / 'bundle.json').write_bytes(intake.encoded(manifest))
                finalizer = Mock(side_effect=AssertionError('Invalid envelopes must not invoke finalization'))
                out = self.next_path('-build')
                with self.assertRaisesRegex(ValueError, pattern):
                    intake.process(self.root, extracted, out, 'c' * 40, 'example/fixture', 'fixture', finalizer)
                finalizer.assert_not_called()
                self.assertFalse(out.exists())
        (self.bundle / 'bundle.json').write_bytes(b'{"schema":"x","schema":"y","scopes":[]}')
        output = self.next_path('.zip')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            intake.pack(self.bundle, output)
        self.assertFalse(output.exists())

    def test_local_symlinks_are_rejected_by_pack(self):
        target = self.root / 'outside.txt'
        target.write_bytes(b'Private unrelated fixture')
        link = self.bundle / 'ar-articles/candidate/linked.txt'
        link.symlink_to(target)
        output = self.next_path('.zip')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            intake.pack(self.bundle, output)
        self.assertFalse(output.exists())
        self.assertEqual(target.read_bytes(), b'Private unrelated fixture')

    def test_tampering_after_extraction_fails_before_finalization_and_preserves_report(self):
        bundle = self.extracted()
        (bundle / 'ar-articles/candidate/fixture.docx').write_bytes(b'Changed after hash verification')
        out = self.next_path('-build')
        out.mkdir()
        report = b'{"sourceCommit":"' + b'c' * 40 + b'","built":[],"failed":[]}\n'
        (out / 'build-report.json').write_bytes(report)
        finalizer = Mock()
        with self.assertRaisesRegex(ValueError, 'changed after packing'):
            intake.process(self.root, bundle, out, 'c' * 40, 'example/fixture', 'fixture', finalizer)
        finalizer.assert_not_called()
        self.assertEqual((out / 'build-report.json').read_bytes(), report)

    def test_scope_failure_is_isolated_and_success_does_not_duplicate_finalizer_built_row(self):
        bundle = self.extracted()
        out = self.next_path('-build')
        out.mkdir()
        original = {'sourceCommit': 'c' * 40,
                    'built': [{'language': 'ar', 'collection': 'tadabbur-extended', 'folder': 'existing-quran'}],
                    'prepared': [{'language': 'ar', 'collection': 'articles'}], 'unchanged': [],
                    'failed': [{'language': 'en', 'collection': 'articles', 'error': 'Existing failure'}],
                    'sourceTransactionErrors': [{'fixture': 'Preserve unrelated report data'}]}
        (out / 'build-report.json').write_bytes(intake.encoded(original))
        calls = []
        def finalizer(root, prepared, candidate, handoff, acceptance, build_out, commit, repo, tag):
            calls.append((root, prepared, candidate, handoff, acceptance, build_out, commit, repo, tag))
            if prepared.parent.name == 'ar-articles':
                raise ValueError('Fixture evidence incomplete; no approval was generated')
            report = json.loads((build_out / 'build-report.json').read_bytes())
            report['built'].append({'language': 'ar', 'collection': 'seerah', 'folder': 'ar-seerah-finalized'})
            (build_out / 'build-report.json').write_bytes(intake.encoded(report))
            return {'fixture': True, 'language': 'ar', 'collection': 'seerah'}
        result = intake.process(self.root, bundle, out, 'c' * 40, 'example/fixture', 'fixture', finalizer)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1:5], tuple(bundle / self.manifest['scopes'][0][field] for field in intake.PATH_FIELDS))
        self.assertEqual(len(result['finalized']), 1)
        self.assertEqual(result['failed'][0]['collection'], 'articles')
        report = json.loads((out / 'build-report.json').read_bytes())
        self.assertEqual(report['built'], original['built'] + [{'language': 'ar', 'collection': 'seerah', 'folder': 'ar-seerah-finalized'}])
        self.assertEqual(report['failed'][0], original['failed'][0])
        self.assertEqual(len(report['failed']), 2)
        self.assertEqual(report['failed'][1]['stage'], 'finalized-candidate-intake')
        self.assertEqual(report['sourceTransactionErrors'], original['sourceTransactionErrors'])
        self.assertEqual(report['prepared'], original['prepared'])
        self.assertFalse(any(name.endswith('-finalized') for name in os.listdir(bundle)))

    def test_stale_report_and_overlapping_build_output_are_rejected(self):
        bundle = self.extracted()
        finalizer = Mock()
        with self.assertRaisesRegex(ValueError, 'separate'):
            intake.process(self.root, bundle, bundle / 'out', 'c' * 40, 'example/fixture', 'fixture', finalizer)
        out = self.next_path('-build')
        out.mkdir()
        original = intake.encoded({'sourceCommit': 'd' * 40, 'built': [], 'failed': []})
        (out / 'build-report.json').write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'publication commit'):
            intake.process(self.root, bundle, out, 'c' * 40, 'example/fixture', 'fixture', finalizer)
        finalizer.assert_not_called()
        self.assertEqual((out / 'build-report.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
