"""Deterministic, source-bound audio QR panels for material opening pages."""
from io import BytesIO
from pathlib import Path
import hashlib,json,re
from urllib.parse import quote,urlsplit,urlencode
import qrcode
from docx.shared import Inches,Pt,Mm
from corner_audio_card import render_card
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from bibliography import native_text

PLAYER_BASE='https://blaghtayt-alt.github.io/iman-companion/listen/'
COLLECTIONS={'tadabbur-extended','hadith','seerah','articles'}
CAPTIONS={
'en':['Scan to listen to this material','Open the audio player'],
'ar':['امسح الرمز للاستماع إلى هذه المادة','افتح المشغّل الصوتي'],
'ur':['یہ مواد سننے کے لیے کوڈ اسکین کریں','آڈیو پلیئر کھولیں'],
'id':['Pindai kode untuk mendengarkan materi ini','Buka pemutar audio'],
'ms':['Imbas kod untuk mendengar bahan ini','Buka pemain audio'],
'bn':['এই লেখাটি শুনতে কোডটি স্ক্যান করুন','অডিও প্লেয়ার খুলুন'],
'tr':['Bu metni dinlemek için kodu tarayın','Ses oynatıcıyı aç'],
'fr':['Scannez le code pour écouter ce texte','Ouvrir le lecteur audio'],
'pt-BR':['Escaneie o código para ouvir este material','Abrir o reprodutor de áudio'],
'hi':['यह सामग्री सुनने के लिए कोड स्कैन करें','ऑडियो प्लेयर खोलें'],
'ru':['Отсканируйте код, чтобы послушать этот материал','Открыть аудиоплеер'],
'es':['Escanea el código para escuchar este material','Abrir el reproductor de audio'],
'fa':['برای شنیدن این مطلب، کد را اسکن کنید','پخش‌کنندهٔ صوتی را باز کنید'],
'de':['Code scannen und diesen Text anhören','Audioplayer öffnen'],
'zh-CN':['扫描二维码收听本篇内容','打开音频播放器'],
'uz':['Ushbu materialni tinglash uchun kodni skanerlang','Audio pleyerni ochish'],
'th':['สแกนรหัสเพื่อฟังเนื้อหานี้','เปิดเครื่องเล่นเสียง'],
'vi':['Quét mã để nghe nội dung này','Mở trình phát âm thanh'],
'ja':['コードを読み取ってこの教材の音声を聴く','音声プレーヤーを開く'],
'fil':['I-scan ang code para mapakinggan ang babasahing ito','Buksan ang tagapagpatugtog']}

def hex64(value):return isinstance(value,str) and bool(re.fullmatch('[0-9a-f]{64}',value))

def validate_record(record):
    if record.get('collection') not in COLLECTIONS or record.get('language') not in CAPTIONS:raise ValueError('Unsupported audio material identity')
    if not isinstance(record.get('materialId'),str) or not re.fullmatch('[a-zA-Z0-9:_-]{1,160}',record['materialId']):raise ValueError('Invalid audio material ID')
    for field in ['sourceSHA256','audioSHA256']:
        if not hex64(record.get(field)):raise ValueError('Audio lacks its exact source/audio hash')
    if not (hex64(record.get('readerTextSHA256')) or hex64(record.get('readingSHA256'))):raise ValueError('Audio lacks its target-language reading binding')
    url=urlsplit(record.get('audioUrl',''))
    if url.scheme!='https' or url.netloc!='github.com' or url.query or url.fragment or not url.path.startswith('/blaghtayt-alt/iman-companion/releases/download/'):raise ValueError('Audio must use its published immutable release asset')
    if not re.fullmatch(r'/blaghtayt-alt/iman-companion/releases/download/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+\.(?:opus|mp3|m4a|ogg|wav)',url.path):raise ValueError('Invalid direct audio asset URL')
    if record['audioSHA256'][:16] not in url.path.rsplit('/',1)[1]:raise ValueError('Audio filename must identify the pinned recording')
    if not isinstance(record.get('audioBytes'),int) or record['audioBytes']<=0:raise ValueError('Missing published audio size')
    native_text(record.get('title',''),record['language'])
    if not record.get('title'):raise ValueError('Missing native material title')
    return record

def audio_for_unit(unit,registry):
    if registry.get('schema')!='iman-material-audio-v1' or registry.get('playerBase')!=PLAYER_BASE:raise ValueError('Invalid audio registry/player')
    matches=[]
    for record in registry.get('entries',[]):
        if record.get('status')!='published' or record.get('approved') is not True:continue
        if (record.get('materialId'),record.get('language'),record.get('collection'))!=(unit['id'],unit['language'],unit['collection']):continue
        if record.get('sourceSHA256') not in unit.get('sourceHashes',[]):continue
        validate_record(record)
        if record.get('readerTextSHA256') and record['readerTextSHA256']!=unit.get('readerTextSHA256'):continue
        if record.get('readingSHA256') and record['readingSHA256'] not in {b.get('sha256') for b in unit.get('inputBindings',[])}:continue
        matches.append(record)
    if len(matches)>1:raise ValueError('Ambiguous audio for one material revision')
    return matches[0] if matches else None

def player_url(record):
    return PLAYER_BASE+'?'+urlencode({'m':record['materialId'],'lang':record['language'],'v':record['sourceSHA256']},quote_via=quote)

def qr_png(url):
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4)
    qr.add_data(url);qr.make(fit=True)
    out=BytesIO();qr.make_image(fill_color='black',back_color='white').save(out,format='PNG')
    return out.getvalue()

