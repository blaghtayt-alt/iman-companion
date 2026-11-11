"""Presentation labels for the owner's exact temporary missing-book test IDs.

These labels grant no source, rendering or publication permission. The normal
intake, Word, visual-review and release gates remain unchanged. No general
testOnly flag or title substring can classify a real book as this temporary test.
"""

SCOPES = {
    'seerah': ('ur', 'id', 'ms', 'bn', 'tr', 'fr', 'pt-BR', 'hi', 'ru', 'es',
               'fa', 'de', 'zh-CN', 'uz', 'th', 'vi', 'ja', 'fil'),
    'articles': ('ur', 'bn', 'pt-BR', 'hi', 'fa', 'de', 'zh-CN', 'uz', 'th',
                 'vi', 'ja', 'fil'),
}
MATERIAL_IDS = {(language, collection): f'automation-test-material-{language}-{collection}-001'
                for collection, languages in SCOPES.items() for language in languages}

# Temporary material badge; notice on a combined download containing that material.
COPY = {
    'ur': ('خودکار نظام کی عارضی آزمائشی مثال', 'مشترکہ ڈاؤن لوڈ میں عارضی آزمائشی مواد شامل ہے'),
    'id': ('Materi uji otomatisasi sementara', 'Unduhan gabungan memuat materi uji sementara'),
    'ms': ('Bahan ujian automasi sementara', 'Muat turun gabungan mengandungi bahan ujian sementara'),
    'bn': ('স্বয়ংক্রিয় ব্যবস্থার সাময়িক পরীক্ষামূলক উপাদান', 'একত্রিত ডাউনলোডে সাময়িক পরীক্ষামূলক উপাদান রয়েছে'),
    'tr': ('Geçici otomasyon test materyali', 'Birleşik indirme geçici test materyali içerir'),
    'fr': ('Contenu temporaire de test automatisé', 'Le téléchargement combiné contient du contenu de test temporaire'),
    'pt-BR': ('Material temporário de teste de automação', 'O download combinado contém material temporário de teste'),
    'hi': ('स्वचालन के लिए अस्थायी परीक्षण सामग्री', 'संयुक्त डाउनलोड में अस्थायी परीक्षण सामग्री शामिल है'),
    'ru': ('Временный материал для проверки автоматизации', 'Общая загрузка содержит временный тестовый материал'),
    'es': ('Material temporal de prueba de automatización', 'La descarga conjunta contiene material temporal de prueba'),
    'fa': ('محتوای موقت برای آزمایش خودکارسازی', 'بستهٔ دانلود ترکیبی شامل محتوای آزمایشی موقت است'),
    'de': ('Vorübergehendes Material zum Automatisierungstest', 'Der Gesamtdownload enthält vorübergehendes Testmaterial'),
    'zh-CN': ('临时自动化测试材料', '合并下载包含临时测试材料'),
    'uz': ('Avtomatlashtirish uchun vaqtinchalik sinov materiali', 'Birlashtirilgan yuklama vaqtinchalik sinov materialini o‘z ichiga oladi'),
    'th': ('เนื้อหาทดสอบระบบอัตโนมัติชั่วคราว', 'ไฟล์ดาวน์โหลดรวมมีเนื้อหาทดสอบชั่วคราว'),
    'vi': ('Tài liệu tạm thời để kiểm thử tự động hóa', 'Bản tải xuống tổng hợp có chứa tài liệu kiểm thử tạm thời'),
    'ja': ('自動化確認用の一時的なテスト資料', '一括ダウンロードには一時的なテスト資料が含まれます'),
    'fil': ('Pansamantalang materyal para sa pagsubok ng awtomasyon', 'May pansamantalang materyal sa pagsubok ang pinagsamang download'),
}


def material_label(book):
    if not isinstance(book, dict):
        return ''
    expected = MATERIAL_IDS.get((book.get('language'), book.get('collection')))
    units = book.get('units', [])
    if (not expected or not isinstance(units, list) or len(units) != 1
            or not isinstance(units[0], dict) or units[0].get('id') != expected):
        return ''
    return COPY[book['language']][0]


def bundle_label(language, books):
    return (COPY[language][1] if any(book.get('language') == language and material_label(book)
                                   for book in books) else '')


def decorate_catalog_row(row, books):
    """Label a presentation row only; never mutate source book/bundle records."""
    books = list(books)
    source = {book['collection']: book for book in books}
    for item in row['books']:
        label = material_label(source.get(item['collection']))
        if label:
            prior = item.get('statusLabel', '')
            item['statusLabel'] = prior + ' · ' + label if prior and prior != label else label
    warning = bundle_label(row['language'], books) if row.get('bundle') else ''
    if warning:
        row['title'] += ' · ' + warning
    return row
