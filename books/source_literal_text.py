"""Keep exact source-bound publisher names and quotation locators unchanged.

Ordinary furniture/native-language validation remains strict. An exception is
valid only for an exact slice of an immutable reviewed reading field, identified
by source and review-inventory hashes. No global word or website allowlist is
introduced and no new prose receives an exception.
"""
import hashlib
import json
import re
from functools import lru_cache
from bibliography import native_text
from reviewed_hadith_sources import SCHEMA as REVIEW_SCHEMA, source_pointer, validate_record

SCHEMA = 'iman-source-literal-text-v1'
APPROVED_READER_SCHEMA = 'iman-approved-reader-source-v1'
_VALIDATED_CURRENT = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize_lines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _stamp(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)


@lru_cache(maxsize=256)
def _snapshot(path, stamp):
    """Cache immutable bytes, invalidating on replacement or in-place edits."""
    raw = path.read_bytes()
    if _stamp(path) != stamp:
        raise ValueError('Source changed during literal validation: ' + str(path))
    return raw, sha(raw)


@lru_cache(maxsize=256)
def _parsed(path, stamp):
    return json.loads(_snapshot(path, stamp)[0])


def _read(root, relative, expected=None, *, parsed=False):
    from book_edition_scope import inside
    path = inside(root, relative)
    stamp = _stamp(path)
    raw, digest = _snapshot(path, stamp)
    if expected is not None and (not re.fullmatch('[a-f0-9]{64}', expected)
                                 or digest != expected):
        raise ValueError('Changed edition review/source input: ' + relative)
    return (_parsed(path, stamp) if parsed else raw), digest


def _pinned_json(root, binding):
    return _read(root, binding.get('path', ''), binding.get('sha256', ''), parsed=True)[0]


def _validate_current(root, module, record, row, catalog, catalog_digest):
    # All bound bytes are rechecked before a cached validation can be reused.
    # Parent directory stamps also invalidate newly added/removed companion
    # files; translation-status is an input to the first-Hadith qualification.
    from book_edition_scope import inside, canonical
    dependencies = []
    directories = set()
    for binding in record.get('sourceFiles', []) + record.get('sourceConditions', []):
        _, digest = _read(root, binding.get('path', ''), binding.get('sha256', ''))
        dependencies.append((binding['path'], digest))
        directories.add(inside(root, binding['path']).parent)
    status = root / 'materials/translation-status.json'
    if status.is_file():
        dependencies.append(('materials/translation-status.json',
                             _read(root, 'materials/translation-status.json')[1]))
    cache_key = (str(root.resolve()), module.__name__, sha(canonical(record)),
                 catalog_digest, tuple(dependencies),
                 tuple((str(path), _stamp(path)) for path in sorted(directories)))
    if cache_key not in _VALIDATED_CURRENT:
        module.validate_record(root, record, row, catalog)
        if len(_VALIDATED_CURRENT) >= 512:
            _VALIDATED_CURRENT.clear()
        _VALIDATED_CURRENT[cache_key] = True


def proof_for(record, inventory_binding, source_binding, start, end, text):
    return {'schema': SCHEMA, 'language': record['language'], 'materialId': record['id'],
            'source': dict(source_binding), 'inventory': dict(inventory_binding),
            'pointer': list(record['readingPointer']), 'start': start, 'end': end,
            'textSHA256': sha(text.encode('utf8'))}