def load_registry(root,conf):
    setting=conf.get('audioRegistry')
    if not setting:return {'schema':'iman-material-audio-v1','playerBase':PLAYER_BASE,'entries':[]}
    path=(root/setting['path']).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Audio registry escapes the checkout')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=setting['sha256']:raise ValueError('Stale audio registry binding')
    return json.loads(raw)

def linked_run(paragraph,run,url):
    link=OxmlElement('w:hyperlink');link.set(qn('r:id'),paragraph.part.relate_to(url,RT.HYPERLINK,is_external=True));link.append(run._r);paragraph._p.append(link)

def add_audio_panel(doc,unit,registry,family,arabic,add_text,direction,heading_paragraphs=None,fonts=None,cache_root=None,force_new_page=True):
    record=audio_for_unit(unit,registry)
    if record is None:return None
    if not heading_paragraphs or not fonts or cache_root is None:raise ValueError('Corner audio needs the material headings, pinned font paths and card cache')
    lang=unit['language'];url=player_url(record)
    card,metrics=render_card(url,lang,fonts[family]['Bold'],cache_root)
    section=doc.sections[-1];available=section.page_width-section.left_margin-section.right_margin
    card_width=Mm(metrics['widthMM']);card_column_width=card_width+Mm(4);gap=Mm(8);title_width=available-card_column_width-gap
    if title_width<Mm(52):raise ValueError('Audio card leaves too little title space')
    first=heading_paragraphs[0]._p
    anchor=doc.add_paragraph();anchor.paragraph_format.page_break_before=force_new_page
    anchor.paragraph_format.keep_with_next=True;anchor.paragraph_format.space_before=Pt(0);anchor.paragraph_format.space_after=Pt(0);anchor.paragraph_format.line_spacing=Pt(1)
    first.addprevious(anchor._p)
    table=doc.add_table(rows=1,cols=3);table.alignment=WD_TABLE_ALIGNMENT.LEFT;table.autofit=False
    # LibreOffice gives an inline image a small anchor inset. Leave room for it
    # inside the cell so the complete card border stays inside the clipping box.
    rtl=lang in {'ar','ur','fa'};widths=[card_column_width,gap,title_width] if rtl else [title_width,gap,card_column_width]
    for i,width in enumerate(widths):table.columns[i].width=width;table.cell(0,i).width=width
    props=table._tbl.tblPr
    width=props.find(qn('w:tblW'));width.set(qn('w:w'),str(round(available/635)));width.set(qn('w:type'),'dxa')
    borders=OxmlElement('w:tblBorders')
    for side in ['top','left','bottom','right','insideH','insideV']:
        b=OxmlElement('w:'+side);b.set(qn('w:val'),'nil');borders.append(b)
    props.append(borders)
    # Explicit table defaults avoid inherited NormalTable padding in LibreOffice.
    # Zero cell overrides alone can leave the image clipped by that padding.
    indent=OxmlElement('w:tblInd');indent.set(qn('w:w'),'0');indent.set(qn('w:type'),'dxa');props.append(indent)
    defaults=OxmlElement('w:tblCellMar')
    for side in ['top','left','bottom','right','start','end']:
        m=OxmlElement('w:'+side);m.set(qn('w:w'),'0');m.set(qn('w:type'),'dxa');defaults.append(m)
    props.append(defaults);table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    for cell in table.rows[0].cells:
        cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.TOP
        margins=OxmlElement('w:tcMar')
        for side in ['top','left','bottom','right','start','end']:
            m=OxmlElement('w:'+side);m.set(qn('w:w'),'0');m.set(qn('w:type'),'dxa');margins.append(m)
        cell._tc.get_or_add_tcPr().append(margins)
        for p in cell.paragraphs:p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(1)
    card_cell=table.cell(0,0 if rtl else 2);title_cell=table.cell(0,2 if rtl else 0)
    # Move exact existing heading paragraphs rather than copying/retyping titles.
    title_cell._tc.remove(title_cell.paragraphs[0]._p)
    first.addprevious(table._tbl)
    for p in heading_paragraphs:
        p.paragraph_format.page_break_before=False;p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(6)
        title_cell._tc.append(p._p)
    p=card_cell.paragraphs[0];p.alignment=0;p.paragraph_format.line_spacing=1.0
    p.paragraph_format.left_indent=Pt(0);p.paragraph_format.right_indent=Pt(0);p.paragraph_format.first_line_indent=Pt(0)
    run=p.add_run();picture=run.add_picture(str(card),width=card_width)
    picture._inline.docPr.set('descr',CAPTIONS[lang][0]);picture._inline.docPr.set('title',CAPTIONS[lang][1])
    rid=p.part.relate_to(url,RT.HYPERLINK,is_external=True)
    for props in [picture._inline.docPr]+list(picture._inline.iter(qn('pic:cNvPr'))):
        click=OxmlElement('a:hlinkClick');click.set(qn('r:id'),rid);click.set('tooltip',CAPTIONS[lang][1]);props.append(click)
    # Give both the editable Word image and its PDF annotation the direct URL.
    linked_run(p,run,url)
    spacer=doc.add_paragraph();spacer.paragraph_format.space_after=Pt(19);spacer.paragraph_format.space_before=Pt(0);spacer.paragraph_format.line_spacing=Pt(1)
    return {'materialId':unit['id'],'language':lang,'sourceSHA256':record['sourceSHA256'],'audioSHA256':record['audioSHA256'],'playerUrl':url,'qrSHA256':hashlib.sha256(card.read_bytes()).hexdigest(),'layout':'modern-corner-v2','corner':'top-left' if rtl else 'top-right','cardWidthMM':metrics['widthMM'],'cardHeightMM':metrics['heightMM'],'printedQRModuleMM':metrics['printedModuleMM']}
