import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from export_ar_articles_projection import export
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
class ArticleExport(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);d=self.root/'materials/articles/prepared-ar';d.mkdir(parents=True)
  title='Article';body='Checked reader text.';reading=title+'\n\n'+body;source='a'*64
  self.article={'id':'article-a','title':title,'sourceSHA256':source,'reading':reading,'paragraphs':[{'index':0,'kind':'body','text':body,'segments':[{'text':body,'role':'plain'}]}],'references':[{'id':'1','text':'[1] Source','segments':[{'text':'[1] Source'}]}]}
  self.reader=self.root/'reader.js';self.write_reader()
  self.record={'id':'article-a','number':1,'title':title,'sourceHashes':[source],'readingSHA256':sha(reading),'markdown':'materials/articles/prepared-ar/01.md','index':'materials/articles/prepared-ar/index.json','collection':'articles','language':'ar','translationStatus':'supplied-arabic-current'}
  self.index={'number':1,'id':'article-a','title':title,'preparedSourceSHA256':source,'readingSHA256':sha(reading),'path':'01.md'}
  self.write_json(self.root/'materials/catalog.json',{'entries':[self.record]});self.write_json(d/'index.json',{'articles':[self.index]});(d/'01.md').write_bytes('# Article\n\nChecked reader text.\n\n## المراجع\n\n[1] Source'.encode('utf8'))
 def tearDown(self):self.temp.cleanup()
 def write_reader(self):self.reader.write_text('window.IMAN_ARTICLE_REPLACEMENTS982_DATA='+json.dumps({'schema':'arabic-article-replacements982-v1','language':'ar','articles':[self.article]},ensure_ascii=False)+';',encoding='utf8')
 def write_json(self,p,data):p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
 def test_exact_reader_and_public_sources(self):
  result=export(self.root,self.reader);self.assertEqual(len(result['articles']),1);self.assertEqual(result['articles'][0]['paragraphs'][0]['segments'][0]['role'],'plain')
 def test_changed_markdown_fails(self):
  (self.root/'materials/articles/prepared-ar/01.md').write_text('# Article\n\nWrong.\n\n## المراجع\n\n[1] Source',encoding='utf8')
  with self.assertRaises(ValueError):export(self.root,self.reader)
 def test_wrong_semantic_role_fails(self):
  self.article['paragraphs'][0]['segments'][0]['role']='guessed';self.write_reader()
  with self.assertRaises(ValueError):export(self.root,self.reader)
 def test_missing_or_withdrawn_source_fails(self):
  self.record['status']='withdrawn';self.write_json(self.root/'materials/catalog.json',{'entries':[self.record]})
  with self.assertRaises(ValueError):export(self.root,self.reader)
 def test_changed_reference_fails(self):
  self.article['references'][0]['text']='[1] Different';self.write_reader()
  with self.assertRaises(ValueError):export(self.root,self.reader)
 def source_identifiers(self):
  doi='DOI: 10.1002/wps.20499'
  self.article['references']=[{'id':'1','text':'[1] مرجع المصدر','segments':[]},{'id':'','text':doi,'segments':[],'continuationOf':'1','preservedIdentifiers':[doi]}]
  (self.root/'materials/articles/prepared-ar/01.md').write_text('# Article\n\nChecked reader text.\n\n## المراجع\n\n[1] مرجع المصدر\n\n'+doi,encoding='utf8')
  self.write_reader()
 def test_explicit_identifier_and_continuation_bindings_survive_export(self):
  self.source_identifiers();ref=export(self.root,self.reader)['articles'][0]['references'][1]
  self.assertEqual(ref['continuationOf'],'1');self.assertEqual(ref['preservedIdentifiers'],['DOI: 10.1002/wps.20499'])
 def test_changed_identifier_binding_is_rejected(self):
  self.source_identifiers();self.article['references'][1]['preservedIdentifiers']=['DOI: 10.1002/wps.20498'];self.write_reader()
  with self.assertRaisesRegex(ValueError,'exact complete token'):export(self.root,self.reader)
 def test_orphan_reference_continuation_is_rejected(self):
  self.source_identifiers();self.article['references'][1]['continuationOf']='2';self.write_reader()
  with self.assertRaisesRegex(ValueError,'continuation'):export(self.root,self.reader)
if __name__=='__main__':unittest.main()
