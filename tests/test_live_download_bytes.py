"""Synthetic transport bytes; never real Word/render/approval evidence."""
from pathlib import Path
from io import BytesIO
import hashlib,json,sys,unittest,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from check_live_book_bytes import inspect,inventory

class Response(BytesIO):
    status=200;headers={'ETag':'fixture'}
    def geturl(self):return 'https://release-assets.githubusercontent.com/fixture'

class BodyChecks(unittest.TestCase):
    def item(self,format,raw,**extra):return {'language':'en','collection':'articles','format':format,'url':'https://github.com/blaghtayt-alt/iman-companion/releases/download/fixture/Iman_Companion_en_articles.'+format,'sha256':hashlib.sha256(raw).hexdigest(),**extra}
    def archive(self,members):
        stream=BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,body in members.items():z.writestr(name,body)
        return stream.getvalue()
    def test_hash_failure_cannot_pass_even_with_http_200(self):
        raw=b'%PDF-wrong';result=inspect(self.item('pdf',b'expected'),opener=lambda *a,**k:Response(raw))
        self.assertEqual(result['integrity'],'failed');self.assertIn('bytes differ',result['error'])
    def test_combined_zip_verifies_every_member_and_missing_reading(self):
        members={'book.docx':b'docx fixture','book.pdf':b'pdf fixture'};raw=self.archive(members)
        item=self.item('zip',raw,members={k:hashlib.sha256(v).hexdigest() for k,v in members.items()})
        self.assertEqual(inspect(item,opener=lambda *a,**k:Response(raw))['integrity'],'passed')
        item['members']['omitted.docx']='0'*64
        self.assertIn('omits',inspect(item,opener=lambda *a,**k:Response(raw))['error'])
    def test_docx_reports_exact_old_new_text_without_claiming_approval(self):
        body='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Exact AFTER fixture</w:t></w:r></w:p></w:body></w:document>'
        raw=self.archive({'word/document.xml':body});item=self.item('docx',raw);item['collection']='tadabbur-extended'
        result=inspect(item,opener=lambda *a,**k:Response(raw),contracts={'en':{'before':'BEFORE fixture','after':'Exact AFTER fixture'}})
        self.assertEqual(result['integrity'],'passed');self.assertTrue(result['textComparison']['afterPresent']);self.assertFalse(result['textComparison']['beforePresent'])
        self.assertNotIn('sourceApproval',result)
    def test_pdf_body_is_opened_and_page_count_is_checked(self):
        from pypdf import PdfWriter
        out=BytesIO();pdf=PdfWriter();pdf.add_blank_page(width=100,height=100);pdf.write(out);raw=out.getvalue()
        result=inspect(self.item('pdf',raw),opener=lambda *a,**k:Response(raw))
        self.assertEqual(result['integrity'],'passed');self.assertEqual(result['pages'],1)
    def test_current_public_inventory_includes_all_pairs_and_bundle_assets(self):
        catalog=json.loads((ROOT/'docs/books/catalog.json').read_bytes());bundles=json.loads((ROOT/'books/published-bundles.json').read_bytes())
        rows=inventory(catalog,bundles)
        self.assertEqual(len(rows),sum(len(l['books'])*2 for l in catalog['languages'].values())+sum(len(b['assets']) for b in bundles['languages'].values()))
        self.assertEqual({r['format'] for r in rows},{'docx','pdf','zip'})

if __name__=='__main__':unittest.main()
