"""Reconcile installed readers, source selection and actual download contents.

This is a diagnostic and presentation layer. It never makes a source eligible,
creates approval evidence, changes a published snapshot or renumbers lessons.
An unbound source can have an existing review; UNKNOWN is not a review verdict.
"""
from collections import defaultdict
from pathlib import Path
import json
import re

from bibliography import digits, native_text
from book_edition_scope import MAP, RETIRED, available, current_seerah_rows, pinned, select
from locale_copy import locale

SCHEMA = 'iman-book-content-coverage-v1'
COLLECTIONS = ('tadabbur-extended', 'hadith', 'seerah', 'articles')

# Included, partial edition, not selected for this edition, awaiting a released
# replacement, no installed current source, diagnostic temporarily unavailable.
# These labels describe book coverage, not translation or scholarly approval.
COPY = {
    'en': ('Included', 'Partial edition', 'Not included in this edition', 'Awaiting the updated book', 'Current source not available in this language', 'Coverage check pending'),
    'ar': ('المشمول', 'نسخة جزئية', 'غير مشمول في هذه النسخة', 'بانتظار نسخة الكتاب المحدثة', 'المادة الحالية غير متاحة بهذه اللغة', 'بانتظار التحقق من المحتوى المشمول'),
    'ur': ('شامل مواد', 'جزوی نسخہ', 'اس نسخے میں شامل نہیں', 'کتاب کے تازہ نسخے کا انتظار ہے', 'اس زبان میں موجودہ ماخذ دستیاب نہیں', 'شامل مواد کی جانچ باقی ہے'),
    'id': ('Termasuk', 'Edisi sebagian', 'Tidak termasuk dalam edisi ini', 'Menunggu buku yang diperbarui', 'Sumber terkini belum tersedia dalam bahasa ini', 'Pemeriksaan cakupan belum selesai'),
    'ms': ('Disertakan', 'Edisi separa', 'Tidak disertakan dalam edisi ini', 'Menunggu buku yang dikemas kini', 'Sumber semasa belum tersedia dalam bahasa ini', 'Semakan kandungan belum selesai'),
    'bn': ('অন্তর্ভুক্ত', 'আংশিক সংস্করণ', 'এই সংস্করণে অন্তর্ভুক্ত নয়', 'বইয়ের হালনাগাদ সংস্করণের অপেক্ষায়', 'এই ভাষায় বর্তমান উৎস উপলব্ধ নয়', 'অন্তর্ভুক্ত বিষয়ের যাচাই বাকি'),
    'tr': ('İçerilenler', 'Kısmi baskı', 'Bu baskıya dahil değil', 'Güncellenmiş kitap bekleniyor', 'Güncel kaynak bu dilde mevcut değil', 'İçerik kapsamı kontrolü bekleniyor'),
    'fr': ('Inclus', 'Édition partielle', 'Non inclus dans cette édition', 'En attente du livre mis à jour', 'Source actuelle indisponible dans cette langue', 'Vérification du contenu en attente'),
    'pt-BR': ('Incluído', 'Edição parcial', 'Não incluído nesta edição', 'Aguardando o livro atualizado', 'Fonte atual indisponível neste idioma', 'Verificação do conteúdo pendente'),
    'hi': ('शामिल', 'आंशिक संस्करण', 'इस संस्करण में शामिल नहीं', 'पुस्तक के अद्यतन संस्करण की प्रतीक्षा', 'इस भाषा में वर्तमान स्रोत उपलब्ध नहीं', 'शामिल सामग्री की जाँच बाकी है'),
    'ru': ('Включено', 'Частичное издание', 'Не включено в это издание', 'Ожидается обновлённая книга', 'Текущий источник на этом языке недоступен', 'Проверка состава книги ожидается'),
    'es': ('Incluido', 'Edición parcial', 'No incluido en esta edición', 'Pendiente del libro actualizado', 'Fuente actual no disponible en este idioma', 'Comprobación del contenido pendiente'),
    'fa': ('محتوای موجود', 'نسخهٔ جزئی', 'در این نسخه گنجانده نشده', 'در انتظار نسخهٔ به‌روز کتاب', 'منبع فعلی به این زبان موجود نیست', 'بررسی محتوای موجود در انتظار است'),
    'de': ('Enthalten', 'Teilausgabe', 'Nicht in dieser Ausgabe enthalten', 'Aktualisiertes Buch ausstehend', 'Aktuelle Quelle in dieser Sprache nicht verfügbar', 'Inhaltsabgleich ausstehend'),
    'zh-CN': ('收录内容', '部分收录版', '本版未收录', '等待更新后的书籍', '本语言暂无现行来源文本', '收录范围待核对'),
    'uz': ('Kiritilgan', 'Qisman nashr', 'Ushbu nashrga kiritilmagan', 'Yangilangan kitob kutilmoqda', 'Joriy manba bu tilda mavjud emas', 'Qamrov tekshiruvi kutilmoqda'),
    'th': ('เนื้อหาที่รวมไว้', 'ฉบับที่รวมเนื้อหาบางส่วน', 'ไม่รวมอยู่ในฉบับนี้', 'รอหนังสือฉบับปรับปรุง', 'ยังไม่มีต้นฉบับปัจจุบันในภาษานี้', 'รอการตรวจสอบเนื้อหาที่รวมไว้'),
    'vi': ('Nội dung có trong sách', 'Ấn bản một phần', 'Không có trong ấn bản này', 'Đang chờ sách cập nhật', 'Chưa có nguồn hiện hành bằng ngôn ngữ này', 'Đang chờ kiểm tra phạm vi nội dung'),
    'ja': ('収録', '一部収録版', 'この版には未収録', '更新版の公開待ち', 'この言語の現行資料は未掲載', '収録範囲を確認中'),
    'fil': ('Kasama', 'Bahagyang edisyon', 'Hindi kasama sa edisyong ito', 'Hinihintay ang na-update na aklat', 'Walang kasalukuyang sanggunian sa wikang ito', 'Naghihintay ng pagsusuri sa saklaw'),
}


