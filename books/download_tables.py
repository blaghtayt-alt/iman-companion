"""Verified release downloads in a 20-language README matrix and native tables."""
from pathlib import Path
import argparse,json,re,hashlib
from urllib.parse import quote
from locale_copy import locale,DOWNLOADS
from bibliography import native_text,digits

COLLECTIONS=['tadabbur-extended','hadith','seerah','articles']
HEADERS=['Quran reflections · extended','Hadith · new extended','Seerah','Articles']
MARKER_START='<!-- IMAN-BOOK-DOWNLOADS:START -->'
MARKER_END='<!-- IMAN-BOOK-DOWNLOADS:END -->'
# title, book, editable file, reading file, included units, preparing
COPY={
'en':['Book downloads','Book','Editable book','Reading copy','Included items','Preparing'],
'ar':['تنزيل الكتب','الكتاب','نسخة قابلة للتحرير','نسخة للقراءة','المواد المشمولة','قيد الإعداد'],
'ur':['کتابیں ڈاؤن لوڈ کریں','کتاب','قابل تدوین کتاب','مطالعے کی نقل','شامل مواد','تیاری جاری ہے'],
'id':['Unduhan buku','Buku','Buku yang dapat disunting','Salinan bacaan','Materi yang disertakan','Sedang disiapkan'],
'ms':['Muat turun buku','Buku','Buku boleh sunting','Salinan bacaan','Bahan yang disertakan','Sedang disediakan'],
'bn':['বই ডাউনলোড','বই','সম্পাদনাযোগ্য বই','পাঠের অনুলিপি','অন্তর্ভুক্ত বিষয়','প্রস্তুত হচ্ছে'],
'tr':['Kitap indirmeleri','Kitap','Düzenlenebilir kitap','Okuma nüshası','İçerilen metinler','Hazırlanıyor'],
'fr':['Téléchargement des livres','Livre','Livre modifiable','Version de lecture','Textes inclus','En préparation'],
'pt-BR':['Downloads de livros','Livro','Livro editável','Versão de leitura','Textos incluídos','Em preparação'],
'hi':['पुस्तकें डाउनलोड करें','पुस्तक','संपादन योग्य पुस्तक','पढ़ने की प्रति','शामिल सामग्री','तैयार की जा रही है'],
'ru':['Скачать книги','Книга','Редактируемая книга','Версия для чтения','Включённые материалы','Готовится'],
'es':['Descarga de libros','Libro','Libro editable','Versión de lectura','Textos incluidos','En preparación'],
'fa':['دریافت کتاب‌ها','کتاب','کتاب ویرایش‌پذیر','نسخهٔ مطالعه','مطالب موجود','در حال آماده‌سازی'],
'de':['Bücher herunterladen','Buch','Bearbeitbares Buch','Leseausgabe','Enthaltene Texte','In Vorbereitung'],
'zh-CN':['书籍下载','书籍','可编辑书籍','阅读版','收录内容','准备中'],
'uz':['Kitoblarni yuklab olish','Kitob','Tahrirlanadigan kitob','O‘qish nusxasi','Kiritilgan materiallar','Tayyorlanmoqda'],
'th':['ดาวน์โหลดหนังสือ','หนังสือ','หนังสือที่แก้ไขได้','ฉบับอ่าน','เนื้อหาที่รวมไว้','กำลังจัดเตรียม'],
'vi':['Tải sách','Sách','Sách có thể chỉnh sửa','Bản để đọc','Nội dung được đưa vào','Đang chuẩn bị'],
'ja':['書籍のダウンロード','書籍','編集可能な書籍','閲覧用の書籍','収録内容','準備中'],
'fil':['Mga aklat na mada-download','Aklat','Nae-edit na aklat','Kopyang pambasa','Mga nilalaman','Inihahanda']}

def cell(text):return str(text).replace('|','\\|').replace('\n',' ')
def release_url(repo,tag,file):return f'https://github.com/{repo}/releases/download/{quote(tag,safe="")}/{quote(file,safe="")}'

