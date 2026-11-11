"""Verified release downloads in a 20-language README matrix and native tables."""
from pathlib import Path
import argparse,json,re,hashlib
from urllib.parse import quote
from locale_copy import locale,DOWNLOADS
from bibliography import native_text,digits
from download_bundle_copy import BUNDLE_COPY
from preparation_copy import LIMITED
from temporary_test_labels import material_label as test_material_label, bundle_label as test_bundle_label

COLLECTIONS=['tadabbur-extended','hadith','seerah','articles']
HEADERS=['Quran reflections · extended','Hadith · new extended','Seerah','Articles']
MARKER_START='<!-- IMAN-BOOK-DOWNLOADS:START -->'
MARKER_END='<!-- IMAN-BOOK-DOWNLOADS:END -->'
# title, book, editable file, reading file, included units, not yet published
COPY={
'en':['Book downloads','Book','Editable','Readable','Included items','Not yet published'],
'ar':['تنزيل الكتب','الكتاب','نسخة قابلة للتحرير','نسخة للقراءة','المواد المشمولة','لم يصدر بعد'],
'ur':['کتابیں ڈاؤن لوڈ کریں','کتاب','قابل تدوین کتاب','مطالعے کی نقل','شامل مواد','ابھی شائع نہیں ہوا'],
'id':['Unduhan buku','Buku','Buku yang dapat disunting','Salinan bacaan','Materi yang disertakan','Belum tersedia'],
'ms':['Muat turun buku','Buku','Buku boleh sunting','Salinan bacaan','Bahan yang disertakan','Belum tersedia'],
'bn':['বই ডাউনলোড','বই','সম্পাদনাযোগ্য বই','পাঠের অনুলিপি','অন্তর্ভুক্ত বিষয়','এখনও প্রকাশিত হয়নি'],
'tr':['Kitap indirmeleri','Kitap','Düzenlenebilir kitap','Okuma nüshası','İçerilen metinler','Henüz yayımlanmadı'],
'fr':['Téléchargement des livres','Livre','Livre modifiable','Version de lecture','Textes inclus','Pas encore disponible'],
'pt-BR':['Downloads de livros','Livro','Livro editável','Versão de leitura','Textos incluídos','Ainda não disponível'],
'hi':['पुस्तकें डाउनलोड करें','पुस्तक','संपादन योग्य पुस्तक','पढ़ने की प्रति','शामिल सामग्री','अभी उपलब्ध नहीं है'],
'ru':['Скачать книги','Книга','Редактируемая книга','Версия для чтения','Включённые материалы','Пока не опубликовано'],
'es':['Descarga de libros','Libro','Libro editable','Versión de lectura','Textos incluidos','Aún no disponible'],
'fa':['دریافت کتاب‌ها','کتاب','کتاب ویرایش‌پذیر','نسخهٔ مطالعه','مطالب موجود','هنوز منتشر نشده'],
'de':['Bücher herunterladen','Buch','Bearbeitbares Buch','Leseausgabe','Enthaltene Texte','Noch nicht verfügbar'],
'zh-CN':['书籍下载','书籍','可编辑书籍','阅读版','收录内容','尚未发布'],
'uz':['Kitoblarni yuklab olish','Kitob','Tahrirlanadigan kitob','O‘qish nusxasi','Kiritilgan materiallar','Hali nashr etilmagan'],
'th':['ดาวน์โหลดหนังสือ','หนังสือ','หนังสือที่แก้ไขได้','ฉบับอ่าน','เนื้อหาที่รวมไว้','ยังไม่เผยแพร่'],
'vi':['Tải sách','Sách','Sách có thể chỉnh sửa','Bản để đọc','Nội dung được đưa vào','Chưa phát hành'],
'ja':['書籍のダウンロード','書籍','編集可能な書籍','閲覧用の書籍','収録内容','未公開'],
'fil':['Mga aklat na mada-download','Aklat','Nae-edit na aklat','Kopyang pambasa','Mga nilalaman','Hindi pa nailalathala']}