def _read(path, default=None):
    return json.loads(path.read_bytes()) if path.is_file() else default


def _current_metadata(row):
    return (not row.get('archived') and row.get('current', True) is not False
            and not any(str(row.get(field, '')).lower() in RETIRED
                        for field in ('status', 'publicationStatus', 'translationStatus')))


def _paths(row):
    return {name: row[name] for name in ('json', 'markdown') if row.get(name)}


def _identity(row):
    return row.get('language'), MAP.get(row.get('collection')), str(row.get('id'))


def discover_readers(root, languages, catalog=None):
    """Find canonical reader candidates, never source archives or sidecar copies.

    A discovered file is not an approval. Declared filename/payload identities
    must agree; malformed files remain diagnostic errors instead of disappearing.
    Already registered paths are checked through their real source adapters,
    rather than imposing one new schema on heterogeneous existing wrappers.
    Catalogued retired identities are filtered again by ``scope_coverage`` so a
    surviving old file cannot resurrect an archived/withdrawn source.
    """
    root = Path(root).resolve()
    catalog = catalog if catalog is not None else _read(root / 'materials/catalog.json', {'entries': []})
    registered_paths = {path for row in catalog.get('entries', []) for path in _paths(row).values()}
    found, errors = [], []
    for language in languages:
        folder = root / 'materials/hadith' / ('essential-' + language)
        for path in sorted(folder.glob('*.json')):
            if not re.fullmatch(r'\d{3}', path.stem):
                continue
            relative = path.relative_to(root).as_posix()
            if relative in registered_paths:
                continue
            try:
                value = json.loads(path.read_bytes())
                ident = f'essential-01-{int(path.stem):03d}'
                reader = value.get('reader', {}) if isinstance(value, dict) else {}
                source_language = value.get('language') if isinstance(value, dict) else None
                if source_language is None and isinstance(reader, dict):
                    source_language = reader.get('language', reader.get('locale'))
                if not isinstance(value, dict) or value.get('id') != ident or source_language != language:
                    raise ValueError('Canonical reader path and payload identity differ')
                if not _current_metadata(value):
                    continue
                found.append({'collection': 'essential-hadith', 'language': language,
                              'id': ident, 'chapter': 1, 'lesson': int(path.stem),
                              'json': relative, 'discovery': 'canonical-numbered-reader'})
            except (OSError, ValueError, TypeError) as error:
                errors.append({'language': language, 'collection': 'hadith',
                               'path': relative, 'reason': str(error)})
        folder = root / 'materials/tadabbur' / language / 'extended'
        for path in sorted(folder.glob('*.json')):
            if not re.fullmatch(r'\d{3}', path.stem):
                continue
            relative = path.relative_to(root).as_posix()
            if relative in registered_paths:
                continue
            try:
                value = json.loads(path.read_bytes())
                surah = int(path.stem)
                source_language = value.get('language', value.get('locale')) if isinstance(value, dict) else None
                source_language = {'es-ES': 'es'}.get(source_language, source_language)
                if (not isinstance(value, dict) or value.get('surah', surah) != surah
                        or source_language != language
                        or value.get('mode', 'extended') != 'extended' or not 1 <= surah <= 114):
                    raise ValueError('Canonical Quran reader path and payload identity differ')
                if not _current_metadata(value):
                    continue
                found.append({'collection': 'tadabbur', 'language': language,
                              'id': f'{surah}:extended', 'surah': surah, 'mode': 'extended',
                              'json': relative, 'discovery': 'canonical-extended-reader'})
            except (OSError, ValueError, TypeError) as error:
                errors.append({'language': language, 'collection': 'tadabbur-extended',
                               'path': relative, 'reason': str(error)})
        path = root / 'materials/tadabbur/fatiha-extended' / language / 'reading.json'
        if path.is_file() and path.relative_to(root).as_posix() not in registered_paths:
            relative = path.relative_to(root).as_posix()
            try:
                value = json.loads(path.read_bytes())
                if not isinstance(value, dict) or value.get('language') != language:
                    raise ValueError('Fatiha reader path and payload language differ')
                if _current_metadata(value):
                    found.append({'collection': 'tadabbur', 'language': language,
                                  'id': 'fatiha-extended', 'surah': 1, 'mode': 'extended',
                                  'json': relative, 'discovery': 'canonical-fatiha-reader'})
            except (OSError, ValueError, TypeError) as error:
                errors.append({'language': language, 'collection': 'tadabbur-extended',
                               'path': relative, 'reason': str(error)})
    # These two indices explicitly identify the current edition, unlike older
    # standalone article translations and older Seerah lecture summaries.
    for relative, collection, field in (
        ('materials/articles/prepared-ar/index.json', 'articles', 'articles'),
        ('materials/seerah/new-adult/ar/index.json', 'seerah', 'chapters'),
    ):
        if 'ar' not in languages:
            continue
        path = root / relative
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_bytes())
            for row in value[field]:
                if not _current_metadata(row):
                    continue
                source = row.get('path') if collection == 'articles' else row.get('readingPath')
                ident = row['id'] if collection == 'articles' else f"new-seerah{row['number']:03d}"
                if not isinstance(source, str) or not source:
                    raise ValueError('Current source index lacks its reader path')
                reader = (path.parent / source).resolve()
                if not reader.is_relative_to(root) or not reader.is_file():
                    raise ValueError('Current source index reader is missing or outside the repository')
                if reader.relative_to(root).as_posix() in registered_paths:
                    continue
                candidate = {'collection': collection, 'language': 'ar', 'id': ident,
                             'markdown': reader.relative_to(root).as_posix(),
                             'number': row.get('number', row.get('position')),
                             'discovery': 'current-edition-source-index'}
                if collection == 'seerah':
                    candidate.update(edition='new-adult', chapter=row['number'])
                found.append(candidate)
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append({'language': 'ar', 'collection': collection,
                           'path': relative, 'reason': str(error)})
    return {'readers': found, 'errors': errors}


