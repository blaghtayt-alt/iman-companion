#!/usr/bin/env python3
"""Browse public source metadata with evidence-backed translation disclosures."""
import argparse
import hashlib
import json
import pathlib
import re
import sys
import unicodedata
import urllib.request

from provenance import Provenance, UNKNOWN_NOTICE, pointer

HERE = pathlib.Path(__file__).resolve().parent
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def load(path):
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold()
                   if not unicodedata.combining(c))


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def fetch_verified(file, member=None, expected_member_sha=None):
    # Fetch only pinned public repository locators, never an arbitrary URL.
    prefix = 'https://github.com/blaghtayt-alt/iman-companion/blob/'
    url = file['url']
    if not re.fullmatch(r'https://github[.]com/blaghtayt-alt/iman-companion/blob/[0-9a-f]{40}/materials/[A-Za-z0-9_./-]+', url) or '..' in url:
        raise ValueError('Unexpected public source origin or path')
    raw = 'https://raw.githubusercontent.com/blaghtayt-alt/iman-companion/' + url[len(prefix):]
    with urllib.request.urlopen(raw, timeout=40) as response:
        body = response.read(30000001)
    if len(body) > 30000000:
        raise ValueError('Source exceeds size limit')
    if hashlib.sha256(body).hexdigest() != file['sha256'] or len(body) != file['bytes']:
        raise ValueError('Pinned source hash or length mismatch')
    obj = json.loads(body)
    if member:
        entries = [entry for entry in obj['files'] if entry['name'] == member]
        if len(entries) != 1:
            raise ValueError('Source member not unique')
        text = entries[0]['text']
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != expected_member_sha:
            raise ValueError('Member hash mismatch')
        obj = json.loads(text)
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=pathlib.Path, default=HERE / 'INDEX.json')
    parser.add_argument('--provenance', type=pathlib.Path, default=HERE / 'TRANSLATION-PROVENANCE.json')
    sub = parser.add_subparsers(dest='action', required=True)
    search = sub.add_parser('search')
    search.add_argument('query', nargs='?', default='')
    search.add_argument('--kind', choices=['package', 'reading', 'source', 'reference', 'lesson', 'chapter', 'translation'])
    for name in ['language', 'chapter', 'collection', 'status', 'mode', 'content-kind']:
        search.add_argument('--' + name)
    search.add_argument('--surah', type=int)
    search.add_argument('--limit', type=int, default=20)
    search.add_argument('--translation-origin', choices=['ai', 'human'], help='Evidence-backed matching passages, not whole-lesson authorship.')
    resolve = sub.add_parser('resolve', help='Fetch a pinned source and resolve a JSON pointer with applicable translation disclosures.')
    resolve.add_argument('id')
    resolve.add_argument('--pointer', default=None, help='RFC 6901 pointer within the referenced JSON; defaults to the indexed object.')
    resolve.add_argument('--reading', action='store_true', help='Resolve the package or reading JSON rather than its source record.')
    args = parser.parse_args()
    pub = load(args.index)
    provenance = Provenance(args.provenance)  # Missing/malformed ledger is an error, not silent label stripping.
    datasets = [('package', pub['packages']), ('reading', pub['readingsOnly']),
                ('source', pub['sourceRecords']), ('reference', pub['quranCitationKeys']),
                ('chapter', pub['chapters']), ('lesson', pub['lessons']),
                ('translation', provenance.records)]
    notice = {'scope': provenance.data['classificationScope'], 'unknown': UNKNOWN_NOTICE,
              'independentProvenanceAudit': provenance.data['independentProvenanceAudit']}
    if args.action == 'search':
        found = []
        for kind, rows in datasets:
            if args.kind and args.kind != kind:
                continue
            for item in rows:
                disclosures = provenance.for_record(kind, item)
                text = norm(json.dumps({'record': item, 'translationDisclosures': disclosures}, ensure_ascii=False))
                if any(norm(term) not in text for term in args.query.split()):
                    continue
                if args.translation_origin and not any(d['translationOrigin'] == args.translation_origin for d in disclosures):
                    continue
                if args.language and norm(args.language) != norm(item.get('language', '')) and not any(norm(args.language) == norm(n.get('language', '')) for n in item.get('nativePublications', [])):
                    continue
                if args.chapter and norm(args.chapter) not in norm(item.get('chapterId', item.get('lessonId', item.get('id', '')))):
                    continue
                if args.collection and norm(args.collection) not in norm(item.get('sourceBook', '')) and norm(args.collection) not in norm(item.get('metadata', {})):
                    continue
                if args.status and norm(args.status) not in text:
                    continue
                if args.content_kind and item.get('contentKind') != args.content_kind:
                    continue
                if args.surah is not None and not any(o.get('surah') == args.surah for o in item.get('occurrences', [])):
                    continue
                if args.mode and not any(norm(o.get('mode', '')) == norm(args.mode) for o in item.get('occurrences', [])):
                    continue
                found.append({'kind': kind, 'record': item, 'translationDisclosures': disclosures})
        output({'count': len(found), 'shown': min(len(found), max(args.limit, 0)),
                'translationProvenance': notice, 'results': found[:max(args.limit, 0)]})
        return
    match = next(((kind, item) for kind, rows in datasets for item in rows if item['id'] == args.id), None)
    if not match:
        parser.error('ID not found in the public index or translation provenance ledger')
    kind, item = match
    loc = item.get('locator', {})
    member = expected = None
    if kind == 'translation':
        if args.pointer is not None or args.reading:
            parser.error('A translation ID resolves only its exact bound passage; use its package ID for other reading paths')
        file = item['reading']
        occurrence = item['occurrences'][0]
        ptr = occurrence['jsonPointer']
    elif kind == 'source' and not args.reading:
        file = loc.get('envelope', loc.get('file'))
        member, expected = loc.get('member'), loc.get('memberSha256')
        ptr = args.pointer if args.pointer is not None else loc.get('memberJsonPointer', loc.get('jsonPointer', ''))
    elif kind == 'package':
        file, ptr = item['locators']['reading'], args.pointer or ''
    elif kind == 'reading':
        file, ptr = item['reading'], args.pointer or ''
    elif kind == 'source' and args.reading:
        package = next((p for p in pub['packages'] if p['language'] == item['language'] and p['lessonId'] == item['lessonId']), None)
        if package is None:
            parser.error('No indexed reading for this source record')
        file, ptr = package['locators']['reading'], args.pointer or ''
    else:
        parser.error('This record does not have a supported resolvable JSON locator')
    value = pointer(fetch_verified(file, member, expected), ptr)
    disclosures = provenance.for_file(file, ptr, member)
    bounds = None
    if kind == 'translation':
        bounds = [occurrence['codepointStart'], occurrence['codepointEnd']]
        value = value[bounds[0]:bounds[1]]
        if value != item['translationText'] or hashlib.sha256(value.encode('utf-8')).hexdigest() != item['textSha256']:
            raise ValueError('Version-bound translation passage mismatch')
        disclosures = [provenance.disclosure(item)]
    output({'source': file['url'], 'verifiedSHA256': file['sha256'], 'member': member,
            'pointer': ptr, 'codepointBounds': bounds, 'value': value,
            'translationDisclosures': disclosures, 'translationProvenance': notice})


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        sys.exit('Error: ' + str(error))
