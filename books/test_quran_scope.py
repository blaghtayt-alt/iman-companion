import unittest
from copy import deepcopy
from quran_scope import canonical_surah,extended,review_catalog_id
from book_edition_scope import available

class QuranScopeTests(unittest.TestCase):
    def alias(self):return {'collection':'tadabbur','id':'fatiha-extended','language':'de','status':'current-app-edition','json':'materials/tadabbur/fatiha-extended/de/reading.json','markdown':'materials/tadabbur/fatiha-extended/de/reading.md'}
    def test_known_packet_retains_source_identity_without_mode_field(self):
        row=self.alias();before=deepcopy(row);self.assertEqual(canonical_surah(row),1);self.assertTrue(available(row));self.assertEqual(row,before)
    def test_alias_detection_never_overrides_a_hold_or_a_simplified_mode(self):
        row=self.alias();row['current']=False;self.assertFalse(available(row))
        row=self.alias();row['translationStatus']='held';self.assertFalse(available(row))
        row=self.alias();row['mode']='simplified';self.assertFalse(extended(row))
    def test_no_filename_or_last_numeric_run_guess(self):
        self.assertIsNone(canonical_surah({'collection':'tadabbur','id':'anything001','json':'001.json'}))
        row=self.alias();row['json']='arbitrary/001.json'
        with self.assertRaises(ValueError):canonical_surah(row)
    def test_standard_and_explicit_future_extended_identity(self):
        self.assertEqual(canonical_surah({'collection':'tadabbur','id':'18:extended','mode':'extended','surah':18}),18)
        self.assertEqual(canonical_surah({'collection':'tadabbur','id':'new-reviewed-reading','mode':'extended','canonicalSurah':35}),35)
        with self.assertRaises(ValueError):canonical_surah({'collection':'tadabbur','id':'18:extended','mode':'extended','surah':35})
    def test_review_bindings_keep_alias_or_explicit_catalog_identity(self):
        self.assertEqual(review_catalog_id({'collection':'tadabbur','materialId':1,'mode':'extended'}),'1:extended')
        self.assertEqual(review_catalog_id({'collection':'tadabbur','materialId':'fatiha-extended','mode':'extended'}),'fatiha-extended')
        self.assertEqual(review_catalog_id({'collection':'tadabbur','materialId':1,'mode':'extended','catalogId':'fatiha-extended'}),'fatiha-extended')

if __name__=='__main__':unittest.main()