def proof_list(value):
    """Normalize optional single/multiple exact-source proofs for a note."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, dict) for item in value):
        raise ValueError('Invalid exact source proof list')
    return list(value)


def check_bound_text(root, text, unit, proofs, *, exact=False):
    proofs = proof_list(proofs)
    for proof in proofs:
        if (proof.get('materialId') != unit.get('id')
                or proof.get('source') not in unit.get('inputBindings', [])
                or proof.get('inventory') not in unit.get('inputBindings', [])):
            raise ValueError('Source literal is not bound to this complete reader unit')
        inventory = _pinned_json(root, proof['inventory'])
        if inventory.get('schema') == APPROVED_READER_SCHEMA:
            material = inventory.get('material', {})
            if (material != {'collection': unit.get('collection'),
                             'language': unit.get('language'), 'id': unit.get('id')}
                    or unit.get('catalogBindings') != [material]
                    or proof.get('collection') != unit.get('collection')
                    or inventory.get('approval', {}).get('readerTextSHA256')
                       != unit.get('readerTextSHA256')
                    or proof.get('readerTextSHA256') != unit.get('readerTextSHA256')):
                raise ValueError('Approved source literal belongs to another complete reader')
    return check_text(root, text, unit['language'], proofs, exact=exact)


def _approved_reader_literal(root, proof, inventory):
    """Preserve an exact approved TXT slice in a new Article or Seerah reader.

    This is a literal-text proof, not source approval. The normal publisher must
    still validate its separate whole-material envelope and exact reader unit.
    The factual import record binds existing review/acceptance receipt digests;
    those private receipts are not copied into the public source repository.
    Initial intake runs before a new catalogue entry or edition exists, so this
    branch binds the complete reader identity rather than requiring an older
    catalogue row. Later indexing retains all normal publisher approval gates.
    """
    material = inventory.get('material', {})
    approval = inventory.get('approval', {})
    expected = {'collection': proof.get('collection'),
                'language': proof.get('language'), 'id': proof.get('materialId')}
    if (material != expected or material.get('collection') not in {'articles', 'seerah'}
            or not material.get('id') or not material.get('language')
            or inventory.get('current') is not True
            or approval.get('decision') != 'approved'
            or approval.get('wholeMaterial') is not True
            or not approval.get('approvalId') or not approval.get('reviewer')):
        raise ValueError('Literal text lacks its exact whole-reader source acceptance')
    for name in ('semanticReviewSHA256', 'sourceAcceptanceSHA256', 'readerTextSHA256'):
        if not re.fullmatch('[a-f0-9]{64}', approval.get(name, '')):
            raise ValueError('Approved source literal lacks a bound ' + name)
    if proof.get('readerTextSHA256') != approval['readerTextSHA256']:
        raise ValueError('Approved source literal reader fingerprint differs')
    source = inventory.get('readingSource')
    if (not isinstance(source, dict) or proof.get('source') != source
            or proof.get('pointer') != []
            or not source.get('path', '').endswith('.txt')
            or source not in inventory.get('sourceBindings', [])):
        raise ValueError('Literal source is outside the accepted complete TXT reader')
    raw, _ = _read(root, source.get('path', ''), source.get('sha256', ''))
    value = normalize_lines(raw.decode('utf8'))
    return _slice_literal(value, proof)


def check_link_associations(root, unit, block):
    """A valid source URL may only be attached to its original source label."""
    paragraph = block['sourceLiteralProof']
    check_bound_text(root, block['text'], unit, paragraph, exact=True)
    inventory = _pinned_json(root, paragraph['inventory'])
    from current_source_registry import format_for
    spec = format_for(inventory.get('schema'))
    if spec is None or not hasattr(spec[0], 'literal_links'):
        raise ValueError('Source inventory does not authorize credit link associations')
    records = [record for record in inventory.get('records', [])
               if (record.get('collection'), record.get('language'), record.get('id'))
               == (spec[1], unit['language'], unit['id'])]
    if len(records) != 1:
        raise ValueError('Source link association lacks a unique current reader')
    def identity(proof):
        return {name: proof.get(name) for name in ('source', 'pointer', 'textSHA256')}
    actual = {'paragraph': identity(paragraph), 'links': [
        {**{name: link.get(name) for name in ('start', 'end', 'url')},
         **identity(link.get('sourceLiteralProof', {}))}
        for link in block['hyperlinks']]}
    if actual not in spec[0].literal_links(records[0]):
        raise ValueError('Source credit link label or destination association changed')


def _current_literal(root, proof, inventory, spec):
    """Validate new formats without broadening legacy proof authority."""
    from book_edition_scope import POLICY, available, pinned
    module, catalogue_collection, book_collection = spec
    declarations = _read(root, 'books/reviewed-books.json', parsed=True)[0]
    scopes = [row for row in declarations.get('books', [])
              if (row.get('language'), row.get('collection'))
              == (proof.get('language'), book_collection)]
    if (declarations.get('schema') != 'iman-reviewed-books-v1' or len(scopes) != 1
            or scopes[0].get('state') != 'reviewed-current'
            or scopes[0].get('automaticBuild') is not True
            or scopes[0].get('scopePolicy') != POLICY
            or proof.get('inventory') not in scopes[0].get('sourceReviewBindings', [])):
        raise ValueError('Source literal lacks an active current reviewed source inventory binding')
    matches = [record for record in inventory.get('records', [])
               if (record.get('collection'), record.get('language'), str(record.get('id')))
               == (catalogue_collection, proof.get('language'), str(proof.get('materialId')))]
    if len(matches) != 1:
        raise ValueError('Literal text has no unique current reviewed source record')
    record = matches[0]
    catalog, catalog_digest = _read(root, 'materials/catalog.json', parsed=True)
    rows = [row for row in catalog.get('entries', [])
            if (row.get('collection'), row.get('language'), str(row.get('id')))
            == (catalogue_collection, proof.get('language'), str(proof.get('materialId')))]
    if len(rows) != 1 or not available(rows[0]):
        raise ValueError('Literal text has no unique available current source record')
    _validate_current(root, module, record, rows[0], catalog, catalog_digest)
    allowed = module.literal_sources(record)
    if {'source': proof.get('source'), 'pointer': proof.get('pointer')} not in allowed:
        raise ValueError('Literal exception is not on an exact reviewed reading field')
    if hasattr(module, 'literal_value'):
        value = module.literal_value(root, record, proof)
    else:
        value = source_pointer(_pinned_json(root, proof['source']), proof['pointer'])
    return _slice_literal(value, proof)


def _slice_literal(value, proof):
    if not isinstance(value, str):
        raise ValueError('Literal source field is not text')
    value = normalize_lines(value)
    start, end = proof.get('start'), proof.get('end')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(value):
        raise ValueError('Invalid source-literal bounds')
    text = value[start:end]
    if sha(text.encode('utf8')) != proof.get('textSHA256'):
        raise ValueError('Source-literal text changed')
    return text


def exact_literal(root, proof):
    from book_edition_scope import POLICY, available, pinned
    if root is None:
        raise ValueError('Source-literal validation requires the exact repository inputs')
    if proof.get('schema') != SCHEMA:
        raise ValueError('Unsupported source-literal proof')
    inventory = _pinned_json(root, proof.get('inventory', {}))
    if inventory.get('schema') == APPROVED_READER_SCHEMA:
        return _approved_reader_literal(root, proof, inventory)
    from current_source_registry import format_for
    spec = format_for(inventory.get('schema'))
    if spec is not None:
        return _current_literal(root, proof, inventory, spec)
    declarations = json.loads((root / 'books/reviewed-books.json').read_bytes())
    scopes = [row for row in declarations.get('books', [])
              if (row.get('language'), row.get('collection')) == (proof.get('language'), 'hadith')]
    if (declarations.get('schema') != 'iman-reviewed-books-v1' or len(scopes) != 1
            or proof.get('language') == 'ar'
            or scopes[0].get('state') != 'reviewed-current'
            or scopes[0].get('automaticBuild') is not True
            or scopes[0].get('scopePolicy') != POLICY
            or proof.get('inventory') not in scopes[0].get('sourceReviewBindings', [])):
        raise ValueError('Source literal lacks an active translated-Hadith review inventory binding')
    if inventory.get('schema') != REVIEW_SCHEMA:
        raise ValueError('Literal text has no bound reviewed translation inventory')
    matches = [row for row in inventory.get('records', [])
               if (row.get('language'), row.get('id')) == (proof.get('language'), proof.get('materialId'))]
    if len(matches) != 1:
        raise ValueError('Literal text has no unique reviewed source record')
    record = matches[0]
    catalog = json.loads((root / 'materials/catalog.json').read_bytes())
    rows = [row for row in catalog.get('entries', [])
            if (row.get('collection'), row.get('language'), row.get('id'))
            == ('essential-hadith', proof.get('language'), proof.get('materialId'))]
    if len(rows) != 1 or not available(rows[0]):
        raise ValueError('Literal text has no unique available current source record')
    validate_record(root, record, rows[0], catalog)
    if proof.get('source') not in record.get('sourceFiles', []) or proof.get('source', {}).get('path') != record.get('catalogEntry', {}).get('json'):
        raise ValueError('Literal source is outside the reviewed reader')
    if proof.get('pointer') != record.get('readingPointer'):
        raise ValueError('Literal exception is not on the exact reviewed reading field')
    value = source_pointer(json.loads(pinned(root, proof['source'])), proof['pointer'])
    return _slice_literal(value, proof)


def check_text(root, text, language, proofs=(), *, exact=False):
    if not isinstance(proofs, (list, tuple)):
        raise ValueError('Invalid source-literal proof list')
    remaining = text
    for proof in proofs:
        if proof.get('language') != language:
            raise ValueError('Source literal belongs to another language')
        literal = exact_literal(root, proof)
        if exact and literal != text:
            raise ValueError('Source-literal proof does not cover this exact paragraph')
        if literal not in remaining:
            raise ValueError('Bound source literal is missing or duplicated in the proof list')
        remaining = remaining.replace(literal, '', 1)
    if exact and len(proofs) != 1:
        raise ValueError('An exact source paragraph needs one literal proof')
    native_text(remaining, language)
    return text
