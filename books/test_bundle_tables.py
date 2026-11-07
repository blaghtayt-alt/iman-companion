from pathlib import Path
from copy import deepcopy
import json,re,unittest
from download_tables import render_ready,COPY
from download_bundle_copy import BUNDLE_COPY
from bibliography import native_text

class BundleTables(unittest.TestCase):
 def setUp(self):
  self.conf=json.loads((Path(__file__).parent/'config.json').read_bytes());self.ready={};self.bundles={}
  for lang in COPY:
   name=f'Iman_Companion_{lang}_tadabbur-extended.docx';base='https://github.com/example/test/releases/download/fixture/'
   self.ready[(lang,'tadabbur-extended')]={'file':name,'download':base+name,'pdfDownload':base+name[:-5]+'.pdf','units':[{'id':'fixture'}]}
   self.bundles[lang]={'parts':1,'docx':base+name,'pdf':base+name[:-5]+'.pdf','zip':base+f'Iman_Companion_{lang}_all-books.zip'}
 def test_twenty_native_tables_use_same_verified_bundle_and_chooser(self):
  table,pages=render_ready(self.conf,self.ready,'example/test',self.bundles)
  rows=[r for r in table.splitlines()if r.startswith('|')];self.assertEqual(len(rows),22);self.assertTrue(all(r.count('|')==7 for r in rows))
  for lang,page in pages.items():
   self.assertIn(self.bundles[lang]['zip'],page);self.assertIn('?lang='+lang,table)
   self.assertEqual(page.count('all-books.zip'),1)
   for text in BUNDLE_COPY[lang]:native_text(text,lang)
   for line in page.splitlines():native_text(re.sub(r'\]\([^)]*\)',']',line),lang)
 def test_missing_bundle_keeps_individual_book_available(self):
  table,pages=render_ready(self.conf,self.ready,'example/test',{})
  self.assertNotIn('all-books.zip',table+'\n'+''.join(pages.values()))
  for lang,page in pages.items():self.assertIn(self.ready[(lang,'tadabbur-extended')]['download'],page)
 def test_wrong_language_zip_and_partial_bundle_are_rejected(self):
  for changes in [{'zip':self.bundles['ru']['zip']},{'parts':2}]:
   bundles=deepcopy(self.bundles);bundles['fil'].update(changes)
   with self.assertRaises(ValueError):render_ready(self.conf,self.ready,'example/test',bundles)
 def test_removed_locale_never_leaves_an_active_combined_link(self):
  ready={k:v for k,v in self.ready.items()if k[0]!='fil'};bundles={k:v for k,v in self.bundles.items()if k!='fil'}
  table,pages=render_ready(self.conf,ready,'example/test',bundles);self.assertNotIn('/Iman_Companion_fil_',pages['fil']);self.assertNotIn('?lang=fil',table)
if __name__=='__main__':unittest.main()
