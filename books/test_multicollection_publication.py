"""Exercise real multi-book packages with tiny, explicitly synthetic fixtures.

These tests make no network requests and create no publication or Word-layout
approvals. The toy font and two-page PDFs test package integrity, not typography.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import posixpath
import re
import tempfile
import unittest
import zipfile

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.shared import Inches
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from lxml import etree
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, NameObject

from download_page import REPO, inventory, publish_bundles, write_catalog
from download_tables import COLLECTIONS, COPY, release_url, verified_books
from font_integrity import restore
from published_library import sha
from reader_xml import body_text


ROOT = Path(__file__).resolve().parents[1]
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'w': W}


def q(name):
    return '{' + W + '}' + name


def package(file):
    with zipfile.ZipFile(file) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def xml_bytes(node):
    return etree.tostring(node, xml_declaration=True, encoding='UTF-8', standalone=True)


def fixture_font(path):
    """A valid small TTF avoids downloads or dependencies on installed book assets."""
    font = FontBuilder(1000, isTTF=True)
    glyphs = ['.notdef', 'space', 'alef']
    font.setupGlyphOrder(glyphs)
    font.setupCharacterMap({32: 'space', 0x0627: 'alef'})
    shapes = {}
    for glyph in glyphs:
        pen = TTGlyphPen(None)
        if glyph == 'alef':
            pen.moveTo((200, 0))
            pen.lineTo((300, 0))
            pen.lineTo((300, 700))
            pen.lineTo((200, 700))
            pen.closePath()
        shapes[glyph] = pen.glyph()
    font.setupGlyf(shapes)
    font.setupHorizontalMetrics({glyph: (600, 0) for glyph in glyphs})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    font.setupNameTable({'familyName': 'Book Package Fixture', 'styleName': 'Regular',
                        'uniqueFontIdentifier': 'BookPackageFixture', 'fullName': 'Book Package Fixture',
                        'psName': 'BookPackageFixture', 'version': 'Version 1.0'})
    font.setupPost()
    font.setupMaxp()
    font.save(path)


def field(paragraph, instruction, cached):
    for name, value in [('fldChar', 'begin'), ('instrText', instruction), ('fldChar', 'separate')]:
        node = etree.SubElement(etree.SubElement(paragraph._p, q('r')), q(name))
        if name == 'instrText':
            node.text = value
        else:
            node.set(q('fldCharType'), value)
    paragraph.add_run(cached)
    etree.SubElement(etree.SubElement(paragraph._p, q('r')), q('fldChar'), {q('fldCharType'): 'end'})


def make_word(path, title, color, audio_url, conf, root):
    document = Document()
    document.add_paragraph('غلاف ' + title)
    png = BytesIO()
    Image.new('RGB', (12, 12), color).save(png, format='PNG')
    png.seek(0)
    document.add_picture(png, width=Inches(.25))
    section = document.add_section(WD_SECTION_START.NEW_PAGE)
    etree.SubElement(section._sectPr, q('pgNumType'), {q('start'): '2'})
    section.footer.is_linked_to_previous = False
    footer = section.footer.paragraphs[0]
    footer.add_run('تذييل ' + title)
    field(footer, ' PAGE ', '٢')
    contents = document.add_paragraph()
    field(contents, ' TOC \\o "1-2" \\h ', 'المحتويات ' + title)
    link = etree.SubElement(contents._p, q('hyperlink'), {q('anchor'): '_TocShared'})
    etree.SubElement(etree.SubElement(link, q('r')), q('t')).text = 'انتقل إلى الفصل'
    heading = document.add_paragraph(title, style='Heading 1')
    heading._p.insert(1, etree.Element(q('bookmarkStart'), {q('id'): '1', q('name'): '_TocShared'}))
    heading._p.append(etree.Element(q('bookmarkEnd'), {q('id'): '1'}))
    paragraph = document.add_paragraph('نص تجريبي محفوظ: ' + title)
    etree.SubElement(paragraph.add_run()._r, q('footnoteReference'), {q('id'): '1'})
    rid = document.part.relate_to(audio_url, R + '/hyperlink', is_external=True)
    link = etree.SubElement(document.add_paragraph()._p, q('hyperlink'), {'{' + R + '}id': rid})
    etree.SubElement(etree.SubElement(link, q('r')), q('t')).text = 'الاستماع'
    document.add_paragraph('نهاية ' + title)
    document.save(path)

    parts = package(path)
    notes = etree.Element(q('footnotes'), nsmap={'w': W})
    note = etree.SubElement(notes, q('footnote'), {q('id'): '1'})
    etree.SubElement(etree.SubElement(etree.SubElement(note, q('p')), q('r')), q('t')).text = 'مرجع ' + title
    parts['word/footnotes.xml'] = xml_bytes(notes)
    relationships = etree.fromstring(parts['word/_rels/document.xml.rels'])
    etree.SubElement(relationships, '{' + P + '}Relationship',
                     {'Id': 'fixtureFootnotes', 'Type': R + '/footnotes', 'Target': 'footnotes.xml'})
    parts['word/_rels/document.xml.rels'] = xml_bytes(relationships)
    types = etree.fromstring(parts['[Content_Types].xml'])
    etree.SubElement(types, '{' + C + '}Override', {'PartName': '/word/footnotes.xml',
                    'ContentType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'})
    parts['[Content_Types].xml'] = xml_bytes(types)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in parts.items():
            archive.writestr(name, raw)
    restore(path, conf, 'ar', root)


def make_pdf(path, collection, audio_url):
    writer = PdfWriter()
    for page_number in range(2):
        page = writer.add_blank_page(width=144, height=216)
        stream = DecodedStreamObject()
        stream.set_data(('% synthetic ' + collection + ' page ' + str(page_number) +
                         '\nq 0.2 0.5 0.4 rg 20 20 50 50 re f Q\n').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_annotation(0, Link(rect=(10, 10, 60, 30), target_page_index=1))
    writer.add_annotation(1, Link(rect=(10, 10, 60, 30), url=audio_url))
    writer.add_outline_item('Fixture chapter', 1)
    writer.write(path)


class ReleaseFixture:
    """Only the GitHub boundary is simulated; file construction and merging are real."""
    def __init__(self):
        self.releases = {}
        self.commands = []

    def __call__(self, arguments, root):
        args = [str(value) for value in arguments]
        self.commands.append(args)
        if args[:3] == ['gh', 'release', 'create']:
            assert args[3] not in self.releases
            self.releases[args[3]] = {'tag_name': args[3], 'draft': True, 'prerelease': False, 'assets': []}
        elif args[:3] == ['gh', 'release', 'upload']:
            tag, file = args[3], Path(args[4])
            self.releases[tag]['assets'].append({'name': file.name, 'size': file.stat().st_size,
                'state': 'uploaded', 'digest': 'sha256:' + sha(file.read_bytes()),
                'browser_download_url': release_url(REPO, tag, file.name)})
        elif args[:3] == ['gh', 'release', 'edit']:
            self.releases[args[3]]['draft'] = False
        elif args[:2] == ['gh', 'api']:
            if '/releases?per_page=' in args[2]:
                return json.dumps(list(self.releases.values()))
            release = self.releases[args[2].rsplit('/', 1)[-1]]
            if release['draft']:
                raise RuntimeError('Drafts are not resolved by the public tag endpoint')
            return json.dumps(release)
        else:
            raise AssertionError('Unexpected external command: ' + repr(args))
        return ''


class MultipleCollectionPublication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'out'
        self.out.mkdir()
        (self.root / 'books').mkdir()
        self.conf = json.loads((ROOT / 'books/config.json').read_text(encoding='utf8'))
        font = self.root / 'books/fixture.ttf'
        fixture_font(font)
        definition = {'family': 'Book Package Fixture',
                      'files': {style: 'books/fixture.ttf' for style in ['Regular', 'Bold']},
                      'sha256': {style: sha(font.read_bytes()) for style in ['Regular', 'Bold']}}
        self.conf['fonts'] = {'Fixture': definition, 'Arabic': definition, 'Latin': definition}
        for settings in self.conf['languages'].values():
            settings['font'] = 'Fixture'
        (self.root / 'books/config.json').write_text(json.dumps(self.conf, ensure_ascii=False), encoding='utf8')
        (self.root / 'books/merge_public_books.py').write_bytes((ROOT / 'books/merge_public_books.py').read_bytes())
        (self.root / 'README.md').write_text('# Synthetic test library\n\nKeep this introduction.\n', encoding='utf8')
        self.templates = {}
        for collection, color in zip(COLLECTIONS, ['red', 'green', 'blue', 'purple']):
            file = self.root / (collection + '.docx')
            audio = 'https://example.test/audio/' + collection
            make_word(file, self.conf['languages']['ar']['titles'][collection], color, audio, self.conf, self.root)
            make_pdf(file.with_suffix('.pdf'), collection, audio)
            self.templates[collection] = (file.read_bytes(), file.with_suffix('.pdf').read_bytes())
        self.remote = ReleaseFixture()

    def ready_book(self, language, collection):
        folder = self.out / (language + '-' + collection)
        folder.mkdir(exist_ok=True)
        name = f'Iman_Companion_{language}_{collection}.docx'
        word, pdf = self.templates[collection]
        (folder / name).write_bytes(word)
        (folder / Path(name).with_suffix('.pdf')).write_bytes(pdf)
        title = self.conf['languages'][language]['titles'][collection]
        return {'language': language, 'collection': collection, 'collectionLabel': title,
                'file': name, 'sha256': sha(word), 'pdfSha256': sha(pdf), 'pages': 2,
                'exportVerified': True, 'previewOnly': False, 'hadithEdition': 'new-extended',
                'units': [{'id': collection + '-fixture', 'title': title}],
                'download': release_url(REPO, 'fixture-original', name),
                'pdfDownload': release_url(REPO, 'fixture-original', Path(name).with_suffix('.pdf').name)}

    def publish(self, ready, tag):
        links, errors = publish_bundles(self.root, self.out, ready, 'c' * 40, REPO, tag, self.remote)
        self.assertEqual(errors, [])
        return links, write_catalog(self.root, self.out, ready, links)

    def assert_merged_contents(self, collections):
        folder = self.out / 'public-bundles/ar'
        parts = package(folder / 'Iman_Companion_ar_all-books.docx')
        body = etree.fromstring(parts['word/document.xml']).find(q('body'))
        source_parts = [package(self.root / (collection + '.docx')) for collection in collections]
        self.assertEqual(body_text(body), ''.join(body_text(etree.fromstring(source['word/document.xml']).find(q('body')))
                                                for source in source_parts))
        notes = {note.get(q('id')): ''.join(note.itertext()) for note in etree.fromstring(parts['word/footnotes.xml'])}
        references = [node.get(q('id')) for node in body.iter(q('footnoteReference'))]
        self.assertEqual(len(references), len(set(references)))
        self.assertEqual([notes[ident] for ident in references],
                         ['مرجع ' + self.conf['languages']['ar']['titles'][collection] for collection in collections])
        names = [node.get(q('name')) for node in body.iter(q('bookmarkStart'))]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 2 * len(collections))
        self.assertTrue(all(link.get(q('anchor')) in names for link in body.iter(q('hyperlink')) if link.get(q('anchor'))))
        toc = [node.text for node in body.iter(q('instrText')) if 'TOC' in (node.text or '')]
        self.assertEqual([re.search(r'\\b\s+(\S+)', text).group(1) for text in toc],
                         [f'm{number}_BookScope' for number in range(1, len(collections) + 1)])
        relationships = {node.get('Id'): node for node in etree.fromstring(parts['word/_rels/document.xml.rels'])}
        links = [relationships[node.get('{' + R + '}id')].get('Target') for node in body.iter(q('hyperlink'))
                 if node.get('{' + R + '}id')]
        self.assertEqual(links, ['https://example.test/audio/' + collection for collection in collections])
        sections = list(body.iter(q('sectPr')))
        self.assertEqual(len(sections), 2 * len(collections))
        self.assertEqual([section.find(q('pgNumType')).get(q('start')) for section in sections],
                         ['1', '2'] * len(collections))
        for section, collection in zip(sections[1::2], collections):
            reference = section.find(q('footerReference'))
            target = relationships[reference.get('{' + R + '}id')].get('Target')
            footer = etree.fromstring(parts[posixpath.normpath(posixpath.join('word', target))])
            self.assertEqual(body_text(footer), 'تذييل ' + self.conf['languages']['ar']['titles'][collection] + '٢')
        image_tag = '{http://schemas.openxmlformats.org/drawingml/2006/main}blip'
        image_hashes = []
        for node in body.iter(image_tag):
            rel = relationships[node.get('{' + R + '}embed')]
            image_hashes.append(sha(parts[posixpath.normpath(posixpath.join('word', rel.get('Target')))]))
        expected_images = [sha(raw) for source in source_parts for name, raw in source.items() if name.startswith('word/media/')]
        self.assertEqual(image_hashes, expected_images)

        merged = PdfReader(folder / 'Iman_Companion_ar_all-books.pdf')
        originals = [PdfReader(self.root / (collection + '.pdf')) for collection in collections]
        self.assertEqual([page.get_contents().get_data() for page in merged.pages],
                         [page.get_contents().get_data() for reader in originals for page in reader.pages])
        for number, collection in enumerate(collections):
            destination = merged.pages[2 * number]['/Annots'][0].get_object()['/Dest']
            self.assertEqual(merged.get_page_number(destination[0].get_object()), 2 * number + 1)
            audio = merged.pages[2 * number + 1]['/Annots'][0].get_object()['/A']['/URI']
            self.assertEqual(audio, 'https://example.test/audio/' + collection)
        top_level = [item for item in merged.outline if not isinstance(item, list)]
        self.assertEqual([item.title for item in top_level],
                         [self.conf['languages']['ar']['titles'][collection] for collection in collections])
        self.assertEqual([merged.get_destination_page_number(item) for item in top_level], list(range(0, 2 * len(collections), 2)))

    def test_arabic_four_collections_preserve_twenty_quran_pairs_and_other_nineteen_bundles(self):
        ready = {(language, 'tadabbur-extended'): self.ready_book(language, 'tadabbur-extended') for language in COPY}
        original_books = deepcopy(ready)
        before_links, before_catalog = self.publish(ready, 'fixture-before')
        manifest = self.root / 'books/published-bundles.json'
        before_manifest = json.loads(manifest.read_text())
        before_pages = {language: (self.root / f'books/downloads/{language}/README.md').read_bytes() for language in COPY}
        original_release = deepcopy(self.remote.releases['fixture-before-bundles'])
        self.remote.commands.clear()
        for collection in COLLECTIONS[1:]:
            ready[('ar', collection)] = self.ready_book('ar', collection)
        links, catalog = self.publish(ready, 'fixture-expanded')
        after_manifest = json.loads(manifest.read_text())
        self.assertEqual([book['collection'] for book in catalog['languages']['ar']['books']], COLLECTIONS)
        self.assertEqual(links['ar']['parts'], 4)
        self.assertEqual(sum(len(row['books']) for row in catalog['languages'].values()), 23)
        for language in COPY:
            self.assertEqual(ready[(language, 'tadabbur-extended')], original_books[(language, 'tadabbur-extended')])
            self.assertEqual(catalog['languages'][language]['books'][0], before_catalog['languages'][language]['books'][0])
            if language != 'ar':
                self.assertEqual(links[language], before_links[language])
                self.assertEqual(after_manifest['languages'][language], before_manifest['languages'][language])
                self.assertEqual(catalog['languages'][language], before_catalog['languages'][language])
                self.assertEqual((self.root / f'books/downloads/{language}/README.md').read_bytes(), before_pages[language])
        self.assertEqual(self.remote.releases['fixture-before-bundles'], original_release)
        uploaded = {Path(command[4]).name for command in self.remote.commands if command[:3] == ['gh', 'release', 'upload']}
        self.assertEqual(uploaded, {f'Iman_Companion_ar_all-books.{extension}' for extension in ['docx', 'pdf', 'zip']})
        expected = {f'Iman_Companion_ar_{collection}.{extension}': self.templates[collection][index]
                    for collection in COLLECTIONS for index, extension in enumerate(['docx', 'pdf'])}
        with zipfile.ZipFile(self.out / 'public-bundles/ar/Iman_Companion_ar_all-books.zip') as archive:
            self.assertEqual(set(archive.namelist()), set(expected))
            for name, raw in expected.items():
                self.assertEqual(archive.read(name), raw)
        table = (self.root / 'README.md').read_text(encoding='utf8')
        arabic_row = next(line for line in table.splitlines() if line.startswith('|') and '?lang=ar)' in line)
        for collection in COLLECTIONS:
            for extension in ['docx', 'pdf']:
                self.assertIn(f'Iman_Companion_ar_{collection}.{extension}', arabic_row)
        self.assertIn('Keep this introduction.', table)
        self.assert_merged_contents(COLLECTIONS)

    def test_prepared_and_preview_candidates_never_enter_catalogue_table_or_bundle(self):
        books = [self.ready_book('ar', collection) for collection in COLLECTIONS]
        books[1].update(exportVerified=False, preparationVerified=True)
        books[2].update(previewOnly=True)
        staged = self.root / 'staged'
        staged.mkdir()
        for book in books:
            for extension in ['docx', 'pdf']:
                name = Path(book['file']).with_suffix('.' + extension)
                (staged / name).write_bytes((self.out / ('ar-' + book['collection']) / name).read_bytes())
        (self.root / 'books/prepared-library.json').write_text(json.dumps({
            'schema': 'iman-book-preparation-queue-v1',
            'entries': [{'state': 'prepared-awaiting-release-qc', 'releaseVerified': False,
                         'candidate': {'book': books[1]}}]}), encoding='utf8')
        ready = verified_books({'previewOnly': False, 'books': books}, staged, REPO, 'fixture-original')
        self.assertEqual(set(ready), {('ar', 'tadabbur-extended'), ('ar', 'articles')})
        links, catalog = self.publish(ready, 'fixture-eligible')
        self.assertEqual(links['ar']['parts'], 2)
        self.assertEqual([book['collection'] for book in catalog['languages']['ar']['books']], ['tadabbur-extended', 'articles'])
        with zipfile.ZipFile(self.out / 'public-bundles/ar/Iman_Companion_ar_all-books.zip') as archive:
            self.assertEqual(set(archive.namelist()), {f'Iman_Companion_ar_{collection}.{extension}'
                             for collection in ['tadabbur-extended', 'articles'] for extension in ['docx', 'pdf']})
        public = (self.root / 'docs/books/catalog.json').read_text() + (self.root / 'README.md').read_text()
        public += (self.root / 'books/downloads/ar/README.md').read_text()
        for book in books[1:3]:
            self.assertNotIn(book['download'], public)
            self.assertNotIn(book['pdfDownload'], public)
            with self.assertRaises(ValueError):
                inventory({**ready, ('ar', book['collection']): book}, 'ar')
        self.assert_merged_contents(['tadabbur-extended', 'articles'])


if __name__ == '__main__':
    unittest.main()
