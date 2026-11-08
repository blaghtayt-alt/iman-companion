"""Keep exact source-bound publisher names and quotation locators unchanged.

Ordinary furniture/native-language validation remains strict. An exception is
valid only for an exact slice of an immutable reviewed reading field, identified
by source and review-inventory hashes. No global word or website allowlist is
introduced and no new prose receives an exception.
"""
import hashlib
import json
from bibliography import native_text
from reviewed_hadith_sources import SCHEMA as REVIEW_SCHEMA, source_pointer

SCHEMA = 'iman-source-literal-text-v1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize_lines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def proof_for(record, inventory_binding, source_binding, start, end, text):
    return {'schema': SCHEMA, 'language': record['language'], 'materialId': record['id'],
            'source': dict(source_binding), 'inventory': dict(inventory_binding),
            'pointer': list(record['readingPointer']), 'start': start, 'end': end,
            'textSHA256': sha(text.encode('utf8'))}


def exact_literal(root, proof):
    from book_edition_scope import pinned
    if root is None:
        raise ValueError('Source-literal validation requires the exact repository inputs')
    if proof.get('schema') != SCHEMA:
        raise ValueError('Unsupported source-literal proof')
    inventory = json.loads(pinned(root, proof.get('inventory', {})))
    if inventory.get('schema') != REVIEW_SCHEMA:
        raise ValueError('Literal text has no bound reviewed translation inventory')
    matches = [row for row in inventory.get('records', [])
               if (row.get('language'), row.get('id')) == (proof.get('language'), proof.get('materialId'))]
    if len(matches) != 1:
        raise ValueError('Literal text has no unique reviewed source record')
    record = matches[0]
    if proof.get('source') not in record.get('sourceFiles', []) or proof.get('source', {}).get('path') != record.get('catalogEntry', {}).get('json'):
        raise ValueError('Literal source is outside the reviewed reader')
    if proof.get('pointer') != record.get('readingPointer'):
        raise ValueError('Literal exception is not on the exact reviewed reading field')
    value = source_pointer(json.loads(pinned(root, proof['source'])), proof['pointer'])
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
