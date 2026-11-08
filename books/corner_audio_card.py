"""Render a real QR and native app type into a printable opening-page card.

The AI-generated design is a visual reference only. Every barcode pixel here is
generated locally and every caption is shaped with the actual pinned app font.
"""
from pathlib import Path
from io import BytesIO
import base64,hashlib,html,json,os,re,shutil,subprocess,tempfile
from PIL import Image
import qrcode

PIXELS_PER_MM=12
QR_BOX_PIXELS=8
QR_BORDER_MODULES=4
MIN_CARD_WIDTH_MM=70
MIN_CARD_HEIGHT_MM=45
SHORT_CAPTIONS={
'en':'Scan to\nlisten','ar':'امسح\nللاستماع','ur':'اسکین کریں\nاور سنیں',
'id':'Pindai\n& dengar','ms':'Imbas\n& dengar','bn':'স্ক্যান করে\nশুনুন',
'tr':'Tarayın\nve dinleyin','fr':'Scannez\net écoutez','pt-BR':'Escaneie\npara ouvir',
'hi':'स्कैन करें\nऔर सुनें','ru':'Сканируй\nи слушай','es':'Escanea\ny escucha',
'fa':'اسکن کنید\nو بشنوید','de':'Scannen\n& anhören','zh-CN':'扫码\n收听',
'uz':'Skanerlang\nva tinglang','th':'สแกน\nเพื่อฟัง','vi':'Quét mã\nđể nghe',
'ja':'読み取って\n聴く','fil':'I-scan\nat makinig'}

def chrome_binary():
    configured=os.environ.get('IMAN_BOOK_CHROME')
    candidates=[configured,shutil.which('google-chrome'),shutil.which('chromium'),shutil.which('chromium-browser'),r'C:\Program Files\Google\Chrome\Application\chrome.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():return str(candidate)
    raise RuntimeError('Audio card rendering needs headless Chrome; set IMAN_BOOK_CHROME to its installed executable')

def qr_artwork(url):
    """Return unscaled QR pixels and their physical print dimensions."""
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=QR_BOX_PIXELS,border=QR_BORDER_MODULES)
    qr.add_data(url);qr.make(fit=True)
    image=qr.make_image(fill_color='black',back_color='white').convert('RGB')
    return image,{'qrModules':len(qr.get_matrix()),'qrSideMM':image.width/PIXELS_PER_MM,'quietZoneModules':QR_BORDER_MODULES,'printedModuleMM':QR_BOX_PIXELS/PIXELS_PER_MM}

