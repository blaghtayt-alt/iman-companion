"""Mutation tests for the read-only app/archive-to-book membership guard.

Small fixtures exercise the real selectors and snapshot/fingerprint functions;
they do not claim actual Word execution, source approval or remote release QA.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_app_book_coverage', ROOT / 'tools/check_app_book_coverage.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
from published_library import catalog_fingerprint, catalog_members, scope_settings
from preparation_queue import signature


class AppBookCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'repository'
        self.root.mkdir()
        self.app = Path(self.temp.name) / 'app'
        self.app.mkdir()
        (self.app / 'reader.js').write_text('Exact archived runtime', encoding='utf8')
        self.rows = [self.source(number) for number in (1, 2)]
        self.write('materials/catalog.json', {'entries': self.rows})
        self.write('books/reviewed-books.json', {'schema': 'iman-reviewed-books-v1', 'books': [
            {'language': 'en', 'collection': 'articles', 'state': 'reviewed-current',
             'automaticBuild': True, 'automaticRelease': True}]})
        self.write('books/config.json', {'languages': {'en': {'font': 'Latin'}},
                                        'fonts': {'Latin': {}, 'Arabic': {},
                                                  'FiqhSymbols': {'family': 'Synthetic Fiqh Symbols'}}})
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': []})
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': []})
        self.baseline = {'schemaVersion': 1, 'kind': guard.BASELINE_KIND,
                         'auditedDate': '2026-11-09', 'repositoryBase': 'a' * 40,
                         'appEvidence': {'archiveSHA256': 'b' * 64,
                                         'files': [self.binding(self.app, 'reader.js')],
                                         'method': 'Synthetic test inventory',
                                         'limitations': ['No actual app or publication review.']},
                         'units': [{**{k: row[k] for k in ('id', 'language', 'collection')},
                                    'evidenceLevel': 'identity-only',
                                    'catalogIdentity': {k: row[k] for k in guard.CATALOG_IDENTITY_FIELDS if k in row},
                                    'sourceBindings': [self.binding(self.root, row['markdown'])]}
                                   for row in self.rows],
                         'exclusions': [], 'knownAppGaps': []}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf8')

    @staticmethod
    def binding(root, relative):
        return {'path': relative, 'sha256': hashlib.sha256((root / relative).read_bytes()).hexdigest()}

    def source(self, number, **extra):
        relative = f'materials/articles/current/{number}.md'
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'Exact article {number} fixture text.\n', encoding='utf8')
        return {'id': f'article-{number}', 'language': 'en', 'collection': 'articles',
                'markdown': relative, **extra}

    def entry(self, rows, prepared=False):
        key = ('en', 'articles')
        ids = [row['id'] for row in rows]
        selected, report = catalog_members(self.root, key, for_release=False)
        snapshot = {'unitIds': sorted(ids), 'catalogSHA256': catalog_fingerprint(rows, report),
                    'scopeSettingsSHA256': scope_settings(self.root, key, ids),
                    'catalogMemberKeys': [{k: row[k] for k in ('collection', 'language', 'id')} for row in rows],
                    'bindings': [self.binding(self.root, row['markdown']) for row in rows]}
        book = {'language': key[0], 'collection': key[1], 'file': 'Iman_Companion_en_articles.docx',
                'sha256': 'c' * 64, 'pdfSha256': 'd' * 64, 'previewOnly': False,
                'preparationVerified' if prepared else 'exportVerified': True,
                'units': [{'id': ident, 'readerTextSHA256': 'e' * 64} for ident in ids]}
        return {'book': book, 'snapshot': snapshot, 'releaseTag': 'test-fixture-only'}

    def publish(self, rows=None):
        entry = self.entry(self.rows if rows is None else rows)
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': [entry]})
        return entry

    def prepare(self):
        row = {'language': 'en', 'collection': 'articles',
               'inputFingerprint': signature(self.root, ('en', 'articles')),
               'state': 'prepared-awaiting-release-qc', 'releaseVerified': False,
               'candidate': self.entry(self.rows, prepared=True)}
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})
        return row

    def check(self, app=False):
        return guard.audit(self.root, self.baseline, self.app if app else None)

    def codes(self, result):
        return {row['code'] for row in result['errors']}

    def test_valid_current_snapshot_and_optional_runtime_pins_are_read_only(self):
        self.publish()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.check(app=True)
        self.assertEqual(result['summary'], {'published-record-current': 2})
        self.assertEqual(result['runtimeEvidence']['state'], 'pins-match')
        self.assertFalse(result['sourceApprovalCreated'])
        self.assertFalse(result['releaseApprovalCreated'])
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_archived_app_evidence_is_not_claimed_as_current_without_app_root(self):
        result = self.check()
        self.assertEqual(result['runtimeEvidence']['state'], 'not-checked')
        self.assertFalse(result['runtimeEvidence']['archiveBytesChecked'])

    def test_same_count_catalog_identity_replacement_is_detected(self):
        replacement = self.source(99)
        self.write('materials/catalog.json', {'entries': [self.rows[0], replacement]})
        result = self.check()
        self.assertIn('baseline-unit-not-selected', self.codes(result))
        self.assertEqual(result['units'][1]['state'], 'missing-from-catalog')

    def test_same_id_catalog_source_path_replacement_is_detected(self):
        rows = deepcopy(self.rows)
        rows[0]['markdown'] = self.source(99)['markdown']
        self.write('materials/catalog.json', {'entries': rows})
        self.assertIn('baseline-source-drift', self.codes(self.check()))

    def test_deleted_reader_mapping_and_changed_revision_metadata_are_detected(self):
        rows = deepcopy(self.rows)
        del rows[0]['markdown']
        self.write('materials/catalog.json', {'entries': rows})
        self.assertIn('baseline-source-drift', self.codes(self.check()))
        rows = deepcopy(self.rows)
        rows[0]['sourceHashes'] = ['f' * 64]
        rows[0]['edition'] = 'different-source-edition'
        self.write('materials/catalog.json', {'entries': rows})
        self.assertIn('baseline-source-drift', self.codes(self.check()))

    def test_source_byte_drift_is_detected(self):
        (self.root / self.rows[0]['markdown']).write_text('Changed reader', encoding='utf8')
        self.assertIn('baseline-source-drift', self.codes(self.check()))

    def test_duplicate_baseline_and_duplicate_catalog_are_rejected(self):
        self.baseline['units'].append(deepcopy(self.baseline['units'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate baseline'):
            self.check()
        self.baseline['units'].pop()
        self.write('materials/catalog.json', {'entries': [*self.rows, self.rows[0]]})
        self.assertIn('duplicate-catalog-identity', self.codes(self.check()))

    def test_held_and_unbound_rows_are_not_admitted_by_baseline(self):
        rows = deepcopy(self.rows)
        rows[0]['status'] = 'held'
        self.write('materials/catalog.json', {'entries': rows})
        result = self.check()
        self.assertEqual(result['units'][0]['state'], 'held-or-retired')
        declaration = guard.read(self.root / 'books/reviewed-books.json')
        declaration['books'][0]['scopePolicy'] = 'reviewed-source-edition-v1'
        declaration['books'][0]['sourceReviewBindings'] = []
        self.write('books/reviewed-books.json', declaration)
        self.assertEqual(self.check()['units'][1]['state'], 'not-selected')

    def test_same_count_book_identity_replacement_and_snapshot_member_mismatch_fail(self):
        entry = self.publish()
        entry['book']['units'][0]['id'] = 'article-99'
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': [entry]})
        self.assertIn('invalid-published-membership', self.codes(self.check()))
        entry = self.publish()
        entry['snapshot']['catalogMemberKeys'][0]['id'] = 'article-99'
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': [entry]})
        self.assertIn('invalid-published-membership', self.codes(self.check()))

    def test_unverified_public_record_is_not_labelled_published(self):
        entry = self.publish()
        entry['book']['exportVerified'] = False
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': [entry]})
        result = self.check()
        self.assertIn('invalid-published-membership', self.codes(result))
        self.assertNotIn('published-record-current', result['summary'])

    def test_current_public_snapshot_cannot_hide_omission_with_consistent_shorter_lists(self):
        entry = self.publish()
        entry['book']['units'].pop()
        entry['snapshot']['unitIds'].pop()
        entry['snapshot']['catalogMemberKeys'].pop()
        self.write('books/published-library.json', {'schema': guard.LIBRARY_SCHEMA, 'entries': [entry]})
        self.assertIn('invalid-published-membership', self.codes(self.check()))

    def test_unchanged_older_subset_is_retained_without_claiming_new_unit_published(self):
        self.publish(self.rows[:1])
        self.prepare()
        result = self.check()
        self.assertFalse(result['errors'])
        self.assertEqual(result['summary'], {'published-record-current': 1, 'selected-and-prepared': 1})

    def test_stale_preparation_is_reported_without_being_admitted_or_blocking_source_update(self):
        self.prepare()
        config = guard.read(self.root / 'books/config.json')
        config['changedFixtureSetting'] = True
        self.write('books/config.json', config)
        result = self.check()
        self.assertFalse(result['errors'])
        self.assertEqual(result['summary'], {'selected-awaiting-preparation': 2})
        self.assertEqual(result['preparationScopes'][0]['state'], 'stale-inputs')

    def test_prepared_identity_tampering_and_duplicate_queue_scope_fail(self):
        row = self.prepare()
        row['candidate']['book']['units'][0]['id'] = 'article-99'
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})
        self.assertIn('invalid-prepared-membership', self.codes(self.check()))
        row = self.prepare()
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row, row]})
        with self.assertRaisesRegex(ValueError, 'Duplicate preparation queue scope'):
            self.check()

    def test_current_preparation_cannot_hide_omission_with_consistent_shorter_lists(self):
        row = self.prepare()
        row['candidate']['book']['units'].pop()
        row['candidate']['snapshot']['unitIds'].pop()
        row['candidate']['snapshot']['catalogMemberKeys'].pop()
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})
        self.assertIn('invalid-prepared-membership', self.codes(self.check()))

    def test_current_preparation_catalog_hash_and_source_bindings_cannot_be_tampered(self):
        row = self.prepare()
        row['candidate']['snapshot']['catalogSHA256'] = '0' * 64
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})
        self.assertIn('invalid-prepared-membership', self.codes(self.check()))
        row = self.prepare()
        row['candidate']['snapshot']['bindings'].pop()
        self.write('books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})
        self.assertIn('invalid-prepared-membership', self.codes(self.check()))

    def test_runtime_pin_change_and_path_escape_are_rejected(self):
        (self.app / 'reader.js').write_text('Different app runtime', encoding='utf8')
        self.assertIn('app-runtime-pins-stale', self.codes(self.check(app=True)))
        self.baseline['units'][0]['sourceBindings'][0]['path'] = '../outside.md'
        self.assertIn('baseline-source-drift', self.codes(self.check()))

    def test_known_gaps_remain_diagnostic_and_do_not_expand_selection(self):
        self.baseline['knownAppGaps'] = [{'id': 'not-yet-integrated', 'kind': 'fixture-only'}]
        self.baseline['exclusions'] = [{'id': 'obsolete-copy', 'reason': 'fixture-only'}]
        result = self.check()
        self.assertEqual(result['auditedUnits'], 2)
        self.assertEqual(result['knownAppGaps'], self.baseline['knownAppGaps'])
        self.assertEqual(result['exclusions'], self.baseline['exclusions'])
        self.assertNotIn('not-yet-integrated', {row['id'] for row in result['units']})

    def test_real_ikhlas_mirror_contract_requires_all_actual_adapter_inputs(self):
        from adapt_ikhlas import generate
        catalog = guard.read(ROOT / 'materials/catalog.json')
        for language in ('en', 'ja'):
            with self.subTest(language=language):
                key = (language, 'tadabbur-extended')
                # This contract concerns the real Ikhlas adapter, not the
                # release readiness of unrelated surahs in the same language.
                rows = [row for row in catalog['entries'] if row.get('id') == '112:extended'
                        and row.get('language') == language and row.get('collection') == 'tadabbur']
                self.assertEqual(len(rows), 1)
                # Exercise the real reader contract without depending on a pending
                # queue entry: successful release normally removes that entry.
                unit = generate(ROOT, catalog, guard.declaration(ROOT, key, for_release=False))[0]
                snapshot = {'bindings': deepcopy(unit['inputBindings'])}
                mirror = f'materials/tadabbur/{language}/extended/112.md'
                self.assertNotIn(mirror, {item['path'] for item in snapshot['bindings']})
                guard.validate_snapshot_sources(ROOT, catalog, key, rows, snapshot)
                consumed = f'materials/tadabbur/sources/112/{language}/112-001.json'
                snapshot['bindings'] = [item for item in snapshot['bindings'] if item['path'] != consumed]
                # Adding the unused mirror cannot substitute for a consumed verse source.
                snapshot['bindings'].append(self.binding(ROOT, mirror))
                with self.assertRaisesRegex(ValueError, 'actual Ikhlas adapter input'):
                    guard.validate_snapshot_sources(ROOT, catalog, key, rows, snapshot)


if __name__ == '__main__':
    unittest.main()
