import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'materials/hadith-bank/organized'
sys.path.insert(0, str(DIRECTORY))
from provenance import Provenance, digest, pointer
spec = importlib.util.spec_from_file_location('bank_search', DIRECTORY / 'search.py')
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


class TranslationProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = Provenance(DIRECTORY / 'TRANSLATION-PROVENANCE.json')
        cls.index = json.loads((DIRECTORY / 'INDEX.json').read_text())

    def load_changed(self, change):
        data = copy.deepcopy(self.ledger.data)
        change(data)
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'ledger.json'
            path.write_text(json.dumps(data))
            return Provenance(path)

    def run_cli(self, *args):
        def local_open(url, timeout):
            prefix = 'https://raw.githubusercontent.com/blaghtayt-alt/iman-companion/'
            self.assertTrue(url.startswith(prefix))
            path = url[len(prefix):].split('/', 1)[1]
            return io.BytesIO((ROOT / path).read_bytes())
        out = io.StringIO()
        with patch.object(sys, 'argv', ['search.py', *args]), patch('urllib.request.urlopen', side_effect=local_open), contextlib.redirect_stdout(out):
            search.main()
        return json.loads(out.getvalue())

    def test_all_exact_sources_and_occurrences(self):
        self.assertEqual(self.ledger.verify_local_sources(ROOT), 17)
        self.assertEqual(sum(len(row['occurrences']) for row in self.ledger.records), 23)

    def test_known_labels_do_not_certify_unknown_material(self):
        self.assertEqual(self.ledger.data['defaultTranslationOrigin'], 'unknown')
        self.assertIsNone(self.ledger.data['defaultDisclosureLabel'])
        counts = {origin: sum(row['translationOrigin'] == origin for row in self.ledger.records) for origin in ('ai', 'human')}
        self.assertEqual(counts, {'ai': 16, 'human': 1})
        self.assertFalse(self.ledger.data['independentProvenanceAudit']['completed'])

    def test_historical_roles_not_falsely_astra(self):
        for row in self.ledger.records:
            if row['translationOrigin'] == 'ai':
                self.assertEqual(row['translator'], {'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'})
                self.assertEqual(row['review']['model'], 'gpt-6.1-sol')
                self.assertEqual(row['review']['reasoningEffort'], 'high')
                self.assertNotIn('Astra', row['disclosure']['label'])
                self.assertNotIn(row['review']['status'], ['passed', 'approved'])
        pt = next(row for row in self.ledger.records if row['language'] == 'pt-BR')
        self.assertEqual(pt['review']['status'], 'conflicting_records')

    def test_human_label_has_actual_source_credit(self):
        row = next(row for row in self.ledger.records if row['translationOrigin'] == 'human')
        self.assertEqual(row['humanTranslator'], 'Abu Iyaad Amjad Rafiq')
        self.assertIn(row['humanTranslator'], row['sourceEdition'])
        self.assertIsNone(row['review']['model'])

    def test_rejects_false_default_label(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d.update(defaultTranslationOrigin='human'))

    def test_rejects_missing_actual_model(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][0].update(translator=None))

    def test_rejects_unknown_with_ai_claim(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][0].update(translationOrigin='unknown'))

    def test_rejects_human_without_named_translator(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][-1].update(humanTranslator=None))

    def test_rejects_silent_disclosure_stripping(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][0]['disclosure'].update(mustAccompanyText=False))

    def test_rejects_text_mutation_and_duplicate_ids(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][0].update(translationText='altered'))
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'].append(copy.deepcopy(d['records'][0])))

    def test_rejects_new_review_pass(self):
        with self.assertRaises(ValueError):
            self.load_changed(lambda d: d['records'][0]['review'].update(status='passed'))

    def test_version_mismatch_never_inherits_label(self):
        row = self.ledger.records[0]
        file = dict(row['reading'], sha256='0' * 64)
        self.assertEqual(self.ledger.for_file(file), [])
        file = dict(row['reading'], url=row['reading']['url'].replace('essential-ms', 'essential-en'))
        self.assertEqual(self.ledger.for_file(file), [])

    def test_exact_passage_not_whole_mixed_reading(self):
        row = self.ledger.records[0]
        self.assertEqual(len(self.ledger.for_file(row['reading'], '/reading/commentarySections/5/text')), 1)
        self.assertEqual(self.ledger.for_file(row['reading'], '/reading/mainNarration'), [])
        self.assertEqual(self.ledger.for_file(row['reading'], '/reading/commentarySections/50'), [])

    def test_source_binding_does_not_label_arabic(self):
        row = self.ledger.records[0]
        source = row['sourceTextLocator']
        self.assertEqual(len(self.ledger.for_file(source['file'], source['jsonPointer'])), 1)
        self.assertEqual(self.ledger.for_file(source['file'], '/originalArabic'), [])

    def test_search_exposes_labels_and_uncertainty(self):
        out = self.run_cli('search', '--kind', 'translation', '--translation-origin', 'ai', '--limit', '100')
        self.assertEqual(out['count'], 16)
        for result in out['results']:
            self.assertTrue(result['translationDisclosures'][0]['disclosure']['mustAccompanyText'])
        self.assertIn('unclassified', out['translationProvenance']['unknown'])
        self.assertEqual(self.run_cli('search', '--kind', 'translation', '--translation-origin', 'human')['count'], 1)

    def test_existing_package_search_includes_only_matching_spans(self):
        out = self.run_cli('search', '--kind', 'package', '--language', 'ms', '--chapter', 'essential-01-001')
        self.assertEqual(out['count'], 1)
        self.assertEqual(len(out['results'][0]['translationDisclosures']), 1)

    def test_resolve_retains_exact_text_with_disclosure(self):
        for row in self.ledger.records:
            out = self.run_cli('resolve', row['id'])
            self.assertEqual(out['value'], row['translationText'])
            self.assertEqual(out['translationDisclosures'][0]['id'], row['id'])

    def test_resolve_unclassified_text_stays_unlabelled(self):
        out = self.run_cli('resolve', 'package:ms:essential-01-001', '--pointer', '/reading/mainNarration')
        self.assertEqual(out['translationDisclosures'], [])
        self.assertIn('unclassified', out['translationProvenance']['unknown'])

    def test_resolve_whole_reading_keeps_labels_separate(self):
        out = self.run_cli('resolve', 'package:ms:essential-01-001')
        self.assertEqual(out['value'], json.loads((ROOT / 'materials/hadith/essential-ms/001.json').read_text()))
        self.assertEqual(len(out['translationDisclosures']), 1)
        self.assertNotIn('translationDisclosures', out['value'])

    def test_missing_ledger_fails_closed(self):
        with self.assertRaises(OSError):
            self.run_cli('--provenance', '/nonexistent-ledger', 'search')

    def test_existing_chapter_query_unchanged(self):
        out = self.run_cli('search', '--kind', 'chapter', '--limit', '12')
        self.assertEqual(out['count'], len(self.index['chapters']))
        self.assertTrue(all(not result['translationDisclosures'] for result in out['results']))

    def test_span_tampering_is_detected(self):
        def tamper(data):
            data['records'][0]['occurrences'][0]['codepointStart'] += 1
            data['records'][0]['occurrences'][0]['codepointEnd'] += 1
        ledger = self.load_changed(tamper)
        with self.assertRaises(ValueError):
            ledger.verify_local_sources(ROOT)


if __name__ == '__main__':
    unittest.main()
