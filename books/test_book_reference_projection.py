from copy import deepcopy
import unittest
from book_reference_projection import binding,place,index_projection,annotate
from book_edition_scope import sha

class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.names={'ar':['الفاتحة','البقرة']+['اسم']*112,'en':['Al-Fatiha','Al-Baqara']+['Name']*112};self.quran={'1:1':'ا','1:2':'ب','2:1':'ت'}
    def row(self,kind,detail):return {'classification':kind,'classification_detail':detail,'reference_object':{'reference':'fixture-reference'},'qualification':None,'section':'intro','issues':[],'literal_quote_anchors':[]}
    def test_original_additional_collection_not_misnamed_as_sahih(self):
        row=self.row('hadith_collection_and_explicit_number',{'collection':'البخاري، الأدب المفرد','explicit_number':'859'})
        value=binding(row,'ar',self.names,self.quran)['citations'][0]
        self.assertNotEqual(value['book'],'bukhari');self.assertEqual(value['localizedTitles']['ar'],'البخاري، الأدب المفرد');self.assertEqual(value['number'],'859')
    def test_ambiguous_original_book_locator_never_becomes_hadith_number(self):
        row=self.row('named_source_locator_ambiguous',{'source':'الحاكم، المستدرك','literal_locator':'5','locator_type':'not established by citation'});row['reference_object']={'reference':'الحاكم، المستدرك: 5'}
        value=binding(row,'ar',self.names,self.quran);self.assertNotIn('citations',value);self.assertIn('٥',value['noteTexts'][0]);self.assertEqual(value['qualifiedBookOnlyLocator']['literalLocator'],'5')
    def test_source_grade_preserved_without_printing_analyst_english(self):
        row=self.row('hadith_collection_and_explicit_number',{'collection':'الطبراني، المعجم الكبير','explicit_number':'3718','qualification':'حسنه الألباني (attributed in source; not independently assessed)'});row['reference_object']={'reference':'الطبراني، المعجم الكبير: 3718؛ حسنه الألباني'}
        value=binding(row,'ar',self.names,self.quran)['citations'][0];self.assertEqual(value['qualification']['text'],'حسنه الألباني')
    def test_exact_source_quote_annotation_preserves_every_character(self):
        text='قبل الاقتباس ثم بعده.';quote='الاقتباس';start=text.index(quote);source={'text':text};row=self.row('quran_reference',{'verse_keys':['1:2']});row['reference_object']={'reference':'1:2','quote':quote};row['literal_quote_anchors']=[{'unit_block_index_zero_based':0,'cp':[start,start+len(quote)],'unit_block_sha256':sha(text.encode())}]
        converted=[{'kind':'paragraph','text':text,'spans':[{'text':text,'role':'body'}],'sourceBlockIndex':0}]
        result=place(row,row['reference_object'],{'blocks':[source]},converted,'ar',self.names,self.quran,set(),set())
        self.assertEqual(result['placement'],'exact literal source quote');self.assertEqual(''.join(s['text'] for s in converted[0]['spans']),text)
        self.assertEqual([s['verseKeys'] for s in converted[0]['spans'] if not s.get('text')],[['1:2']])
    def test_later_quote_preserves_earlier_zero_width_citation(self):
        text='alpha bravo';block={'text':text,'spans':[{'text':text,'role':'body'}]};cite={'book':'muslim','number':'395'}
        annotate(block,0,5,'alpha',{'citations':[cite]});annotate(block,6,11,'bravo',{'verseKeys':['1:1']})
        self.assertEqual(''.join(s['text'] for s in block['spans']),text)
        self.assertEqual([s['citations'] for s in block['spans'] if s.get('citations')],[[cite]])
        self.assertIn(['1:1'],[s['verseKeys'] for s in block['spans'] if s.get('verseKeys')])
    def test_later_quote_preserves_earlier_zero_width_note(self):
        text='alpha bravo';block={'text':text,'spans':[{'text':text,'role':'body'}]}
        annotate(block,0,5,'alpha',{'noteTexts':['source note']});annotate(block,6,11,'bravo',{'citations':[{'book':'muslim','number':'395'}]})
        self.assertEqual(''.join(s['text'] for s in block['spans']),text)
        self.assertEqual([s['noteTexts'] for s in block['spans'] if s.get('noteTexts')],[['source note']])
        self.assertEqual(len([s for s in block['spans'] if s.get('citations')]),1)
    def test_section_attribution_does_not_fabricate_a_quote_anchor(self):
        row=self.row('named_scholar_book_or_commentary',{'literal_source':'زاد المعاد، فصل الرقية'});converted=[{'kind':'paragraph','text':'نص كامل.'}]
        result=place(row,row['reference_object'],{'blocks':[]},converted,'ar',self.names,self.quran,set(),set())
        self.assertNotIn('sourceCP',result);self.assertEqual(converted[0]['spans'][-1]['noteTexts'],['زاد المعاد، فصل الرقية'])
    def test_changed_current_reference_or_quote_is_rejected(self):
        row=self.row('named_scholar_book_or_commentary',{'literal_source':'زاد المعاد'})
        with self.assertRaisesRegex(ValueError,'differs from its frozen'):place(row,{'reference':'changed'},{},[],'ar',self.names,self.quran,set(),set())
    def test_projection_has_exact_source_revision_and_no_duplicate_field_index(self):
        row=self.row('named_scholar_book_or_commentary',{'literal_source':'زاد المعاد'});row.update({'sourcePath':'source.json','source_reference_pointer':'entries["intro"].citations','matching_source_indices_zero_based':[0]})
        data={'schema':'iman-source-reference-projection-v1','sources':[{'path':'source.json','sha256':'a'*64}],'references':[row]}
        self.assertIn(('intro','citations',0),index_projection(data,'source.json','a'*64))
        with self.assertRaisesRegex(ValueError,'another reader revision'):index_projection(data,'source.json','b'*64)
        data['references'].append(deepcopy(row))
        with self.assertRaisesRegex(ValueError,'Duplicate'):index_projection(data,'source.json','a'*64)

if __name__=='__main__':unittest.main()
