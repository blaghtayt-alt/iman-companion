"""Structured-reader formatting fixtures; never real source/review evidence."""
from pathlib import Path
from copy import deepcopy
import json,tempfile,unittest
from adapt_reviewed_quran import normalize,sha

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.quran=self.write('quran.json',{'18:1':'ا ١','18:2':'ب ٢','18:3':'ت ٣'})
        self.names=self.write('names.json',{'fil':['Pangalan']*114})
        self.config={'quranText':self.quran,'surahNames':self.names}
        self.row={'collection':'tadabbur','language':'fil','id':'18:extended','surah':18,'mode':'extended','json':'source.json','markdown':'source.md','sourceHashes':['a'*64]}
        self.payload={'language':'fil','surah':18,'entries':{'intro':{'heading':'Panimula','blocks':[{'kind':'paragraph','text':'Buong panimula.'}]},
          '18:1':{'heading':'Talata 1','blocks':[{'kind':'translation','text':'Unang salin.'},{'kind':'paragraph','text':'Buong paliwanag at pasubali.','spans':[{'text':'Buong paliwanag at pasubali.','role':'meaning'}],'requiredPublishedNoteIds':['n1']}]},
          '18:3':{'heading':'Talata 3','blocks':[{'kind':'translation','text':'Ikatlong salin.'},{'kind':'qualification','text':'Nananatili ang buong kwalipikasyon.'}]}},
          'readerNotes':[{'id':'n1','text':'Buong tala ng tagapaglathala.'}],'glossary':[{'term':'Salita','meaning':'Buong kahulugan.'}]}
    def tearDown(self):self.temp.cleanup()
    def write(self,path,value):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);raw=(json.dumps(value,ensure_ascii=False)+'\n').encode();p.write_bytes(raw);return {'path':path,'sha256':sha(raw)}
    def inputs(self):
        source=self.write('source.json',self.payload);markdown=self.root/'source.md';markdown.write_bytes(b'Fixture source transport only.');condition=self.write('conditions.json',{'fixture':'Keep qualifications and actual reviewer identity; not a real approval.'})
        self.record={'collection':'tadabbur','language':'fil','materialId':18,'mode':'extended','sourceFiles':[source,{'path':'source.md','sha256':sha(markdown.read_bytes())}],
          'sourceConditions':[condition],'existingWholeReview':{'handoffSHA256':'b'*64,'reviewer':{'kind':'fixture','noRealReview':True}},'historicalPublication':{'commit':'c'*40},
          'quranCredit':{'language':'fil','text':'Tunay na kredito mula sa pinagtibay na sanggunian.'}}
        evidence=self.write('inventory.json',{'fixture':'Test only','records':[self.record]});return evidence
    def build(self):return normalize(self.root,self.row,self.record,self.evidence,self.config)
    def test_selected_coverage_intro_prose_qualifications_notes_glossary_preserved(self):
        self.evidence=self.inputs();unit=self.build()
        self.assertEqual([s.get('ayahKey') for s in unit['sections']],[None,'18:1','18:3'])
        self.assertEqual(unit['reviewedCoverage']['ayahKeys'],['18:1','18:3']);self.assertIn('Mga talatang kasama',unit['title']);self.assertEqual(unit['coverageLabel'],'talata 1, 3')
        body=''.join(b['text'] for s in unit['sections'] for b in s['blocks'])
        for text in ['Buong panimula.','Unang salin.','Buong paliwanag at pasubali.','Nananatili ang buong kwalipikasyon.']:self.assertIn(text,body)
        notes=[n for s in unit['sections'] for b in s['blocks'] for span in b.get('spans',[]) for n in span.get('noteTexts',[])]
        self.assertEqual(notes,['Buong tala ng tagapaglathala.','Salita: Buong kahulugan.'])
        self.assertFalse(unit['provenance']['sourceApprovalCreated']);self.assertTrue(unit['provenance']['allProseAndQuotationCharactersPreserved'])
        self.assertEqual(unit['provenance']['sourceOwnerWholeReview'],self.record['existingWholeReview'])
    def test_held_or_unknown_evidence_cannot_be_created_by_formatter(self):
        self.evidence=self.inputs();self.record['sourceFiles'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Changed edition'):self.build()
    def test_wrong_source_bounds_or_unknown_sections_are_not_silently_omitted(self):
        for mode in ['bounds','unknown']:
            self.set_payload=deepcopy(self.payload)
            key='18:4' if mode=='bounds' else 'miscellaneous-section'
            self.payload['entries'][key]=self.payload['entries'].pop('18:3');self.evidence=self.inputs()
            with self.assertRaises(ValueError):self.build()
            self.payload=self.set_payload
    def test_missing_source_meaning_note_is_rejected(self):
        self.payload['readerNotes']=[];self.evidence=self.inputs()
        with self.assertRaisesRegex(ValueError,'meaning/qualification note is missing'):self.build()
    def test_author_only_credit_is_not_mislabeled_as_quran_translator(self):
        self.payload['shortCredit']='May-akda ng orihinal na Arabe.';self.evidence=self.inputs();self.record.pop('quranCredit')
        with self.assertRaisesRegex(ValueError,'translator/edition credit is missing'):self.build()
    def test_wrong_declared_source_owner_coverage_is_rejected(self):
        self.evidence=self.inputs();self.record['bookCoverage']={'ayahKeys':['18:1'],'introductionSectionIds':['intro']}
        with self.assertRaisesRegex(ValueError,'coverage differs'):self.build()
    def test_unstructured_website_reference_is_pending_never_used_as_hadith_number(self):
        self.payload['entries']['18:3']['citations']=[{'reference':'source-only','url':'https://example.invalid/5449'}];self.evidence=self.inputs();unit=self.build()
        self.assertEqual(unit['referenceReadiness']['unresolvedSourceReferenceCount'],1)
        self.assertFalse(any(s.get('citations') for section in unit['sections'] for b in section['blocks'] for s in b.get('spans',[])))
    def test_typed_original_collection_number_and_qualification_are_retained(self):
        citation={'type':'hadith','book':'muslim','number':'809','qualification':{'language':'fil','text':'Pinananatiling kwalipikasyon.'}}
        self.payload['entries']['18:3']['blocks'][-1]['citations']=[citation];self.evidence=self.inputs();unit=self.build()
        self.assertEqual(unit['sections'][-1]['blocks'][-1]['spans'][-1]['citations'],[citation])
    def test_main_translation_note_is_attached_to_its_actual_block(self):
        self.payload['entries']['18:1']['blocks'][0]['requiredPublishedNoteIds']=['n1'];self.evidence=self.inputs();unit=self.build()
        self.assertEqual(unit['sections'][1]['blocks'][1]['spans'][-1]['noteTexts'],['Buong tala ng tagapaglathala.'])
    def test_embedded_introduction_precedes_main_ayah_without_omission(self):
        self.payload['entries'].pop('intro');self.payload['entries']['18:1']['blocks'].insert(0,{'kind':'paragraph','text':'Buong nakapaloob na panimula.'});self.evidence=self.inputs();unit=self.build()
        self.assertNotIn('ayahKey',unit['sections'][0]);self.assertEqual(unit['sections'][0]['blocks'][0]['text'],'Buong nakapaloob na panimula.')
        self.assertEqual(unit['sections'][1]['ayahKey'],'18:1');self.assertEqual(unit['reviewedCoverage']['introduction']['state'],'included')
    def test_explicit_unbound_semantic_roles_are_reported_truthfully(self):
        self.payload['entries']['18:3']['blocks'][-1]['role']='hadith';self.evidence=self.inputs();unit=self.build()
        self.assertEqual(unit['referenceReadiness']['unboundHadithSegments'],1)
    def test_mandatory_whole_commentary_note_anchors_this_section_not_last_ayah(self):
        entry=self.payload['entries']['18:1'];entry['blocks'].append({'kind':'paragraph','text':'Ikalawang buong talata.'})
        text='Mahalagang paglilinaw ng kahulugan.'
        entry['mandatoryReadingNotes']=[{'id':'source-note-1','key':'18:1','text':text,'textSHA256':sha(text.encode()),'anchorCommentarySHA256':sha(''.join(b['text'] for b in entry['blocks'][1:]).encode())}]
        self.evidence=self.inputs();unit=self.build()
        self.assertEqual(unit['sections'][1]['blocks'][-1]['spans'][-1]['noteTexts'],[text])
        self.assertFalse(any(text in span.get('noteTexts',[]) for b in unit['sections'][-1]['blocks'] for span in b.get('spans',[])))
        entry['mandatoryReadingNotes'][0]['anchorCommentarySHA256']='0'*64;self.evidence=self.inputs()
        with self.assertRaisesRegex(ValueError,'whole-commentary anchor differs'):self.build()
    def test_mandatory_detached_qualification_must_remain_visible_in_its_source_block(self):
        block=self.payload['entries']['18:3']['blocks'][-1];block['authorQualification']={'id':'q1','text':block['text'],'mandatoryInEveryDetachedReadingAndExport':True}
        self.evidence=self.inputs();unit=self.build();self.assertEqual(len(unit['provenance']['mandatoryDetachedQualifications']),1)
        block['authorQualification']['text']='Nawawalang kwalipikasyon.';self.evidence=self.inputs()
        with self.assertRaisesRegex(ValueError,'qualification missing'):self.build()
    def test_source_scope_instruction_is_separate_metadata_at_its_exact_next_range(self):
        text='Saklaw lamang ng pinagmulang materyal.'
        self.payload['entries']['18:1']['blocks'].append({'kind':'paragraph','text':text});self.evidence=self.inputs()
        self.record['bookPresentation']=[{'kind':'source-scope-note','section':'18:1','block':2,'textSHA256':sha(text.encode()),'beforeSection':'18:3','label':'Saklaw ng materyal'}]
        unit=self.build();self.assertEqual(unit['sourceScopeNotes'][0]['beforeSection'],'18:3');self.assertEqual(unit['sourceScopeNotes'][0]['text'],text)
        self.assertNotIn(text,[b['text'] for b in unit['sections'][1]['blocks']])
    def test_bounded_quote_identity_keeps_candidate_keys_in_provenance(self):
        block=self.payload['entries']['18:1']['blocks'][1];block['spans']=[{'text':block['text'],'role':'quran','verseKeys':['18:1','18:3']}]
        self.evidence=self.inputs();self.record['bookSpanDispositions']=[{'section':'18:1','block':1,'span':0,'textSHA256':sha(block['text'].encode()),'originalVerseKeys':['18:1','18:3'],'verseKeys':['18:1']}]
        unit=self.build();self.assertEqual(unit['sections'][1]['blocks'][-1]['spans'][0]['verseKeys'],['18:1'])
        event=next(x for x in unit['provenance']['referenceFurnitureTransformations'] if x.get('source')=='source-owner-bounded-quote-identity');self.assertEqual(event['originalVerseKeys'],['18:1','18:3'])

if __name__=='__main__':unittest.main()
