#!/usr/bin/env python3
"""Generate the narrowly scoped children Al-Ikhlas hold for the pinned public build.

Writes only to a new output directory. The source snapshot is read-only.
"""
import argparse
import hashlib
import json
from pathlib import Path

CONTRACT = Path(__file__).with_name('contract.json')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Root of the exact approved public snapshot')
    parser.add_argument('output', type=Path, help='New directory for five generated replacement files')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.absolute()
    require(source.is_dir() and not args.source.is_symlink(), 'Source must be a real directory')
    require(not output.exists() and not output.is_symlink(), 'Output must not already exist')
    require(not output.resolve().is_relative_to(source), 'Output must be outside the source snapshot')
    contract = json.loads(CONTRACT.read_bytes())
    rows = {x['path']: x for x in contract['files']}
    require(set(rows) == {'assets/learning/kids-lessons.js', 'runtime/scripts/content-audio-catalog1036.js', 'index.html', 'mobile.html', 'tablet.html'}, 'Unexpected contract paths')
    originals = {}
    for name, row in rows.items():
        p = source / name
        require(p.resolve().is_relative_to(source) and not p.is_symlink() and p.is_file(), 'Invalid source path: ' + name)
        raw = p.read_bytes()
        require(len(raw) == row['sourceBytes'] and digest(raw) == row['sourceSHA256'], 'Source changed: ' + name)
        originals[name] = raw
    lesson_name = 'assets/learning/kids-lessons.js'
    catalog_name = 'runtime/scripts/content-audio-catalog1036.js'
    s = originals[lesson_name].decode('utf8')
    prefix = 'window.IMAN_KIDS_LESSONS=['
    require(s.startswith(prefix), 'Unexpected lesson format')
    pos = len(prefix)
    decoder = json.JSONDecoder()
    spans = []
    while True:
        while s[pos].isspace():
            pos += 1
        if s[pos] == ']':
            break
        start = pos
        lesson, pos = decoder.raw_decode(s, pos)
        spans.append((start, pos, lesson))
        while s[pos].isspace():
            pos += 1
        if s[pos] == ',':
            pos += 1
        elif s[pos] == ']':
            break
        else:
            raise ValueError('Unexpected lesson delimiter')
    held = [(a, b, lesson) for a, b, lesson in spans if lesson.get('id') == contract['heldLessonId']]
    require(len(held) == 1 and held[0][2].get('status') == 'experimental', 'Expected experimental lesson not found')
    start, end, _ = held[0]
    require(s[end] == ',', 'Expected a following lesson')
    lesson_output = (s[:start] + s[end + 1:]).encode('utf8')
    before_lessons = json.loads(s[len('window.IMAN_KIDS_LESSONS='):].rstrip(';\r\n'))
    after_lessons = json.loads(lesson_output.decode('utf8')[len('window.IMAN_KIDS_LESSONS='):].rstrip(';\r\n'))
    require(after_lessons == [x for x in before_lessons if x.get('id') != contract['heldLessonId']], 'Other lessons changed')
    prefix = 'window.IMAN_APPROVED_CONTENT_AUDIO1036='
    text = originals[catalog_name].decode('utf8')
    require(text.startswith(prefix), 'Unexpected audio catalog format')
    catalog = json.loads(text[len(prefix):].rstrip(';\r\n'))
    require(catalog['sourceLessonsSHA256'] == digest(originals[lesson_name]), 'Audio catalog is not bound to this source')
    removed = [e for e in catalog['entries'] if e.get('id') == contract['heldAudioApprovalId']]
    require(len(removed) == contract['heldAudioApprovalCount'] and all(e.get('kind') == 'lesson' for e in removed), 'Unexpected approval entries')
    catalog['entries'] = [e for e in catalog['entries'] if e.get('id') != contract['heldAudioApprovalId']]
    catalog['sourceLessonsSHA256'] = digest(lesson_output)
    catalog_output = (prefix + json.dumps(catalog, ensure_ascii=False, separators=(',', ':')) + ';\n').encode('utf8')
    outputs = {lesson_name: lesson_output, catalog_name: catalog_output}
    for name in ('index.html', 'mobile.html', 'tablet.html'):
        text = originals[name].decode('utf8')
        for asset, before, after in ((lesson_name, originals[lesson_name], lesson_output), (catalog_name, originals[catalog_name], catalog_output)):
            old = asset + '?v=' + digest(before)[:12]
            new = asset + '?v=' + digest(after)[:12]
            require(text.count(old) == 1, 'Unexpected page reference: ' + name + ' ' + asset)
            text = text.replace(old, new)
        outputs[name] = text.encode('utf8')
    for name, raw in outputs.items():
        row = rows[name]
        require(len(raw) == row['targetBytes'] and digest(raw) == row['targetSHA256'], 'Generated file mismatch: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in outputs.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(raw)
    print(json.dumps({'status': 'generated-and-verified', 'files': len(outputs), 'heldLesson': contract['heldLessonId'], 'heldAudioApprovals': len(removed)}))

if __name__ == '__main__':
    main()
