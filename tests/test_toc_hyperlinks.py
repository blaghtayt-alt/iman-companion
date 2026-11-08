"""Fail-closed cache, link and source-target guards for native TOC regeneration."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'books'))
import toc_hyperlinks as toc


def element(parent, local_name, value=None, **attrs):
    node = ET.SubElement(parent, toc.tag(local_name), {toc.tag(k): v for k, v in attrs.items()})
    node.text = value
    return node


def document():
    root = ET.Element(toc.tag('document'))
    body = element(root, 'body')
    for i in range(2):
        p = element(body, 'p')
        properties = element(p, 'pPr')
        element(properties, 'pStyle', val='TOC1')
        element(element(properties, 'tabs'), 'tab', val='right', pos='9600')
        link = element(p, 'hyperlink', anchor='target' + str(i))
        element(element(link, 'r'), 't', 'Same heading')
        element(element(link, 'r'), 'tab')
        element(element(link, 'r'), 't', '٢')
    for i in range(2):
        p = element(body, 'p')
        element(element(p, 'pPr'), 'pStyle', val='Heading1')
        element(p, 'bookmarkStart', id=str(i), name='target' + str(i))
        element(element(p, 'r'), 'br')
        element(element(p, 'r'), 't', 'Same heading')
        element(p, 'bookmarkEnd', id=str(i))
    return root


def save(path, root):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', ET.tostring(root))


class CachedXML(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'book.docx'
        self.root = document()
        save(self.path, self.root)

    def read(self):
        save(self.path, self.root)
        return toc.read_cached_contents(self.path)

    def test_duplicate_titles_and_same_page_keep_distinct_source_bindings(self):
        rows = self.read()
        self.assertEqual([r['cache'] for r in rows], ['٢', '٢'])
        self.assertEqual([r['prefix'] for r in rows], ['Same heading\t'] * 2)
        self.assertEqual([r['target']['sourceParagraphOrdinal'] for r in rows], [0, 1])
        self.assertEqual([r['target']['text'] for r in rows], ['\nSame heading'] * 2)
        toc.verify_cached_contents(self.path, rows)

    def test_missing_duplicate_or_external_anchors_are_rejected(self):
        for mode in ('missing', 'duplicate', 'external'):
            with self.subTest(mode=mode):
                self.root = document()
                link = self.root.find('.//' + toc.tag('hyperlink'))
                if mode == 'missing':
                    link.set(toc.tag('anchor'), 'absent')
                elif mode == 'external':
                    link.set('{' + toc.R + '}id', 'rId7')
                else:
                    bookmark = self.root.find('.//' + toc.tag('bookmarkStart'))
                    self.root.find(toc.tag('body')).append(deepcopy(bookmark))
                with self.assertRaisesRegex(ValueError, 'target'):
                    self.read()

    def test_no_or_multiple_links_are_rejected(self):
        for count in (0, 2):
            self.root = document()
            paragraph = list(self.root.find(toc.tag('body')))[0]
            link = paragraph.find(toc.tag('hyperlink'))
            if count == 0: paragraph.remove(link)
            else: paragraph.append(deepcopy(link))
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'unique'):
                self.read()

    def test_non_numeric_or_missing_tail_is_rejected(self):
        for value in ('', 'page two', '0', '-2', ' 2'):
            self.root = document()
            link = self.root.find('.//' + toc.tag('hyperlink'))
            list(link.iter(toc.tag('t')))[-1].text = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'numeric cache'):
                self.read()

    def test_post_store_detects_swapped_same_title_same_page_links(self):
        original = self.read()
        links = list(self.root.iter(toc.tag('hyperlink')))
        links[0].set(toc.tag('anchor'), 'target1')
        links[1].set(toc.tag('anchor'), 'target0')
        save(self.path, self.root)
        with self.assertRaisesRegex(ValueError, 'source target changed'):
            toc.verify_cached_contents(self.path, original)

    def test_post_store_detects_moved_targets_between_identical_source_paragraphs(self):
        original = self.read()
        marks = list(self.root.iter(toc.tag('bookmarkStart')))
        marks[0].set(toc.tag('name'), 'target1')
        marks[1].set(toc.tag('name'), 'target0')
        save(self.path, self.root)
        with self.assertRaisesRegex(ValueError, 'source target changed'):
            toc.verify_cached_contents(self.path, original)

    def test_post_store_detects_changed_cache(self):
        original = self.read()
        link = self.root.find('.//' + toc.tag('hyperlink'))
        list(link.iter(toc.tag('t')))[-1].text = '٣'
        save(self.path, self.root)
        with self.assertRaises(ValueError):
            toc.verify_cached_contents(self.path, original)

    def test_genuinely_absent_toc_is_allowed(self):
        root = ET.Element(toc.tag('document'))
        element(element(element(root, 'body'), 'p'), 'r')
        save(self.path, root)
        self.assertEqual(toc.read_cached_contents(self.path), [])
        toc.verify_cached_contents(self.path, [])

    def test_missing_caches_for_simple_or_split_complex_toc_field_fail(self):
        for simple in (True, False):
            root = ET.Element(toc.tag('document'))
            p = element(element(root, 'body'), 'p')
            if simple:
                element(p, 'fldSimple', instr=' TOC \\o "1-2" ')
            else:
                element(element(p, 'r'), 'fldChar', fldCharType='begin')
                element(element(p, 'r'), 'instrText', ' TO')
                element(element(p, 'r'), 'instrText', 'C \\o "1-2" ')
                element(element(p, 'r'), 'fldChar', fldCharType='separate')
                element(element(p, 'r'), 'fldChar', fldCharType='end')
            save(self.path, root)
            with self.subTest(simple=simple), self.assertRaisesRegex(ValueError, 'entries are missing'):
                toc.read_cached_contents(self.path)


class FullCursor:
    def __init__(self, paragraph):
        self.paragraph = paragraph

    def getString(self):
        return self.paragraph.text

    def getPropertyValue(self, name):
        if name == 'HyperLinkURL':
            if self.paragraph.tail_link_lost: return ''
            if self.paragraph.mixed_full and self.paragraph.edits: return None
            return self.paragraph.url
        return self.paragraph.link_styles[name]

    def getPropertySetInfo(self):
        return SimpleNamespace(hasPropertyByName=lambda name: name in {
            'HyperLinkURL', *self.paragraph.link_styles})

    def gotoRange(self, end, select):
        assert end is self.paragraph and select

    def setPropertyValue(self, name, value):
        self.paragraph.whole_link_writes.append((name, value))
        if name == 'HyperLinkURL':
            self.paragraph.url = value
            self.paragraph.mixed_full = False
        else:
            self.paragraph.link_styles[name] = value


class TailCursor:
    def __init__(self, paragraph):
        self.paragraph = paragraph
        self.start = None

    def goLeft(self, units, select):
        assert select
        encoded = self.paragraph.text.encode('utf-16-le')
        self.start = len(encoded) - 2 * units
        return self.start >= 0

    def getString(self):
        return self.paragraph.text.encode('utf-16-le')[self.start:].decode('utf-16-le')

    def getPropertyValue(self, name):
        if name == 'HyperLinkURL':
            return '' if self.paragraph.tail_link_lost else self.paragraph.url
        return self.paragraph.link_styles[name]

    def setPropertyValue(self, name, value):
        self.paragraph.link_writes.append((name, value))
        if name == 'HyperLinkURL':
            self.paragraph.url = value
            self.paragraph.tail_link_lost = False
        else:
            self.paragraph.link_styles[name] = value

    def setString(self, value):
        if self.paragraph.fail_edit:
            raise RuntimeError('simulated edit failure')
        self.paragraph.edits.append(value)
        prefix = self.paragraph.text.encode('utf-16-le')[:self.start].decode('utf-16-le')
        self.paragraph.text = prefix + value + ('X' if self.paragraph.corrupt_edit else '')
        self.paragraph.tail_link_lost = True


class Paragraph:
    def __init__(self, text, url=''):
        self.text, self.url = text, url
        self.edits, self.fail_edit = [], False
        self.corrupt_edit, self.tail_link_lost = False, False
        self.mixed_full, self.bad_portion = False, False
        self.link_styles = {'VisitedCharStyleName': 'Original visited',
                            'UnvisitedCharStyleName': 'Original unvisited',
                            'HyperLinkName': 'Native name', 'HyperLinkTarget': 'Native target'}
        self.link_writes = []
        self.whole_link_writes = []

    def getString(self):
        return self.text

    def getEnd(self):
        return self

    def getStart(self):
        return ('start', self)

    def getText(self):
        return self

    def createTextCursorByRange(self, end):
        if end == ('start', self): return FullCursor(self)
        assert end is self
        return TailCursor(self)

    def createEnumeration(self):
        texts = [self.text] if not self.edits else list(self.text.rpartition('\t'))
        items = []
        for number, text in enumerate(texts):
            properties = {**self.link_styles, 'TextPortionType': 'Text',
                          'HyperLinkURL': '#unexpected' if self.bad_portion and self.edits and number == 0 else self.url}
            items.append(SimpleNamespace(getString=lambda text=text: text,
                getPropertySetInfo=lambda properties=properties: SimpleNamespace(
                    hasPropertyByName=lambda name: name in properties),
                getPropertyValue=lambda name, properties=properties: properties[name]))
        pending = list(items)
        return SimpleNamespace(hasMoreElements=lambda: bool(pending),
                               nextElement=lambda: pending.pop(0))


class Index:
    def __init__(self, rows):
        self.rows = rows
        self.IsProtected = True
        self.calls = 0
        self.on_update = lambda: None

    def getServiceName(self):
        return toc.CONTENT_INDEX

    def update(self):
        self.calls += 1
        self.on_update()


class NativeCacheGuards(unittest.TestCase):
    def setUp(self):
        self.paragraph = Paragraph('Same heading\t٨٨')
        self.index = Index([self.paragraph])
        self.indexes = [self.index]
        self.doc = SimpleNamespace(getDocumentIndexes=lambda: SimpleNamespace(
            getCount=lambda: len(self.indexes), getByIndex=lambda n: self.indexes[n]))
        self.saved = [{'prefix': 'Same heading\t', 'cache': '٨٨', 'anchor': 'target0'}]
        self.mock = patch.object(toc, '_native_rows',
            side_effect=lambda index: [(p, FullCursor(p)) for p in index.rows])
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def generated(self):
        self.paragraph.text = 'Same heading\t2'
        self.paragraph.url = '#target0'
        self.paragraph.tail_link_lost = False

    def test_exact_distinct_cache_survives_repeated_native_regeneration(self):
        self.index.on_update = self.generated
        for _ in range(2):
            self.paragraph.url = ''
            self.assertEqual(toc.refresh_cached_contents(self.doc, self.saved), 1)
            self.assertEqual(self.paragraph.text, 'Same heading\t٨٨')
            self.assertEqual(self.paragraph.url, '#target0')
            self.assertTrue(self.index.IsProtected)
        self.assertEqual(self.paragraph.edits, ['٨٨', '٨٨'])

    def test_already_intact_import_avoids_regeneration(self):
        self.paragraph.url = '#target0'
        self.assertEqual(toc.refresh_cached_contents(self.doc, self.saved), 0)
        self.assertEqual(self.index.calls, 0)

    def test_tail_replacement_restores_only_the_captured_native_link_properties(self):
        self.index.on_update = self.generated
        toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.paragraph.link_writes, [
            ('HyperLinkURL', '#target0'), ('VisitedCharStyleName', 'Original visited'),
            ('UnvisitedCharStyleName', 'Original unvisited'), ('HyperLinkName', 'Native name'),
            ('HyperLinkTarget', 'Native target')])
        self.assertEqual(self.paragraph.text, 'Same heading\t٨٨')

    def test_mixed_aggregate_with_exact_portion_urls_is_coalesced_to_original_properties(self):
        self.index.on_update = self.generated
        self.paragraph.mixed_full = True
        with patch('builtins.print') as printed:
            toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.paragraph.whole_link_writes, self.paragraph.link_writes)
        self.assertFalse(self.paragraph.mixed_full)
        self.assertEqual(json.loads(printed.call_args.args[0])['rows'], 1)

    def test_unexpected_portion_url_fails_before_whole_row_coalescing(self):
        self.index.on_update = self.generated
        self.paragraph.mixed_full = self.paragraph.bad_portion = True
        with self.assertRaisesRegex(ValueError, 'changed native link spans'):
            toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.paragraph.whole_link_writes, [])
        self.assertTrue(self.index.IsProtected)

    def test_changed_replacement_text_fails_before_reapplying_link_properties(self):
        self.index.on_update = self.generated
        self.paragraph.corrupt_edit = True
        with self.assertRaisesRegex(ValueError, 'exact generated numeric cache'):
            toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.paragraph.link_writes, [])
        self.assertTrue(self.index.IsProtected)

    def test_changed_imported_title_cache_or_target_fails_before_update(self):
        for text, url in (('Other\t٨٨', ''), ('Same heading\t٨٩', ''),
                          ('Same heading\t٨٨', '#wrong')):
            self.paragraph.text, self.paragraph.url = text, url
            with self.subTest(text=text, url=url), self.assertRaisesRegex(ValueError, 'Imported'):
                toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.index.calls, 0)

    def test_changed_regenerated_prefix_target_or_count_is_rejected_before_tail_edit(self):
        for mode in ('prefix', 'target', 'count'):
            self.paragraph.text, self.paragraph.url = 'Same heading\t٨٨', ''
            self.index.rows = [self.paragraph]
            def changed():
                self.generated()
                if mode == 'prefix': self.paragraph.text = 'Other\t2'
                if mode == 'target': self.paragraph.url = '#wrong'
                if mode == 'count': self.index.rows = []
            self.index.on_update = changed
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Regenerated'):
                toc.refresh_cached_contents(self.doc, self.saved)
        self.assertEqual(self.paragraph.edits, [])

    def test_protection_is_restored_when_native_tail_edit_raises(self):
        self.index.on_update = self.generated
        self.paragraph.fail_edit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            toc.refresh_cached_contents(self.doc, self.saved)
        self.assertTrue(self.index.IsProtected)

    def test_no_toc_requires_both_empty_snapshot_and_no_native_index(self):
        with self.assertRaisesRegex(ValueError, 'no validated cached rows'):
            toc.refresh_cached_contents(self.doc, [])
        self.indexes.clear()
        self.assertEqual(toc.refresh_cached_contents(self.doc, []), 0)
        with self.assertRaisesRegex(ValueError, 'row count'):
            toc.refresh_cached_contents(self.doc, self.saved)


if __name__ == '__main__':
    unittest.main()
