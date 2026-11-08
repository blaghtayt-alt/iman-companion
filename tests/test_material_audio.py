import json,os,sys,unittest
from copy import deepcopy
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler
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
    def remote_release(self):
        return {'draft':False,'tag_name':'test-fixture','assets':[{'browser_download_url':self.record['audioUrl'],'state':'uploaded','size':100,'digest':'sha256:'+self.record['audioSHA256']}]}
    def test_remote_verification_authenticates_only_the_fixed_release_api(self):
        response=BytesIO(json.dumps(self.remote_release()).encode())
        with patch.dict(os.environ,{'GH_TOKEN':'fixture-token'},clear=True),patch('sync_material_audio.urllib.request.urlopen',return_value=response) as opened:
            verify_remote([self.record,self.record])
        opened.assert_called_once()
        request=opened.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.github.com/repos/blaghtayt-alt/iman-companion/releases/tags/test-fixture')
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-token')
        self.assertEqual(request.get_header('Accept'),'application/vnd.github+json')
        self.assertEqual(opened.call_args.kwargs,{'timeout':30})
    def test_api_authorization_is_not_forwarded_to_a_download_redirect(self):
        response=BytesIO(json.dumps(self.remote_release()).encode())
        with patch.dict(os.environ,{'GH_TOKEN':'fixture-token'},clear=True),patch('sync_material_audio.urllib.request.urlopen',return_value=response) as opened:
            verify_remote([self.record])
        request=opened.call_args.args[0]
        redirected=HTTPRedirectHandler().redirect_request(request,None,302,'Found',{},self.record['audioUrl'])
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-token')
        self.assertEqual(redirected.full_url,self.record['audioUrl'])
        self.assertIsNone(redirected.get_header('Authorization'))
    def test_remote_verification_without_gh_token_has_no_fallback_authorization(self):
        for environment in ({'GITHUB_TOKEN':'unused-token'},{'GH_TOKEN':'','GITHUB_TOKEN':'unused-token'}):
            with self.subTest(environment=tuple(environment)):
                response=BytesIO(json.dumps(self.remote_release()).encode())
                with patch.dict(os.environ,environment,clear=True),patch('sync_material_audio.urllib.request.urlopen',return_value=response) as opened:
                    verify_remote([self.record])
                self.assertIsNone(opened.call_args.args[0].get_header('Authorization'))
    def test_authenticated_remote_verification_still_rejects_changed_digest(self):
        release=self.remote_release();release['assets'][0]['digest']='sha256:'+'d'*64
        with patch.dict(os.environ,{'GH_TOKEN':'fixture-token'},clear=True),patch('sync_material_audio.urllib.request.urlopen',return_value=BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(ValueError,'Audio release asset identity cannot be verified'):
                verify_remote([self.record])
    def test_authenticated_failure_is_not_retried_anonymously(self):
        failure=HTTPError('https://api.github.com/repos/blaghtayt-alt/iman-companion/releases/tags/test-fixture',403,'rate limit exceeded',{},None)
        with patch.dict(os.environ,{'GH_TOKEN':'fixture-token'},clear=True),patch('sync_material_audio.urllib.request.urlopen',side_effect=failure) as opened:
            with self.assertRaises(HTTPError) as caught:verify_remote([self.record])
        opened.assert_called_once()
        self.assertNotIn('fixture-token',str(caught.exception))
    def test_all_labels_are_native(self):
        for lang,labels in CAPTIONS.items():
            for label in labels:native_text(label,lang)
if __name__=='__main__':unittest.main()