def _number(collection, ident, row=None):
    row = row or {}
    if collection == 'hadith':
        match = re.fullmatch(r'essential-(\d+)-(\d+)', str(ident))
        if match:
            return tuple(map(int, match.groups()))
        return None
    elif collection == 'tadabbur-extended':
        if ident == 'fatiha-extended':
            return 1
        match = re.fullmatch(r'(\d+):extended', str(ident))
        if match:
            return int(match[1])
    elif collection == 'seerah':
        match = re.fullmatch(r'new-seerah(\d+)', str(ident))
        if match:
            return int(match[1])
    number = row.get('number', row.get('position', row.get('chapter')))
    return number if type(number) is int and number > 0 else None


def _sort_key(collection, ident, rows):
    number = _number(collection, ident, rows.get(ident))
    if isinstance(number, tuple):
        return (0, *number, str(ident))
    return (0, number, 0, str(ident)) if number is not None else (1, 0, 0, str(ident))


def _review_incomplete(root, language, collection, rows):
    """Recognize the exact documented French first-lesson review conflict.

    This narrow diagnostic uses the migration's explicit exclusion and checks
    both current source bytes. It neither changes catalogue status nor infers
    review failure from the absence of an adapter or publication binding.
    """
    ident = 'essential-01-001'
    relative = 'books/source-projections/current-hadith-first.json'
    path = root / relative
    if (language, collection) != ('fr', 'hadith') or ident not in rows or not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_bytes())
        if (data.get('schema') != 'iman-current-hadith-first-source-bindings-v1'
                or data.get('sourceApprovalCreated') is not False):
            raise ValueError('Unrecognized first-lesson review-exclusion evidence')
        matches = [row for row in data.get('excludedCurrentRows', [])
                   if (row.get('language'), row.get('id')) == (language, ident)]
        if not matches:
            return {}, []
        if len(matches) != 1 or any((row.get('language'), row.get('id')) == (language, ident)
                                    for row in data.get('records', [])):
            raise ValueError('Conflicting first-lesson review-exclusion identities')
        record = matches[0]
        bindings = record.get('sourceFiles', [])
        expected = set(_paths(rows[ident]).values())
        if (len(bindings) != len(expected) or {item.get('path') for item in bindings} != expected
                or record.get('sourceApprovalCreated') is not False):
            raise ValueError('First-lesson review exclusion omits exact current sources')
        sources = {item['path']: pinned(root, item) for item in bindings}
        payload = json.loads(sources[rows[ident]['json']])
        status = payload.get('reading', {}).get('reviewStatus')
        if (not isinstance(status, str) or status != record.get('reviewStatus')
                or 'PENDING_ACTUAL_DISTINCT_FINAL' not in status):
            raise ValueError('Current first-lesson pending-review evidence changed')
        return {ident: {'projection': relative, 'sourceFiles': bindings,
                        'reviewStatus': status, 'reason': record['reason']}}, []
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return {}, [{'language': language, 'collection': collection,
                     'path': relative, 'stage': 'review-exclusion', 'reason': str(error)}]


