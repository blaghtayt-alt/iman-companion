"""Physical A4/QR regressions; printing errors must fail before publication."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,unittest
from unittest.mock import patch

from docx import Document
from docx.shared import Mm
from docx.oxml.ns import qn
from PIL import Image
import zxingcpp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from build_books import cover_page,expected_page_layout
from check_outputs import validate_page_layout
from check_audio_qr import validate_card_geometry
from corner_audio_card import SHORT_CAPTIONS,qr_artwork
from material_audio import PLAYER_BASE,add_audio_panel,player_url

POINTS_PER_MM=72/25.4

class A4AudioLayoutChecks(unittest.TestCase):
    def record(self,language='en',identity='test-material-1'):
        return {'materialId':identity,'collection':'articles','language':language,
                'title':{'en':'Test material','ar':'مادة للاختبار'}.get(language,'Test material'),
                'sourceSHA256':'a'*64,'readingSHA256':'b'*64,'audioSHA256':'c'*64,
                'audioBytes':100,'approved':True,'status':'published',
                'audioUrl':'https://github.com/blaghtayt-alt/iman-companion/releases/download/test-fixture/test-cccccccccccccccc.opus'}

    def test_actual_codes_decode_at_print_resolution_for_every_language_and_long_id(self):
        for language in SHORT_CAPTIONS:
            for identity in ('new-seerah001','long-material-'+'x'*146):
                with self.subTest(language=language,identity_length=len(identity)):
                    url=player_url(self.record(language,identity))
                    bitmap,metrics=qr_artwork(url)
                    self.assertGreaterEqual(metrics['qrSideMM'],38)
                    self.assertGreaterEqual(metrics['printedModuleMM'],.6)
                    self.assertGreaterEqual(metrics['quietZoneModules'],4)
                    # Decode the real barcode at its declared physical size,
                    # resampled to an ordinary 150-dpi document scan.
                    pixels=round(metrics['qrSideMM']*150/25.4)
                    scan=bitmap.resize((pixels,pixels),Image.Resampling.LANCZOS)
                    result=zxingcpp.read_barcode(scan)
                    self.assertIsNotNone(result)
                    self.assertEqual(result.text,url)
                    quiet=metrics['quietZoneModules']*bitmap.width//metrics['qrModules']
                    for box in ((0,0,bitmap.width,quiet),(0,bitmap.height-quiet,bitmap.width,bitmap.height),
                                (0,0,quiet,bitmap.height),(bitmap.width-quiet,0,bitmap.width,bitmap.height)):
                        self.assertEqual(bitmap.crop(box).getextrema(),((255,255),(255,255),(255,255)))

    def test_large_qr_uses_reserved_flow_space_for_rtl_and_ltr_long_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            for language in ('en','ar'):
                with self.subTest(language=language):
                    record=self.record(language);url=player_url(record)
                    image,metrics=qr_artwork(url)
                    card=Image.new('RGB',(840,540),'white');card.paste(image,(20,40))
                    path=Path(tmp)/'card.png';card.save(path)
                    metrics.update(widthMM=70,heightMM=45)
                    doc=Document();section=doc.sections[0]
                    section.page_width=Mm(210);section.page_height=Mm(297)
                    section.left_margin=section.right_margin=Mm(18)
                    title=('A deliberately long material title with multiple clauses and retained source words ' if language=='en'
                           else 'عنوان طويل للمادة مع شرح واضح ومحافظة على كلمات المصدر ')*4
                    heading=doc.add_paragraph(title,style='Heading 1')
                    unit={'id':record['materialId'],'language':language,'collection':'articles',
                          'sourceHashes':['a'*64],'inputBindings':[{'sha256':'b'*64}],'readerTextSHA256':'d'*64}
                    registry={'schema':'iman-material-audio-v1','playerBase':PLAYER_BASE,'entries':[record]}
                    with patch('material_audio.render_card',return_value=(path,metrics)):
                        panel=add_audio_panel(doc,unit,registry,'Test','Test',None,None,
                                              heading_paragraphs=[heading],fonts={'Test':{'Bold':path}},cache_root=tmp)
                    body=doc.add_paragraph('Body text follows the reserved QR and title row.')
                    self.assertEqual(panel['layout'],'modern-corner-a4-v3')
                    self.assertEqual(len(doc.tables),1)
                    table=doc.tables[0]
                    self.assertIsNotNone(table.rows[0]._tr.find('./'+qn('w:trPr')+'/'+qn('w:cantSplit')))
                    self.assertAlmostEqual(sum(column.width.mm for column in table.columns),174,delta=.1)
                    self.assertGreaterEqual(table.columns[2 if language=='ar' else 0].width.mm,65)
                    self.assertEqual(table.cell(0,2 if language=='ar' else 0).text,title)
                    self.assertEqual(len(table.cell(0,0 if language=='ar' else 2)._tc.xpath('.//wp:inline')),1)
                    self.assertFalse(table._tbl.xpath('.//wp:anchor'))
                    self.assertLess(list(doc.element.body).index(table._tbl),list(doc.element.body).index(body._p))
                    self.assertIn(url,[relationship.target_ref for relationship in doc.part.rels.values() if relationship.is_external])

    def geometry(self):
        page=SimpleNamespace(width=210*POINTS_PER_MM,height=297*POINTS_PER_MM,extract_words=lambda:[])
        left=18*POINTS_PER_MM;top=20*POINTS_PER_MM
        item={'x0':left,'top':top,'x1':left+70*POINTS_PER_MM,'bottom':top+45*POINTS_PER_MM}
        panel={'layout':'modern-corner-a4-v3','corner':'top-left','cardWidthMM':70,'cardHeightMM':45,
               'qrSideMM':38,'quietZoneModules':4,'printedQRModuleMM':2/3}
        return panel,item,page

    def test_export_rejects_smaller_distorted_clipped_or_overlapping_card(self):
        panel,item,page=self.geometry();validate_card_geometry(panel,item,page)
        small=deepcopy(item);small['x1']=small['x0']+55*POINTS_PER_MM
        with self.assertRaisesRegex(ValueError,'scaled or distorted'):validate_card_geometry(panel,small,page)
        low_module={**panel,'printedQRModuleMM':.3}
        with self.assertRaisesRegex(ValueError,'too small'):validate_card_geometry(low_module,item,page)
        quiet={**panel,'quietZoneModules':0}
        with self.assertRaisesRegex(ValueError,'quiet zone'):validate_card_geometry(quiet,item,page)
        clipped={**item,'x0':-3}
        with self.assertRaisesRegex(ValueError,'outside'):validate_card_geometry(panel,clipped,page)
        page.extract_words=lambda:[{'x0':item['x0']+1,'x1':item['x0']+15,'top':item['top']+1,'bottom':item['top']+12,'text':'collision'}]
        with self.assertRaisesRegex(ValueError,'overlaps'):validate_card_geometry(panel,item,page)

    def test_a4_cover_preserves_complete_artwork_and_page_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'cover.png';Image.new('RGB',(200,300),'#fcfaf5').save(source)
            doc=Document();cover_page(doc,source,Mm(210),Mm(297))
            for section in doc.sections:
                self.assertAlmostEqual(section.page_width.mm,210,delta=.1)
                self.assertAlmostEqual(section.page_height.mm,297,delta=.1)
            drawing=doc.element.body.xpath('.//wp:anchor')[0]
            extent=drawing.find(qn('wp:extent'))
            self.assertAlmostEqual(int(extent.get('cx'))/int(extent.get('cy')),2/3,places=5)
            width=210*POINTS_PER_MM;height=297*POINTS_PER_MM;artwidth=height*2/3
            item={'x0':(width-artwidth)/2,'x1':(width+artwidth)/2,'top':0,'bottom':height,'srcsize':(200,300)}
            cover=SimpleNamespace(width=width,height=height,images=[item])
            pdf=SimpleNamespace(pages=[cover]);book={'pageLayout':expected_page_layout()}
            validate_page_layout(doc,pdf,book)
            # Stretching or cropping a 2:3 source to the A4 aspect must fail.
            item['x0']=0;item['x1']=width
            with self.assertRaisesRegex(ValueError,'cropped, distorted'):validate_page_layout(doc,pdf,book)
            item['x0']=(width-artwidth)/2;item['x1']=(width+artwidth)/2
            doc.sections[-1].page_width=Mm(152.4)
            with self.assertRaisesRegex(ValueError,'Word book is not on A4'):validate_page_layout(doc,pdf,book)

if __name__=='__main__':unittest.main()
