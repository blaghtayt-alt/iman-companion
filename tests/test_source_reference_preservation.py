"""Literal attribution fidelity is distinct from machine citation classification."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from check_outputs import require_complete_references

class ReferencePreservationTests(unittest.TestCase):
    def book(self):
        return {'collection':'hadith','units':[{'id':'fixture-1'}],
          'sourceReferencePreservation':{
            'schema':'iman-source-reference-preservation-v1','auditMode':'literal-source-and-qualification-fidelity',
            'units':1,'auditedUnits':1,'approvedPublisherUnits':0,
            'sourceReferences':3,'preservedReferences':3,'lostReferences':0,
            'sourceQualifications':1,'preservedQualifications':1,'lostQualifications':0,
            'sourceParagraphs':2,'preservedParagraphs':2,'lostParagraphs':0},
          'sourceReferenceDiagnostics':{'auditMode':'parser-placement-only-not-source-validity',
            'quranGroupsWithoutImmediateTypedReference':1,'quotationGroupsWithoutImmediateReference':2,
            'literalReferencesWithoutTypedClassification':3}}

    def test_preserved_literal_notes_and_repeated_quotes_are_not_missing_sources(self):
        require_complete_references(self.book())

    def test_dropped_or_changed_source_references_qualifications_and_paragraphs_are_rejected(self):
        for field,value in [('preservedReferences',2),('preservedQualifications',0),('preservedParagraphs',1),
                            ('lostReferences',1),('lostQualifications',1),('lostParagraphs',1),('sourceReferences',True)]:
            with self.subTest(field=field):
                book=self.book();book['sourceReferencePreservation'][field]=value
                with self.assertRaisesRegex(ValueError,'not completely preserved'):require_complete_references(book)

    def test_unaccounted_reader_unit_is_rejected(self):
        book=self.book();book['units'].append({'id':'fixture-2'})
        with self.assertRaisesRegex(ValueError,'omits a reader unit'):require_complete_references(book)

    def test_literal_fidelity_does_not_remove_existing_typed_reference_holds(self):
        book=self.book();book['collection']='seerah'
        book['referenceReadiness']={'units':1,'auditedUnits':1,'unboundQuranSegments':1,'unboundHadithSegments':0}
        with self.assertRaisesRegex(ValueError,'source citations are incomplete'):require_complete_references(book)
        book=deepcopy(book);book['referenceReadiness']['unboundQuranSegments']=0
        book['referenceReadiness']['unresolvedSourceReferenceCount']=1
        with self.assertRaisesRegex(ValueError,'not completely mapped'):require_complete_references(book)

if __name__=='__main__':unittest.main()