def render_card(url,language,font_path,cache_root):
    font_path=Path(font_path);cache_root=Path(cache_root).resolve();cache_root.mkdir(parents=True,exist_ok=True)
    caption=SHORT_CAPTIONS[language]
    key=hashlib.sha256(('corner-audio-v3-a4-large|'+url+'|'+language+'|'+caption).encode()+font_path.read_bytes()).hexdigest()
    target=cache_root/(key+'.png');metrics=cache_root/(key+'.json')
    if target.is_file() and metrics.is_file():return target,json.loads(metrics.read_text(encoding='utf-8'))
    image,qr_metrics=qr_artwork(url);qr_size=image.width
    width=max(MIN_CARD_WIDTH_MM*PIXELS_PER_MM,qr_size+315)
    height=max(MIN_CARD_HEIGHT_MM*PIXELS_PER_MM,qr_size+44)
    # The QR grows with the encoded identity; never shrink it to fit the card.
    # 8 pixels per module at 12 px/mm gives 0.67 mm printed modules and keeps
    # the four-module white quiet zone separate from the decorative frame.
    if width/PIXELS_PER_MM>95:raise ValueError('Material ID is too long for the printable audio code')
    qr_buffer=BytesIO();image.save(qr_buffer,format='PNG')
    font=base64.b64encode(font_path.read_bytes()).decode();qr_data=base64.b64encode(qr_buffer.getvalue()).decode()
    text_left=22+qr_size+14;text_width=width-text_left-22
    rtl=language in {'ar','ur','fa'};lineheight='1.75' if language=='ur' else '1.28'
    speaker='<svg viewBox="0 0 24 24" width="56" height="56" fill="none" stroke="#07513b" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8a6 6 0 0 1 0 8M18.5 5a10 10 0 0 1 0 14"/></svg>'
    page=f'''<!doctype html><html lang="{language}" data-ready="false"><head><meta charset="utf-8"><style>
@font-face{{font-family:CardNative;src:url(data:font/ttf;base64,{font}) format('truetype');font-weight:600}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;background:white;color-scheme:light}}
.card{{position:relative;width:{width}px;height:{height}px;border:3px solid #b79244;border-radius:23px;background:#fcfaf5}}
.card:after{{content:"";position:absolute;inset:5px;border:2px solid #07513b;border-radius:17px;pointer-events:none}}
.qr{{position:absolute;left:19px;top:{(height-qr_size)//2-3}px;width:{qr_size}px;height:{qr_size}px;image-rendering:pixelated}}
.copy{{position:absolute;left:{text_left-3}px;top:22px;width:{text_width}px;height:{height-44}px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:14px}}
.caption{{font-family:CardNative;font-size:46px;font-weight:600;color:#07513b;line-height:{lineheight};white-space:pre;text-align:center;direction:{'rtl' if rtl else 'ltr'};margin:0;max-width:100%}}
</style></head><body><div class="card"><img class="qr" src="data:image/png;base64,{qr_data}"><div class="copy">{speaker}<p class="caption">{html.escape(caption)}</p></div></div><script>
document.fonts.ready.then(()=>{{const e=document.querySelector('.caption'),b=e.getBoundingClientRect(),c=document.querySelector('.copy').getBoundingClientRect();document.documentElement.dataset.ready='true';document.documentElement.dataset.fontReady=String(document.fonts.check('600 46px CardNative'));document.documentElement.dataset.fits=String(e.scrollWidth<=c.width+1&&e.scrollHeight+70<=c.height+1);}});
</script></body></html>'''
    temp=Path(tempfile.mkdtemp(prefix='corner-card-',dir=cache_root)).resolve()
    if not temp.is_relative_to(cache_root):raise ValueError('Temporary renderer escaped cache root')
    try:
        source=temp/'card.html';capture=temp/'capture.png';source.write_text(page,encoding='utf-8')
        args=[chrome_binary(),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--hide-scrollbars','--force-device-scale-factor=1','--user-data-dir='+str(temp/'profile'),'--window-size='+str(width)+','+str(height+160),'--virtual-time-budget=1500','--screenshot='+str(capture),'--dump-dom',source.as_uri()]
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        run=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=35,creationflags=flags)
        dom=run.stdout.decode('utf-8','replace')
        if run.returncode or not capture.is_file() or 'data-ready="true"' not in dom or 'data-font-ready="true"' not in dom or 'data-fits="true"' not in dom:
            flags=re.search(r'<html[^>]*>',dom)
            raise RuntimeError('Native QR corner card did not render or caption does not fit: '+language+' '+(flags.group(0) if flags else 'no DOM')+' '+run.stderr.decode('utf-8','replace')[-300:])
        with Image.open(capture) as screenshot:
            if screenshot.width<width or screenshot.height<height:raise ValueError('Corner card screenshot is clipped')
            screenshot.crop((0,0,width,height)).convert('RGB').save(target,format='PNG')
        data={'widthMM':width/PIXELS_PER_MM,'heightMM':height/PIXELS_PER_MM,**qr_metrics,'captionFontPt':46*72/(PIXELS_PER_MM*25.4),'caption':caption,'fontSHA256':hashlib.sha256(font_path.read_bytes()).hexdigest()}
        metrics.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return target,data
    finally:
        # Only the owned temporary directory below the already checked cache root.
        if temp.is_relative_to(cache_root):shutil.rmtree(temp,ignore_errors=True)