def scope_coverage(root, language, collection, catalog, declaration=None, *,
                   selected=None, book=None, discovered=None, selection_error=None):
    """Return source/catalog/selected/download identities without changing any.

    ``book`` must be the actual remotely verified download when this report is
    used on public surfaces. Selected new inputs are never labelled included.
    """
    root = Path(root).resolve()
    material = [row for row in catalog.get('entries', [])
                if (row.get('language'), MAP.get(row.get('collection'))) == (language, collection)]
    current = [row for row in material if available(row)]
    legacy = []
    if collection == 'seerah':
        current, legacy = current_seerah_rows(current, declaration)
    elif declaration and declaration.get('edition'):
        current = [row for row in current if row.get('edition') == declaration['edition']]
    if selected is None:
        selected = []
        if declaration and not selection_error:
            try:
                selected, _ = select(root, catalog, declaration)
            except (OSError, ValueError, KeyError, TypeError) as error:
                selection_error = str(error)
    catalog_rows = {str(row['id']): row for row in current}
    all_registered = {str(row['id']): row for row in material}
    candidates = dict(catalog_rows)
    discovery = discovered if discovered is not None else discover_readers(root, [language], catalog)
    competing = []
    for row in discovery['readers']:
        if _identity(row)[:2] != (language, collection):
            continue
        ident = str(row['id'])
        if ident in all_registered:
            # Withdrawn/older identities and competing paths do not become new
            # eligible material just because their old files are still present.
            if ident in catalog_rows and any(catalog_rows[ident].get(k) != v
                                             for k, v in _paths(row).items()):
                competing.append({'id': ident, 'sourcePaths': _paths(row),
                                  'reason': 'different-from-current-catalogue-source'})
            continue
        candidates[ident] = row
    selected_ids = {str(row['id']) for row in selected}
    included_ids = [str(unit['id']) for unit in (book or {}).get('units', [])]
    if len(set(included_ids)) != len(included_ids):
        raise ValueError('Duplicate included download identity')
    incomplete, review_errors = _review_incomplete(root, language, collection, catalog_rows)
    if set(incomplete) & (selected_ids | set(included_ids)):
        review_errors.append({'stage': 'review-exclusion',
                              'reason': 'Selected or included lesson conflicts with exact pending-review evidence'})
    missing = []
    for ident in sorted(set(candidates) - set(included_ids), key=lambda value: _sort_key(collection, value, candidates)):
        reason = ('review-incomplete' if ident in incomplete else
                  'source-not-catalogued' if ident not in catalog_rows else
                  'awaiting-book-release' if ident in selected_ids else 'source-not-bound')
        item = {'id': ident, 'reason': reason, 'sourcePaths': _paths(candidates[ident]),
                'number': _number(collection, ident, candidates[ident])}
        if ident in incomplete:
            item['reviewEvidence'] = incomplete[ident]
        missing.append(item)
    absent = []
    if collection == 'hadith':
        chapters = defaultdict(set)
        for ident in set(candidates) | set(included_ids):
            position = _number(collection, ident)
            if isinstance(position, tuple):
                chapters[position[0]].add(position[1])
        for chapter, lessons in sorted(chapters.items()):
            for lesson in range(1, max(lessons) + 1):
                ident = f'essential-{chapter:02d}-{lesson:03d}'
                if lesson not in lessons:
                    absent.append({'id': ident, 'chapter': chapter, 'lesson': lesson,
                                   'reason': 'current-source-not-installed'})
    errors = [entry for entry in discovery['errors']
              if (entry['language'], entry['collection']) == (language, collection)]
    errors += review_errors
    if selection_error:
        errors.append({'reason': selection_error, 'stage': 'source-selection'})
    result = {'schema': SCHEMA, 'language': language, 'collection': collection,
              'sourceIds': sorted(candidates, key=lambda value: _sort_key(collection, value, candidates)),
              'catalogIds': sorted(catalog_rows, key=lambda value: _sort_key(collection, value, candidates)),
              'selectedIds': sorted(selected_ids, key=lambda value: _sort_key(collection, value, candidates)),
              'includedIds': included_ids,
              'includedNumbers': {ident: _number(collection, ident, catalog_rows.get(ident)) for ident in included_ids},
              'missingCurrent': missing, 'absentEarlierLessons': absent,
              'unregisteredSourceIds': [row['id'] for row in missing if row['reason'] == 'source-not-catalogued'],
              'competingSources': competing, 'legacyExcluded': len(legacy),
              'otherEditionSources': [{'id': str(row['id']), 'edition': row.get('edition'),
                  'sourcePaths': _paths(row),
                  'reason': 'outside-the-explicitly-selected-current-edition',
                  'catalogClaims': {field: row[field] for field in
                      ('status', 'publicationStatus', 'translationStatus', 'current', 'archived')
                      if field in row}} for row in legacy],
              'errors': errors, 'sourceApprovalCreated': False,
              'sourceQualificationsChanged': False}
    result['state'] = ('check-pending' if errors else 'partial' if missing or absent else
                       'listed-materials-included' if included_ids else 'no-current-download')
    return result


