import sys,unittest
from copy import deepcopy
from pathlib import Path
from io import BytesIO
from PIL import Image
import zxingcpp
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from material_audio import PLAYER_BASE,CAPTIONS,audio_for_unit,player_url,qr_png
from bibliography import native_text
from sync_material_audio import verify_remote

class MaterialAudioChecks(unittest.TestCase):
    def setUp(self):
        self.record={'materialId':'test-material-1','collection':'articles','language':'en','title':'Test material','sourceSHA256':'a'*64,'readingSHA256':'b'*64,'audioSHA256':'c'*64,'audioBytes':100,'approved':True,'status':'published','audioUrl':'https://github.com/blaghtayt-alt/iman-companion/releases/download/test-fixture/test-cccccccccccccccc.opus'}
        self.registry={'schema':'iman-material-audio-v1','playerBase':PLAYER_BASE,'entries':[self.record]}
        self.unit={'id':'test-material-1','collection':'articles','language':'en','sourceHashes':['a'*64],'inputBindings':[{'sha256':'b'*64}],'readerTextSHA256':'d'*64}
    def test_exact_binding_and_qr(self):
        self.assertEqual(audio_for_unit(self.unit,self.registry),self.record)
        result=zxingcpp.read_barcode(Image.open(BytesIO(qr_png(player_url(self.record)))))
        self.assertEqual(result.text,player_url(self.record))
    def test_inexact_or_unapproved_never_matches(self):
        for key,value in [('id','different'),('language','ar'),('collection','seerah'),('sourceHashes',['d'*64]),('inputBindings',[{'sha256':'d'*64}])]:
            unit=deepcopy(self.unit);unit[key]=value;self.assertIsNone(audio_for_unit(unit,self.registry))
        for status in ['held','withdrawn','draft','awaiting-individual-audio-publication']:
            registry=deepcopy(self.registry);registry['entries'][0]['status']=status;self.assertIsNone(audio_for_unit(self.unit,registry))
        registry=deepcopy(self.registry);registry['entries'][0]['approved']=False;self.assertIsNone(audio_for_unit(self.unit,registry))
    def test_duplicate_or_bad_audio_url_fails_closed(self):
        registry=deepcopy(self.registry);registry['entries'].append(deepcopy(self.record))
        with self.assertRaisesRegex(ValueError,'Ambiguous'):audio_for_unit(self.unit,registry)
        registry=deepcopy(self.registry);registry['entries'][0]['audioUrl']='https://example.org/test.opus'
        with self.assertRaises(ValueError):audio_for_unit(self.unit,registry)
    def test_remote_publication_requires_matching_url_size_and_digest(self):
        asset={'browser_download_url':self.record['audioUrl'],'state':'uploaded','size':100,'digest':'sha256:'+self.record['audioSHA256']}
        release={'draft':False,'tag_name':'test-fixture','assets':[asset]}
        verify_remote([self.record],fetch=lambda _:release)
        for field,bad in [('state','new'),('size',99),('digest','sha256:'+'d'*64),('browser_download_url','https://example.org/wrong.opus')]:
            changed=deepcopy(release);changed['assets'][0][field]=bad
            with self.assertRaises(ValueError):verify_remote([self.record],fetch=lambda _,v=changed:v)
        changed=deepcopy(release);changed['draft']=True
        with self.assertRaises(ValueError):verify_remote([self.record],fetch=lambda _:changed)
    def test_all_labels_are_native(self):
        for lang,labels in CAPTIONS.items():
            for label in labels:native_text(label,lang)
if __name__=='__main__':unittest.main()
