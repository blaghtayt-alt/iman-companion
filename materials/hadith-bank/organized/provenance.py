"""Version-bound translation attribution; never infer authorship from missing metadata."""
import hashlib
import json
import pathlib
import re

SCHEMA = 'hadith-translation-provenance-v1'
UNKNOWN_NOTICE = 'Unlisted passages are unclassified: no AI or human origin is asserted.'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def pointer(value, path):
    if path and not path.startswith('/'):
        raise ValueError('JSON pointer must be empty or begin with /')
    for part in path.split('/')[1:] if path else []:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def related_pointer(left, right):
    return (left == right or not left or not right or
            left.startswith(right + '/') or right.startswith(left + '/'))


def same_file(left, right):
    """Match path AND exact bytes, allowing identical bytes pinned at different commits."""
    def path(loc):
        url = loc.get('url', '')
        match = re.fullmatch(
            r'https://github[.]com/blaghtayt-alt/iman-companion/blob/[0-9a-f]{40}/(materials/[A-Za-z0-9_./-]+)', url)
        return match.group(1) if match and '..' not in match.group(1) else None
    return (path(left) is not None and path(left) == path(right) and
            left.get('sha256') == right.get('sha256') and
            left.get('bytes') == right.get('bytes'))


class Provenance:
    def __init__(self, path):
        with pathlib.Path(path).open(encoding='utf-8') as stream:
            self.data = json.load(stream)
        self.validate()
        self.records = self.data['records']

    def validate(self):
        if self.data.get('schema') != SCHEMA:
            raise ValueError('Unsupported translation provenance schema')
        if (self.data.get('defaultTranslationOrigin') != 'unknown' or
                self.data.get('defaultDisclosureLabel') is not None):
            raise ValueError('Unknown translation origin must not receive an AI/human label')
        seen = set()
        for row in self.data['records']:
            if row['id'] in seen:
                raise ValueError('Duplicate translation provenance ID')
            seen.add(row['id'])
            origin = row['translationOrigin']
            disclosure = row['disclosure']
            if origin not in ('ai', 'human', 'unknown'):
                raise ValueError('Unsupported translation origin')
            if origin == 'ai':
                if (row['aiTranslated'] is not True or not (row.get('translator') or {}).get('model') or
                        row.get('humanTranslator') is not None or
                        not disclosure.get('label', '').startswith('AI-translated')):
                    raise ValueError('AI attribution requires an actual model and explicit label')
            elif origin == 'human':
                if (row['aiTranslated'] is not False or not row.get('humanTranslator') or
                        row.get('translator') is not None or
                        row['humanTranslator'] not in disclosure.get('label', '')):
                    raise ValueError('Human attribution requires a named source translator')
            else:
                if any(row.get(k) is not None for k in ('aiTranslated', 'translator', 'humanTranslator')) or disclosure.get('label') is not None:
                    raise ValueError('Unknown origin must remain unlabelled')
            if origin != 'unknown' and not (disclosure.get('required') and disclosure.get('mustAccompanyText') and disclosure.get('displayOutsideQuotedText')):
                raise ValueError('Known-origin disclosure must travel with text, outside the quotation')
            if row['review']['status'] not in ('historical_recorded', 'conflicting_records', 'not_assessed'):
                raise ValueError('This ledger cannot claim a new review pass')
            if row['textSha256'] != digest(row['translationText'].encode('utf-8')):
                raise ValueError('Translation text hash mismatch')
            if not row['occurrences'] or not row['provenanceEvidence']:
                raise ValueError('An attribution needs an exact occurrence and provenance evidence')
            for loc in [row['reading'], row['sourceTextLocator']['file']] + [e['file'] for e in row['provenanceEvidence']]:
                if not same_file(loc, loc) or not re.fullmatch(r'[0-9a-f]{64}', loc['sha256']) or loc['bytes'] <= 0:
                    raise ValueError('Invalid version-bound file locator')
            for occurrence in row['occurrences']:
                if (not occurrence['jsonPointer'].startswith('/reading') or occurrence['codepointStart'] < 0 or
                        occurrence['codepointEnd'] - occurrence['codepointStart'] != len(row['translationText'])):
                    raise ValueError('Invalid exact translation span')

    @staticmethod
    def disclosure(row):
        return {key: row[key] for key in (
            'id', 'language', 'lessonId', 'fieldId', 'contentKind', 'translationOrigin', 'aiTranslated', 'humanTranslator',
            'translator', 'review', 'disclosure', 'textSha256', 'occurrences',
            'reading', 'sourceTextLocator', 'provenanceEvidence')}

    def for_file(self, file, ptr='', member=None):
        matches = []
        for row in self.records:
            if member is None and same_file(file, row['reading']):
                if any(related_pointer(ptr, occ['jsonPointer']) for occ in row['occurrences']):
                    matches.append(self.disclosure(row))
            else:
                source = row['sourceTextLocator']
                if (member == source.get('member') and same_file(file, source['file']) and
                        related_pointer(ptr, source['jsonPointer'])):
                    matches.append(self.disclosure(row))
        return matches

    def for_record(self, kind, item):
        if kind == 'translation':
            return [self.disclosure(item)]
        if kind == 'package':
            return self.for_file(item['locators']['reading'])
        if kind == 'reading':
            return self.for_file(item['reading'])
        if kind == 'source':
            loc = item.get('locator', {})
            file = loc.get('envelope', loc.get('file'))
            if file:
                return self.for_file(file, loc.get('memberJsonPointer', loc.get('jsonPointer', '')), loc.get('member'))
        return []

    def verify_local_sources(self, root):
        """Audit every recorded hash, exact quote/span and evidence pointer against local files."""
        root = pathlib.Path(root).resolve()
        def read(loc, member=None, member_sha=None):
            path = (root / loc['path']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Source path escaped repository')
            raw = path.read_bytes()
            if digest(raw) != loc['sha256'] or len(raw) != loc['bytes']:
                raise ValueError('Source hash/length mismatch: ' + loc['path'])
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            if blob != loc['gitBlob']:
                raise ValueError('Git blob mismatch: ' + loc['path'])
            obj = json.loads(raw) if loc['path'].endswith('.json') else raw.decode('utf-8')
            if member:
                parts = [part for part in obj['files'] if part['name'] == member]
                if len(parts) != 1 or digest(parts[0]['text'].encode('utf-8')) != member_sha:
                    raise ValueError('Source envelope member mismatch')
                obj = json.loads(parts[0]['text'])
            return obj
        for row in self.records:
            reading = read(row['reading'])
            for occ in row['occurrences']:
                text = pointer(reading, occ['jsonPointer'])[occ['codepointStart']:occ['codepointEnd']]
                if text != row['translationText']:
                    raise ValueError('Reading span mismatch: ' + row['id'])
            source = row['sourceTextLocator']
            text = pointer(read(source['file'], source.get('member'), source.get('memberSha256')), source['jsonPointer'])
            if text != row['translationText']:
                raise ValueError('Source quotation mismatch: ' + row['id'])
            for evidence in row['provenanceEvidence']:
                obj = read(evidence['file'], evidence.get('member'), evidence.get('memberSha256'))
                for ptr in evidence['jsonPointers']:
                    pointer(obj, ptr)
        return len(self.records)