def verified_books(index,folder,repo,tag):
    ready={}
    if index.get('previewOnly') is not False:return ready
    for book in index.get('books',[]):
        if book.get('exportVerified') is not True or book.get('previewOnly'):continue
        if book['collection']=='hadith' and book.get('hadithEdition')!='new-extended':raise ValueError('Legacy short Hadith books cannot be current downloads')
        if book['collection'] not in COLLECTIONS:raise ValueError('Unknown downloadable book category')
        if book['language'] not in COPY:raise ValueError('Unknown downloadable book language')
        if Path(book['file']).suffix!='.docx':raise ValueError('Expected an editable Word book asset')
        key=(book['language'],book['collection'])
        if key in ready:raise ValueError('Duplicate language/book download')
        for ext,hashkey in [('docx','sha256'),('pdf','pdfSha256')]:
            filename=Path(book['file']).with_suffix('.'+ext).name
            if Path(book['file']).name!=book['file']:raise ValueError('Book filename is not a local asset basename')
            file=folder/filename
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=book.get(hashkey):raise ValueError('Missing or changed verified download asset: '+filename)
        item=dict(book);item['download']=release_url(repo,tag,book['file']);item['pdfDownload']=release_url(repo,tag,Path(book['file']).with_suffix('.pdf').name)
        ready[key]=item
    return ready

def render(conf,index,folder,repo,tag):
    languages=conf['languages'];ready=verified_books(index,folder,repo,tag)
    if set(languages)!=set(COPY):raise ValueError('Download labels must cover all 20 configured languages')
    intro=('Book editions are in preparation. Links appear only after the Word and PDF files have been verified.' if not ready else 'Each download contains the currently available complete published material in that language. The language pages show how many items are included. New extended Hadith lessons and extended Quran reflections use the approved book layout.')
    root=['### Books by language','',intro,'', '| Language | '+' | '.join(HEADERS)+' |','| --- | --- | --- | --- | --- |'];pages={}
    for lang,lc in languages.items():
        title,booklabel,editable,reading,count,pending=COPY[lang]
        for text in COPY[lang]:native_text(text,lang)
        native=locale(lang)['nativeName'];row=[f'[{cell(native)}](https://github.com/{repo}/blob/main/books/downloads/{quote(lang)}/README.md)']
        page=['# '+title,'',native,'','| '+' | '.join([booklabel,editable,reading,count])+' |','| --- | --- | --- | --- |']
        for collection in COLLECTIONS:
            item=ready.get((lang,collection));label=lc['titles'][collection];native_text(label,lang)
            if item:
                row.append(f'[{cell(editable)}]({item["download"]}) · [{cell(reading)}]({item["pdfDownload"]})')
                page.append('| '+' | '.join([cell(label),f'[{DOWNLOADS[lang][0]}]({item["download"]})',f'[{DOWNLOADS[lang][1]}]({item["pdfDownload"]})',digits(str(len(item.get('units',[]))),lang)])+' |')
            else:
                row.append(cell(pending));page.append('| '+' | '.join([cell(label),pending,pending,'—'])+' |')
        root.append('| '+' | '.join(row)+' |')
        if lang!='ar':page+=['',locale(lang)['notice']]
        for line in page:
            # Check visible labels, not URL targets containing technical filenames.
            native_text(re.sub(r'\]\([^)]*\)',']',line),lang)
        pages[lang]='\n'.join(page)+'\n'
    return '\n'.join(root)+'\n',pages

def merge_readme(original,table):
    if original.count(MARKER_START)!=original.count(MARKER_END) or original.count(MARKER_START)>1:raise ValueError('Ambiguous README download markers')
    block=MARKER_START+'\n'+table.rstrip()+'\n'+MARKER_END
    if MARKER_START in original:
        start=original.index(MARKER_START);end=original.index(MARKER_END,start)+len(MARKER_END)
        return original[:start]+block+original[end:]
    match=re.search(r'^## Downloads\s*$',original,re.M)
    if match:return original[:match.end()]+'\n\n'+block+'\n'+original[match.end():]
    return original.rstrip()+'\n\n## Downloads\n\n'+block+'\n'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--repo',required=True);ap.add_argument('--tag',required=True);args=ap.parse_args()
    conf=json.loads((args.root/'books/config.json').read_text(encoding='utf-8'));index=json.loads((args.folder/'index.json').read_text(encoding='utf-8'))
    table,pages=render(conf,index,args.folder,args.repo,args.tag)
    (args.folder/'README_DOWNLOADS.md').write_text(table,encoding='utf-8')
    for lang,page in pages.items():
        target=args.folder/'readme-pages'/lang/'README.md';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(page,encoding='utf-8')
    print(json.dumps({'languages':len(pages),'downloadRows':len(pages),'readyBookPairs':len(verified_books(index,args.folder,args.repo,args.tag)),'previewOnly':bool(index.get('previewOnly'))}))
if __name__=='__main__':main()