def cell(text):return str(text).replace('|','\\|').replace('\n',' ')
def release_url(repo,tag,file):return f'https://github.com/{repo}/releases/download/{quote(tag,safe="")}/{quote(file,safe="")}'

def format_label(text,extension):
    return f'{text} ({dict(docx="Word",pdf="PDF")[extension]})'

def download_labels(language):
    return {extension:format_label(text,extension) for extension,text in zip(('docx','pdf'),DOWNLOADS[language])}

def native_download_text(text,language):
    """Allow the requested format suffixes only at the download UI boundary."""
    native_text(re.sub(r' \((?:Word|PDF)\)(?=\s*(?:$|\]|\|))','',text),language)
    return text

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
    return render_ready(conf,verified_books(index,folder,repo,tag),repo)

def render_ready(conf,ready,repo,bundles=None,coverage=None):
    """Render independently verified immutable pairs across different releases."""
    languages=conf['languages']
    if set(languages)!=set(COPY):raise ValueError('Download labels must cover all 20 configured languages')
    intro=('Links appear only after the Word and PDF files have been verified and published.' if not ready else 'Each book contains the verified material listed on its language page. New extended Hadith lessons and extended Quran reflections use the approved book layout.')
    counts={collection:sum((language,collection) in ready for language in languages) for collection in COLLECTIONS}
    total=len(languages)*len(COLLECTIONS);available=sum(counts.values())
    availability=f'Published book editions: **{available} of {total}** language/category combinations. **{total-available}** do not yet have a published Word/PDF pair.'
    categories=' · '.join(f'{name}: {counts[collection]}/{len(languages)}' for name,collection in zip(['Quran reflections','Hadith','Seerah','Articles'],COLLECTIONS))
    root=['### Books by language','',intro,'',availability,'',categories+'.','', '| Language | '+' | '.join(HEADERS)+' |','| --- | --- | --- | --- | --- |'];pages={}
    test_count=sum(bool(test_material_label(book)) for book in ready.values())
    if test_count:
        root[3:3]=['',f'Temporary automation test: **{test_count}** published pairs use only `TEST TEST` as their material text and will be removed after verification.']
    if bundles is not None:
        if set(bundles)-set(languages):raise ValueError('Unknown combined-download language')
        root[-2]+=' Combined downloads |';root[-1]+=' --- |'
        for lang,item in bundles.items():
            parts=[b for (language,_),b in ready.items()if language==lang]
            if not parts or item.get('parts')!=len(parts):raise ValueError('Combined-download inventory differs from current books')
            for ext in ['zip','docx','pdf']:
                url=item.get(ext,'');prefix=f'https://github.com/{repo}/releases/download/'
                if not url.startswith(prefix)or any(c in url for c in ['?','#','\n','\r']):raise ValueError('Invalid combined-download release URL')
                allowed={f'Iman_Companion_{lang}_all-books.{ext}'}
                if ext!='zip'and len(parts)==1:allowed.add(parts[0]['file']if ext=='docx'else str(Path(parts[0]['file']).with_suffix('.pdf')))
                if url.rsplit('/',1)[-1]not in allowed:raise ValueError('Combined-download file belongs to another language or scope')
    for lang,lc in languages.items():
        title,booklabel,editable,reading,count,pending=COPY[lang]
        for text in COPY[lang]:native_text(text,lang)
        editable=format_label(editable,'docx');reading=format_label(reading,'pdf');downloads=download_labels(lang)
        native=locale(lang)['nativeName'];row=[f'[{cell(native)}](https://github.com/{repo}/blob/main/books/downloads/{quote(lang)}/README.md)']
        page=['# '+title,'',native,'','| '+' | '.join([booklabel,editable,reading,count])+' |','| --- | --- | --- | --- |']
        edition_details=[]
        coverage_details=[]
        for collection in COLLECTIONS:
            item=ready.get((lang,collection));label=lc['titles'][collection]
            test_label=test_material_label(item)
            content_scope=(coverage or {}).get((lang,collection))
            content_copy=content_scope.get('presentation',{}) if content_scope else {}
            if item and (item.get('editionScope') or item.get('availability')):
                label=item.get('collectionLabel',label);titles=[u['title'] for u in item['units']]
                if not isinstance(titles,list) or not titles:raise ValueError('Edition must identify its included material')
                for included in titles:native_text(included,lang)
                edition_details.append((label,titles))
                if item.get('availability'):
                    edition_details.append((LIMITED[lang],[]))
            if test_label:label+=' · '+test_label
            native_text(label,lang)
            if item:
                if content_scope and content_scope.get('includedIds')!=[str(unit['id']) for unit in item['units']]:
                    raise ValueError('Download coverage differs from the verified book contents')
                row.append(f'[{cell(editable)}]({item["download"]})<br>[{cell(reading)}]({item["pdfDownload"]})'+(f'<br>**{cell(test_label)}**' if test_label else ''))
                included_count=digits(str(len(item.get('units',[]))),lang)
                if content_copy.get('includedLabel'):
                    included_count+=' · '+content_copy['includedLabel']
                    coverage_details.append((label,content_copy))
                page.append('| '+' | '.join([cell(label),f'[{downloads["docx"]}]({item["download"]})',f'[{downloads["pdf"]}]({item["pdfDownload"]})',cell(included_count)])+' |')
            else:
                row.append(cell(pending));page.append('| '+' | '.join([cell(label),pending,pending,'—'])+' |')
        for edition_label,titles in edition_details:
            page+=['','## '+cell(edition_label),'']+['- '+cell(t) for t in titles]
        for edition_label,scope_copy in coverage_details:
            page+=['','### '+cell(edition_label),'',scope_copy['includedLabel']]
            if scope_copy.get('statusLabel'):page+=['',scope_copy['statusLabel']]
            if scope_copy.get('notes'):page+=['']+['- '+cell(note) for note in scope_copy['notes']]
        if bundles is not None:
            together,merged,zipped=BUNDLE_COPY[lang]
            for text in BUNDLE_COPY[lang]:native_text(text,lang)
            item=bundles.get(lang)
            if item:
                warning=test_bundle_label(lang,[book for (language,_),book in ready.items() if language==lang])
                chooser=f'https://blaghtayt-alt.github.io/iman-companion/books/?lang={quote(lang)}'
                row.append(f'[{cell(together)}]({chooser})'+(f'<br>**{cell(warning)}**' if warning else ''))
                page+=['','## '+together]
                if warning:page+=['',warning]
                page+=['',merged,'',f'[{downloads["docx"]}]({item["docx"]})','',f'[{downloads["pdf"]}]({item["pdf"]})','',f'[{zipped}]({item["zip"]})']
            else:row.append(cell(pending))
        root.append('| '+' | '.join(row)+' |')
        if lang!='ar':page+=['',locale(lang)['notice']]
        for line in page:
            # Check visible labels, not URL targets containing technical filenames.
            native_download_text(re.sub(r'\]\([^)]*\)',']',line),lang)
        pages[lang]='\n'.join(page)+'\n'
    if any(item.get('availability') for item in ready.values()):root+=['','Verified earlier editions include only the listed contents; new material is awaiting release checks.']
    if any(item.get('presentation',{}).get('statusLabel') for item in (coverage or {}).values()):
        root+=['','Each language page lists the exact included lesson or surah numbers and any material awaiting publication or a coverage check.']
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
    from book_content_coverage import download_coverage
    ready=verified_books(index,args.folder,args.repo,args.tag)
    table,pages=render_ready(conf,ready,args.repo,coverage=download_coverage(args.root,ready,conf=conf))
    (args.folder/'README_DOWNLOADS.md').write_text(table,encoding='utf-8')
    for lang,page in pages.items():
        target=args.folder/'readme-pages'/lang/'README.md';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(page,encoding='utf-8')
    print(json.dumps({'languages':len(pages),'downloadRows':len(pages),'readyBookPairs':len(verified_books(index,args.folder,args.repo,args.tag)),'previewOnly':bool(index.get('previewOnly'))}))
if __name__=='__main__':main()
