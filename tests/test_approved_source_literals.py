"""Exact Article/Seerah source credits survive intake without a URL allowlist.

Every approval in this file is a synthetic test fixture, not a real review.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'books'))
from bibliography import native_text
from build_books import check_unit
from publish_approved_material import apply, prepare
from source_literal_text import check_bound_text


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ApprovedSourceLiteralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.text = 'Exact supplied source credit: QuranEnc.com.\nVersion 1.0.'
        self.material = {'collection': 'seerah', 'language': 'en', 'id': 'new-seerah001'}
        self.source = self.write('materials/seerah/new-adult/en/01.txt',
                                 ('Chapter One\r\n\r\n' + self.text + '\r\n').encode())
        self.markdown = self.write('materials/seerah/new-adult/en/01.md',
                                   ('# Chapter One\n\n' + self.text + '\n').encode())
        self.inventory = {
            'schema': 'iman-approved-reader-source-v1', 'material': self.material,
            'current': True, 'readingSource': self.source,
            'sourceBindings': [self.source, self.markdown],
            'approval': {'decision': 'approved', 'wholeMaterial': True,
                         'approvalId': 'TEST-FIXTURE-ONLY',
                         'reviewer': {'kind': 'fixture', 'id': 'No real approval'},
                         'semanticReviewSHA256': sha(b'fictional semantic fixture'),
                         'sourceAcceptanceSHA256': sha(b'fictional acceptance fixture'),
                         'readerTextSHA256': sha(self.text.encode())}}
        self.proof = {
            'schema': 'iman-source-literal-text-v1', 'collection': 'seerah',
            'language': 'en', 'materialId': 'new-seerah001',
            'readerTextSHA256': sha(self.text.encode()), 'source': self.source,
            'pointer': [], 'start': len('Chapter One\n\n'),
            'end': len('Chapter One\n\n') + len(self.text),
            'textSHA256': sha(self.text.encode())}
        self.unit = {
            'schema': 'iman-book-unit-v1', **self.material, 'title': 'Chapter One',
            'order': 1, 'chapter': 1, 'complete': True, 'reviewGate': 'published-current',
            'sourceHashes': [self.source['sha256']], 'readerTextSHA256': sha(self.text.encode()),
            'catalogBindings': [self.material], 'sections': [{'blocks': [
                {'kind': 'paragraph', 'text': self.text, 'sourceLiteralProof': self.proof}]}]}
        self.refresh_inventory()
        self.write('materials/catalog.json', {'languages': ['en'], 'scope': 'current', 'entries': []})
        self.write('books/assets/quran-arabic.json', {})
        self.write('books/reviewed-books.json', {'schema': 'iman-reviewed-books-v1', 'books': []})

    def write(self, path, value):
        raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {'path': path, 'sha256': sha(raw)}

    def refresh_inventory(self):
        binding = self.write('materials/source-acceptances/fixture.json', self.inventory)
        self.proof['inventory'] = binding
        self.unit['inputBindings'] = [self.source, self.markdown, binding]

    def check(self, unit=None, proof=None, text=None):
        return check_bound_text(self.root, self.text if text is None else text,
                                self.unit if unit is None else unit,
                                self.proof if proof is None else proof, exact=True)

    def test_exact_credit_before_first_catalogue_entry_and_scope(self):
        with self.assertRaises(ValueError):
            native_text(self.text, 'en')
        self.assertEqual(self.check(), self.text)
        check_unit(self.unit, self.material, {}, root=self.root)

    def test_missing_binding_or_changed_source_and_inventory_rejected(self):
        changed = deepcopy(self.unit)
        changed['inputBindings'].pop()
        with self.assertRaises(ValueError):
            self.check(unit=changed)
        for binding in (self.source, self.proof['inventory']):
            path = self.root / binding['path']
            raw = path.read_bytes()
            path.write_bytes(raw + b' ')
            with self.assertRaises(ValueError):
                self.check()
            path.write_bytes(raw)

    def test_proof_cannot_hide_added_url_or_changed_source_text(self):
        for value in (self.text + ' https://unreviewed.test',
                      self.text.replace('1.0', '2.0'), self.text[:-1]):
            with self.assertRaises(ValueError):
                self.check(text=value)
        proof = deepcopy(self.proof)
        proof['end'] -= 1
        with self.assertRaises(ValueError):
            self.check(proof=proof)

    def test_source_acceptance_identity_scope_and_receipts_are_required(self):
        for key, value in [('decision', 'pending'), ('wholeMaterial', False),
                           ('reviewer', None), ('approvalId', ''),
                           ('semanticReviewSHA256', ''), ('sourceAcceptanceSHA256', ''),
                           ('readerTextSHA256', '0' * 64)]:
            with self.subTest(key=key):
                original = deepcopy(self.inventory)
                self.inventory['approval'][key] = value
                self.refresh_inventory()
                with self.assertRaises(ValueError):
                    self.check()
                self.inventory = original
                self.refresh_inventory()
        for key, value in [('language', 'fr'), ('id', 'new-seerah002'), ('collection', 'hadith')]:
            changed = deepcopy(self.unit)
            changed[key] = value
            with self.assertRaises(ValueError):
                self.check(unit=changed)
        self.inventory['current'] = False
        self.refresh_inventory()
        with self.assertRaises(ValueError):
            self.check()

    def test_literal_acceptance_does_not_replace_publisher_approval(self):
        reader = self.write('materials/book-readers/en-seerah001.json', self.unit)
        handoff = {
            'schema': 'iman-approved-material-publication-v1',
            'expectedCatalogSHA256': sha((self.root / 'materials/catalog.json').read_bytes()),
            'catalogEntry': {**self.material, 'edition': 'new-adult', 'chapter': 1,
                             'markdown': self.markdown['path'], 'current': True},
            'sourceBindings': [self.source, self.markdown], 'canonicalOrder': 1,
            'readerUnit': reader,
            'approval': {'decision': 'approved', 'wholeMaterial': True,
                         'approvalId': 'TEST-FIXTURE-ONLY', 'reviewer': {'kind': 'fixture'},
                         'material': self.material, 'readerTextSHA256': self.unit['readerTextSHA256'],
                         'reviewArtifacts': [self.proof['inventory']]}}
        path = self.root / self.write('handoff.json', handoff)['path']
        prepare(self.root, path)
        for key, value in [('decision', 'pending'), ('wholeMaterial', False),
                           ('readerTextSHA256', '0' * 64), ('reviewArtifacts', [])]:
            changed = deepcopy(handoff)
            changed['approval'][key] = value
            self.write('handoff.json', changed)
            with self.assertRaises(ValueError):
                prepare(self.root, path)
        self.write('handoff.json', handoff)
        receipt = apply(self.root, path)
        self.assertTrue(receipt['preparationScopeCreated'])
        self.assertFalse(receipt['sourceApprovalCreated'])
        self.assertFalse(receipt['scopeReleaseHoldsChanged'])
        from book_edition_scope import typed_basis
        entry = json.loads((self.root / 'materials/catalog.json').read_bytes())['entries'][0]
        self.assertIsNotNone(typed_basis(self.root, entry))


if __name__ == '__main__':
    unittest.main()
