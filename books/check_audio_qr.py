"""Read actual rendered QR codes; never infer scanability from an image hash."""
from io import BytesIO
import zipfile
from PIL import Image
import zxingcpp

def complete_card_border(bitmap):
    """Check the visible rendered frame, which can clip while a QR still scans."""
    pixels=bitmap.convert('RGB');w,h=pixels.size;strip=max(3,round(min(w,h)*.028))
    def ink(rgb):
        r,g,b=rgb
        return (r<95 and 40<g<155 and b<125 and g>r*1.3) or (95<r<230 and 65<g<195 and b<160 and r>g*1.08 and g>b*1.08)
    for side in ['left','right','top','bottom']:
        rows=range(round((h if side in {'left','right'} else w)*.2),round((h if side in {'left','right'} else w)*.8))
        hits=0
        for n in rows:
            if side=='left':points=((x,n) for x in range(strip))
            elif side=='right':points=((x,n) for x in range(w-strip,w))
            elif side=='top':points=((n,y) for y in range(strip))
            else:points=((n,y) for y in range(h-strip,h))
            hits+=any(ink(pixels.getpixel(point)) for point in points)
        if hits<.75*len(rows):return False
    return True

def validate_audio_qr(docx,pdf,panels):
    if not panels:return []
    expected={p['playerUrl'] for p in panels};word=set();printed={}
    with zipfile.ZipFile(docx) as z:
        for name in z.namelist():
            if not name.startswith('word/media/'):continue
            try:
                image=Image.open(BytesIO(z.read(name)))
                if not (.8<=image.width/image.height<=2.5 and image.width<2200):continue
                word.update(r.text for r in zxingcpp.read_barcodes(image))
            except (OSError,ValueError):continue
    if not expected.issubset(word):raise ValueError('Audio QR missing or unreadable in editable Word book')
    for number,page in enumerate(pdf.pages,1):
        # QR images are square, small, and on content pages. The cover is untouched.
        for item in page.images:
            width=item['x1']-item['x0'];height=item['bottom']-item['top']
            if not(45<width<190 and 40<height<140 and .8<=width/height<=2.5):continue
            bounds=(max(0,item['x0']-2),max(0,item['top']-2),min(page.width,item['x1']+2),min(page.height,item['bottom']+2))
            bitmap=page.crop(bounds).to_image(resolution=240,antialias=False).original
            for result in zxingcpp.read_barcodes(bitmap):
                if result.text in expected:
                    panel=next(p for p in panels if p['playerUrl']==result.text)
                    if panel.get('layout')=='modern-corner-v2':
                        scale=bitmap.width/(bounds[2]-bounds[0])
                        visible_card=bitmap.crop((round((item['x0']-bounds[0])*scale),round((item['top']-bounds[1])*scale),round((item['x1']-bounds[0])*scale),round((item['bottom']-bounds[1])*scale)))
                        if not complete_card_border(visible_card):raise ValueError('Audio card border is clipped in the rendered PDF')
                        if item['top']>125:raise ValueError('Audio card is not at the top of the lesson page')
                        if panel['corner']=='top-left' and item['x0']>75:raise ValueError('RTL audio card is not at the left corner')
                        if panel['corner']=='top-right' and item['x1']<page.width-75:raise ValueError('LTR audio card is not at the right corner')
                        for word in page.extract_words():
                            if min(word['x1'],item['x1'])-max(word['x0'],item['x0'])>.5 and min(word['bottom'],item['bottom'])-max(word['top'],item['top'])>.5:raise ValueError('Audio card overlaps the lesson text')
                    printed[result.text]=number
    if set(printed)!=expected:raise ValueError('Audio QR missing or unreadable in rendered PDF')
    return [{'playerUrl':url,'page':printed[url]} for url in sorted(expected)]
