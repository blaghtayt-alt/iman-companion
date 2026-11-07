"""Synthetic format-contract tests, not actual Word/source review receipts."""
from pathlib import Path
import copy,hashlib,json,tempfile,unittest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,TextStringObject,ArrayObject,NumberObject,DecodedStreamObject
from word_layout_check import verify,verify_pair
from check_contents_targets import check as check_pdf

class WordLayoutChecks(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.file=self.root/'SYNTHETIC-CONTRACT-ONLY.docx';self.receipt=self.file.with_name(self.file.name+'.word-layout.json');doc=Document();doc.styles.add_style('TOC1',WD_STYLE_TYPE.PARAGRAPH)
  for n in range(2):
   p=doc.add_paragraph(style='TOC1');h=OxmlElement('w:hyperlink');h.set(qn('w:anchor'),'fixture'+str(n));p._p.append(h)
   for content in ['Synthetic entry',None,str(n+3)]:
    r=OxmlElement('w:r');node=OxmlElement('w:tab'if content is None else'w:t');node.text=content;r.append(node);h.append(r)
   target=doc.add_paragraph();start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(n));start.set(qn('w:name'),'fixture'+str(n));target._p.append(start);target.add_run('Synthetic target');end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(n));target._p.append(end)
  doc.save(self.file);self.data={'schema':'iman-word-layout-readback-v1','testFixtureOnly':True,'docxSHA256':hashlib.sha256(self.file.read_bytes()).hexdigest(),'engine':{'application':'Microsoft Word','version':'synthetic-contract-fixture','build':'not-a-real-readback'},'readOnly':True,'savedByWord':False,'pages':4,'contents':[{'anchor':'fixture'+str(n),'cachedPage':n+3,'actualPage':n+3,'physicalPage':n+3}for n in range(2)]};self.write()
 def tearDown(self):self.temp.cleanup()
 def write(self):self.receipt.write_text(json.dumps(self.data),encoding='utf8')
 def pdf(self,bad=False,wrong_visible=False):
  file=self.root/'SYNTHETIC.pdf';writer=PdfWriter()
  for _ in range(3):writer.add_blank_page(width=432,height=648)
  painted=[]
  for n,target in enumerate([2,3]):
   annotation=DictionaryObject({NameObject('/Subtype'):NameObject('/Link'),NameObject('/Rect'):ArrayObject([NumberObject(10),NumberObject(497-n*20),NumberObject(315),NumberObject(512-n*20)]),NameObject('/Dest'):ArrayObject([writer.pages[target-1].indirect_reference,NameObject('/Fit')]),NameObject('/Contents'):TextStringObject('Synthetic\t'+str(99 if bad and n==0 else target))});writer.pages[0].setdefault(NameObject('/Annots'),ArrayObject()).append(writer._add_object(annotation));painted.append(f'BT /F1 10 Tf 300 {500-n*20} Td ({99 if wrong_visible and n==0 else target}) Tj ET')
  font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')});writer.pages[0][NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})});stream=DecodedStreamObject();stream.set_data('\n'.join(painted).encode());writer.pages[0][NameObject('/Contents')]=writer._add_object(stream)
  with file.open('wb')as stream:writer.write(stream)
  return file
 def test_independent_format_pagination_is_checked_separately(self):
  result=verify_pair(self.file,self.pdf(),'en');self.assertEqual(result['word']['pages'],4);self.assertEqual(result['pdf']['matchedEntries'],2);self.assertEqual(result['pdf']['visibleLabelsMatched'],2)
 def test_invalid_pdf_label_is_rejected_even_with_valid_word_receipt(self):
  verify(self.file,self.receipt)
  with self.assertRaises(ValueError):check_pdf(self.file,self.pdf(True))
 def test_changed_final_word_file_rejects_stale_readback(self):
  with self.file.open('ab')as stream:stream.write(b'changed')
  with self.assertRaises(ValueError):verify(self.file,self.receipt)
 def test_every_anchor_and_its_actual_word_page_are_required(self):
  original=copy.deepcopy(self.data)
  for update in [{'anchor':'missing'},{'cachedPage':2},{'actualPage':4},{'physicalPage':5}]:
   self.data=copy.deepcopy(original);self.data['contents'][0].update(update);self.write()
   with self.assertRaises(ValueError):verify(self.file,self.receipt)
 def test_incomplete_target_list_rejects_receipt(self):
  self.data['contents'].pop();self.write()
  with self.assertRaises(ValueError):verify(self.file,self.receipt)
 def test_actual_read_only_word_engine_is_required(self):
  for field,value in [('readOnly',False),('savedByWord',True),('engine',{'application':'Other renderer','version':'1','build':'1'})]:
   self.data[field]=value;self.write()
   with self.assertRaises(ValueError):verify(self.file,self.receipt)
 def test_every_pdf_contents_entry_requires_a_painted_number_check(self):
  with patch('word_layout_check.visible_pdf_contents',return_value={'visibleLabelsMatched':1}):
   with self.assertRaisesRegex(ValueError,'Not every PDF'):verify_pair(self.file,self.pdf(),'en')
 def test_no_receipt_keeps_existing_strict_cache_comparison(self):
  self.receipt.unlink()
  with self.assertRaises(ValueError):verify_pair(self.file,self.pdf(),'en')
 def test_valid_link_metadata_cannot_hide_wrong_painted_pdf_number(self):
  pdf=self.pdf(wrong_visible=True);check_pdf(self.file,pdf)
  with self.assertRaises(ValueError):verify_pair(self.file,pdf,'en')
if __name__=='__main__':unittest.main()
