"""Unimplemented app collections must remain visible without becoming approved."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
from multilingual_readiness import inventory


class MaterialCatalogPartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('books/config.json', {'languages': {'ja': {}, 'ar': {}}})
        self.write('books/reviewed-books.json', {'schema': 'iman-reviewed-books-v1', 'books': []})
        self.write('materials/catalog.json', {'entries': []})

    def write(self, path, value):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')

    def test_reviewed_claim_and_unsupported_collection_do_not_disappear_or_gain_approval(self):
        path = 'materials/heart-reminder/ja/001.json'
        rows = [{'language': 'ja', 'collection': 'heart-reminder', 'id': '001',
                 'json': path, 'status': 'current-app-edition',
                 'translationStatus': 'independently-model-reviewed-needs-verification'},
                {'language': 'ar', 'collection': 'articles', 'id': 1}]
        before = deepcopy(rows)
        self.write(path, {'reader': 'Original app reader fixture'})
        self.write('materials/catalog.json', {'entries': rows})
        result = inventory(self.root)
        self.assertEqual(result['catalogPartition'], {'totalMaterials': 2, 'mappedCollectionMaterials': 1,
            'unmappedCollectionMaterials': 1, 'unaccountedMaterials': 0})
        extra = result['unmappedMaterialScopes'][0]
        self.assertEqual((extra['language'], extra['collection'], extra['materialCount']), ('ja', 'heart-reminder', 1))
        self.assertEqual(extra['exportState'], 'no-book-collection-adapter')
        self.assertTrue(extra['materials'][0]['sourceFiles'][0]['installed'])
        self.assertEqual(extra['materials'][0]['catalogClaims']['translationStatus'], rows[0]['translationStatus'])
        self.assertFalse(extra['sourceApprovalCreated'])
        self.assertEqual(result['automaticPreparationScopes'], 0)
        self.assertEqual(json.loads((self.root / 'materials/catalog.json').read_bytes())['entries'], before)

    def test_new_collection_and_archived_rows_both_keep_exact_flags(self):
        rows = [{'language': 'ja', 'collection': 'future-app-reader', 'id': 'a', 'current': True,
                 'json': 'materials/not-installed.json'},
                {'language': 'ja', 'collection': 'historical-hadith', 'id': 'old',
                 'archived': True, 'status': 'historical'}]
        self.write('materials/catalog.json', {'entries': rows})
        result = inventory(self.root)
        self.assertEqual(result['catalogPartition']['unmappedCollectionMaterials'], 2)
        groups = {row['collection']: row for row in result['unmappedMaterialScopes']}
        self.assertFalse(groups['future-app-reader']['materials'][0]['sourceFiles'][0]['installed'])
        self.assertEqual(groups['historical-hadith']['materials'][0]['catalogClaims'],
                         {'status': 'historical', 'archived': True})
        self.assertFalse(result['sourceQualificationsChanged'])


if __name__ == '__main__':
    unittest.main()
