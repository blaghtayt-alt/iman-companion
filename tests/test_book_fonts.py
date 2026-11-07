import hashlib,sys,tempfile,unittest,zipfile
from pathlib import Path
from docx import Document
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from font_integrity import restore,verify
class FontChecks(unittest.TestCase):
 def test_restoration_keeps_reader_and_links_and_checks_exact_font_bytes(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);f=root/'test.docx';doc=Document();doc.add_paragraph('Keep this reader text.');doc.save(f)
   conf={'languages':{'en':{'font':'Body'}},'fonts':{}}
   for name in ['Body','Arabic','Latin']:
    raw=(name.encode()*64);path=root/(name+'.ttf');path.write_bytes(raw);conf['fonts'][name]={'family':'Test '+name,'files':{'Regular':path.name},'sha256':{'Regular':hashlib.sha256(raw).hexdigest()}}
   with zipfile.ZipFile(f) as z:before={n:z.read(n) for n in ['word/document.xml','word/_rels/document.xml.rels']}
   restore(f,conf,'en',root);self.assertTrue(verify(f,conf,'en'))
   with zipfile.ZipFile(f) as z:
    for n,value in before.items():self.assertEqual(z.read(n),value)
    parts={n:z.read(n) for n in z.namelist()}
   target=next(n for n in parts if n.startswith('word/fonts/iman-'));parts[target]=parts[target][:-1]+bytes([parts[target][-1]^1])
   with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in parts.items():z.writestr(name,data)
   with self.assertRaisesRegex(ValueError,'does not match'):verify(f,conf,'en')
if __name__=='__main__':unittest.main()