def download_coverage(root, ready, *, conf=None):
    """Audit public metadata independently of immutable release fingerprints."""
    root = Path(root).resolve()
    conf = conf or _read(root / 'books/config.json', {})
    catalog = _read(root / 'materials/catalog.json', {'entries': []})
    declarations = _read(root / 'books/reviewed-books.json', {'books': []})
    declared = {}
    for row in declarations.get('books', []):
        identity = row['language'], row['collection']
        if identity in declared:
            raise ValueError('Duplicate book source scope in coverage inventory')
        declared[identity] = row
    discovery = discover_readers(root, conf.get('languages', {}), catalog)
    result = {}
    for language, collection in ready:
        key = language, collection
        item = scope_coverage(root, language, collection, catalog, declared.get(key),
                              book=ready[key], discovered=discovery)
        item['presentation'] = presentation(item, conf['languages'][language])
        result[key] = item
    return result


def _ranges(values):
    values = sorted(set(values))
    groups = []
    for value in values:
        if groups and value == groups[-1][-1] + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    return ', '.join(str(group[0]) if len(group) == 1 else f'{group[0]}–{group[-1]}' for group in groups)


def _number_summary(collection, identifiers, numbers):
    values = [numbers.get(ident) for ident in identifiers]
    if not values or any(value is None for value in values):
        return ''
    if collection == 'hadith':
        groups = defaultdict(list)
        for chapter, lesson in values:
            groups[chapter].append(lesson)
        if set(groups) == {1}:
            return _ranges(groups[1])
        return '; '.join(str(chapter) + ':' + _ranges(lessons) for chapter, lessons in sorted(groups.items()))
    return _ranges(values)


