"""Explicit dispatch for installed current reviewed source formats.

The registry describes code, not approval. A format becomes eligible only when
its exact inventory is pinned by an active edition and its validator reconciles
the current catalogue, source bytes, review evidence and source revision.
"""
from importlib import import_module


FORMATS = {
    'iman-current-hadith-first-source-bindings-v1':
        ('current_hadith_first', 'essential-hadith', 'hadith'),
    'iman-current-reviewed-quran-source-bindings-v1':
        ('current_reviewed_quran', 'tadabbur', 'tadabbur-extended'),
    'iman-current-filipino-hadith-five-source-bindings-v1':
        ('current_hadith_five', 'essential-hadith', 'hadith'),
    'iman-current-reviewed-seerah-source-bindings-v1':
        ('current_reviewed_seerah', 'seerah', 'seerah'),
}


def format_for(schema):
    spec = FORMATS.get(schema)
    if spec is None:
        return None
    module, catalogue_collection, book_collection = spec
    return import_module(module), catalogue_collection, book_collection


def supplemental_records(root, declaration):
    """Return only records from the edition's explicitly pinned inventories."""
    import json
    from book_edition_scope import pinned
    result = []
    seen = set()
    for binding in declaration.get('sourceReviewBindings', []):
        data = json.loads(pinned(root, binding))
        spec = format_for(data.get('schema'))
        if spec is None:
            continue
        module, catalogue_collection, book_collection = spec
        if declaration.get('collection') != book_collection:
            raise ValueError('Current source inventory belongs to another book collection')
        for record in data.get('records', []):
            if record.get('language') != declaration.get('language'):
                continue
            identity = (catalogue_collection, record['language'], str(record['id']))
            if identity in seen:
                raise ValueError('Duplicate current reviewed source inventory identity')
            if record.get('collection') != catalogue_collection:
                raise ValueError('Current source inventory has a different catalogue collection')
            seen.add(identity)
            result.append((identity, record, binding, module))
    return result