def presentation(coverage, language_config):
    """Native labels describe exact included numbers and distinct missing states."""
    language, collection = coverage['language'], coverage['collection']
    included, partial, unbound, pending, absent, error = COPY[language]
    noun = (locale(language)['surahLabel'] if collection == 'tadabbur-extended' else
            language_config.get('hadithLabel', language_config['titles'][collection]) if collection == 'hadith' else
            language_config['titles'][collection])
    numbers = coverage['includedNumbers']
    summary = _number_summary(collection, coverage['includedIds'], numbers)
    included_text = noun + ' ' + digits(summary, language) if summary else digits(len(coverage['includedIds']), language)
    result = {'includedLabel': included + ': ' + included_text,
              'statusLabel': partial if coverage['state'] == 'partial' else error if coverage['errors'] else '',
              'notes': [], 'unitLabels': {}}
    multi_chapter = collection == 'hadith' and len({value[0] for value in numbers.values() if value}) > 1
    for ident in coverage['includedIds']:
        value = numbers[ident]
        if value is None:
            continue
        label = (str(value[0]) + ':' + str(value[1]) if multi_chapter or value[0] != 1 else str(value[1])) if collection == 'hadith' else str(value)
        result['unitLabels'][ident] = noun + ' ' + digits(label, language)
    for reason, label in [('source-not-catalogued', unbound), ('source-not-bound', unbound), ('awaiting-book-release', pending)]:
        rows = [row for row in coverage['missingCurrent'] if row['reason'] == reason]
        if not rows:
            continue
        text = _number_summary(collection, [row['id'] for row in rows], {row['id']: row['number'] for row in rows})
        detail = noun + ' ' + digits(text, language) if text else digits(len(rows), language)
        result['notes'].append(label + ': ' + detail)
    incomplete = [row for row in coverage['missingCurrent'] if row['reason'] == 'review-incomplete']
    if incomplete:
        if language != 'fr':
            raise ValueError('No native label for undocumented incomplete-review diagnostic')
        text = _number_summary(collection, [row['id'] for row in incomplete], {row['id']: row['number'] for row in incomplete})
        result['notes'].append('Vérification finale incomplète : ' + noun + ' ' + digits(text, language))
    if coverage['absentEarlierLessons']:
        rows = coverage['absentEarlierLessons']
        text = _number_summary(collection, [row['id'] for row in rows], {row['id']: (row['chapter'], row['lesson']) for row in rows})
        result['notes'].append(absent + ': ' + noun + ' ' + digits(text, language))
    for text in [result['includedLabel'], result['statusLabel'], *result['notes'], *result['unitLabels'].values()]:
        native_text(text, language)
    return result
