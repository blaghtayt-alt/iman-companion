"""Regression cases for combining verified books with isolated Word styles."""
from io import BytesIO
from pathlib import Path
import hashlib,tempfile,unittest,zipfile

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import RGBColor
from lxml import etree
from PIL import Image

from merge_public_books import C,P,R,W,body_text,merge_docx,q,serialized,xml


def read_parts(path):
    with zipfile.ZipFile(path)as archive:return {name:archive.read(name)for name in archive.namelist()}


def write_parts(path,parts):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as archive:
        for name,raw in parts.items():archive.writestr(name,raw)


def add_field(paragraph,instructions,result='1'):
    begin=etree.SubElement(paragraph.add_run()._r,q('fldChar'));begin.set(q('fldCharType'),'begin')
    for instruction in instructions:etree.SubElement(paragraph.add_run()._r,q('instrText')).text=instruction
    separate=etree.SubElement(paragraph.add_run()._r,q('fldChar'));separate.set(q('fldCharType'),'separate')
    paragraph.add_run(result)
    end=etree.SubElement(paragraph.add_run()._r,q('fldChar'));end.set(q('fldCharType'),'end')


def fixture(path,label,*,color='123456',normal=None,unused=False):
    document=Document()
    if normal:document.styles['Normal'].font.color.rgb=RGBColor.from_string(normal)
    paragraph_style=document.styles.add_style('Shared Heading',WD_STYLE_TYPE.PARAGRAPH)
    paragraph_style.font.color.rgb=RGBColor.from_string(color)
    character_style=document.styles.add_style('Shared Emphasis',WD_STYLE_TYPE.CHARACTER)
    character_style.font.color.rgb=RGBColor.from_string(color)
    derived=document.styles.add_style('Dependent Heading',WD_STYLE_TYPE.PARAGRAPH)
    derived.base_style=paragraph_style
    derived.next_paragraph_style=paragraph_style
    etree.SubElement(paragraph_style._element,q('link'),{q('val'):character_style.style_id})
    etree.SubElement(character_style._element,q('link'),{q('val'):paragraph_style.style_id})
    table_style=document.styles.add_style('Shared Table',WD_STYLE_TYPE.TABLE)
    table_style.font.color.rgb=RGBColor.from_string(color)
    if unused:
        style=document.styles.add_style('Endnote Characters',WD_STYLE_TYPE.CHARACTER)
        style.font.superscript=(label=='first')
    document.add_paragraph('Cover '+label)
    section=document.add_section(WD_SECTION_START.NEW_PAGE)
    section.header.is_linked_to_previous=False
    section.footer.is_linked_to_previous=False
    section.header.paragraphs[0].add_run('Header '+label).style=character_style
    footer=section.footer.paragraphs[0]
    footer.add_run('Footer '+label+' ').style=character_style
    add_field(footer,[' PAGE '])
    add_field(footer,[' STYLEREF "Dependent Heading" ']if label=='first'else[' STY','LEREF "Dependent ','Heading" '],result='Cached '+label)
    body=document.add_paragraph('Chapter '+label,style=derived)
    body.add_run(' emphasized '+label).style=character_style
    body.add_run(' plain '+label)
    note=etree.SubElement(body.add_run()._r,q('footnoteReference'));note.set(q('id'),'1')
    document.add_paragraph('Unstyled '+label)
    table=document.add_table(rows=1,cols=1);table.style=table_style
    table.cell(0,0).text='Table '+label
    picture=BytesIO();Image.new('RGB',(8,8),'white').save(picture,'PNG');picture.seek(0)
    document.add_picture(picture)
    contents=document.add_paragraph()
    add_field(contents,[' TOC \\t "Shared Heading,1,Dependent Heading,2" '],result='Contents '+label)
    document.add_paragraph('End '+label)
    document.save(path)
    parts=read_parts(path)
    notes=etree.Element(q('footnotes'),nsmap={'w':W})
    note=etree.SubElement(notes,q('footnote'),{q('id'):'1'})
    paragraph=etree.SubElement(note,q('p'))
    prop=etree.SubElement(paragraph,q('pPr'));etree.SubElement(prop,q('pStyle'),{q('val'):derived.style_id})
    run=etree.SubElement(paragraph,q('r'))
    prop=etree.SubElement(run,q('rPr'));etree.SubElement(prop,q('rStyle'),{q('val'):character_style.style_id})
    etree.SubElement(run,q('t')).text='Source note '+label
    parts['word/footnotes.xml']=serialized(notes)
    relationships=xml(parts['word/_rels/document.xml.rels'])
    etree.SubElement(relationships,'{'+P+'}Relationship',Id='fixture-notes',Type=R+'/footnotes',Target='footnotes.xml')
    parts['word/_rels/document.xml.rels']=serialized(relationships)
    types=xml(parts['[Content_Types].xml'])
    etree.SubElement(types,'{'+C+'}Override',PartName='/word/footnotes.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml')
    parts['[Content_Types].xml']=serialized(types)
    write_parts(path,parts)
    return parts


class MergePublicBooks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.first=self.root/'first.docx';self.second=self.root/'second.docx';self.out=self.root/'merged.docx'

    def tearDown(self):self.temp.cleanup()

    def test_word_normalization_of_unused_endnote_style_no_longer_blocks_bundle(self):
        originals=[fixture(self.first,'first',unused=True),fixture(self.second,'second',unused=True)]
        hashes=[hashlib.sha256(p.read_bytes()).hexdigest()for p in(self.first,self.second)]
        report=merge_docx([self.first,self.second],self.out)
        self.assertEqual(report['isolatedStyles'][0]['styles'].keys(),{'EndnoteCharacters'})
        parts=read_parts(self.out);styles=xml(parts['word/styles.xml'])
        ids={n.get(q('styleId')):n for n in styles.findall(q('style'))}
        mapping=report['isolatedStyles'][0]['styles'];remapped=ids[mapping['EndnoteCharacters']]
        self.assertEqual(ids['EndnoteCharacters'].find('.//'+q('vertAlign')).get(q('val')),'superscript')
        self.assertIsNone(remapped.find('.//'+q('vertAlign')))
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest()for p in(self.first,self.second)])
        expected=''.join(body_text(xml(p['word/document.xml']).find(q('body')))for p in originals)
        self.assertEqual(body_text(xml(parts['word/document.xml']).find(q('body'))),expected)
        self.assertEqual(report['sourceFootnotesExactlyPreserved'],2)
        self.assertEqual(report['imagesAndAudioLinksVerified'],2)

    def test_used_style_dependency_tree_is_preserved_in_body_notes_headers_and_tables(self):
        fixture(self.first,'first',color='FF0000');fixture(self.second,'second',color='0000FF')
        report=merge_docx([self.first,self.second],self.out)
        mapping=report['isolatedStyles'][0]['styles']
        self.assertEqual(set(mapping),{'SharedHeading','SharedEmphasis','DependentHeading','SharedTable'})
        parts=read_parts(self.out);styles={n.get(q('styleId')):n for n in xml(parts['word/styles.xml']).findall(q('style'))}
        self.assertEqual(styles['SharedHeading'].find('.//'+q('color')).get(q('val')),'FF0000')
        self.assertEqual(styles[mapping['SharedHeading']].find('.//'+q('color')).get(q('val')),'0000FF')
        derived=styles[mapping['DependentHeading']]
        for tag in('basedOn','next'):self.assertEqual(derived.find(q(tag)).get(q('val')),mapping['SharedHeading'])
        self.assertEqual(styles[mapping['SharedHeading']].find(q('link')).get(q('val')),mapping['SharedEmphasis'])
        self.assertEqual(styles[mapping['SharedEmphasis']].find(q('link')).get(q('val')),mapping['SharedHeading'])
        roots={name:xml(raw)for name,raw in parts.items()if name.startswith('word/')and name.endswith('.xml')}
        for text,tag,expected in [('Chapter second','pStyle','DependentHeading'),('Source note second','pStyle','DependentHeading'),('Header second','rStyle','SharedEmphasis'),('Footer second','rStyle','SharedEmphasis')]:
            paragraphs=[p for root in roots.values()for p in root.iter(q('p'))if any((n.text or'').startswith(text)for n in p.iter(q('t')))]
            self.assertEqual(len(paragraphs),1,text)
            self.assertIn(mapping[expected],[n.get(q('val'))for n in paragraphs[0].iter(q(tag))])
        tables=list(roots['word/document.xml'].iter(q('tbl')))
        self.assertEqual(tables[0].find('.//'+q('tblStyle')).get(q('val')),'SharedTable')
        self.assertEqual(tables[1].find('.//'+q('tblStyle')).get(q('val')),mapping['SharedTable'])
        # Field PAGE, footer links and independent section starts remain intact.
        second_footer=roots['word/m2-footer1.xml']
        instructions=''.join(n.text or''for n in second_footer.iter(q('instrText')))
        self.assertIn(' PAGE ',instructions)
        self.assertIn('STYLEREF "'+styles[mapping['DependentHeading']].find(q('name')).get(q('val'))+'"',instructions)
        doc=roots['word/document.xml'];relationships={n.get('Id'):n for n in xml(parts['word/_rels/document.xml.rels'])}
        targets=[relationships[n.get('{'+R+'}id')].get('Target')for n in doc.iter(q('footerReference'))]
        self.assertIn('footer1.xml',targets);self.assertIn('m2-footer1.xml',targets)
        self.assertEqual(len([n for n in doc.iter(q('pgNumType'))if n.get(q('start'))=='1']),2)
        self.assertEqual([n.get(q('id'))for n in doc.iter(q('footnoteReference'))],['1','2'])
        toc=[n.text for n in doc.iter(q('instrText'))if(n.text or'').lstrip().startswith('TOC')][1]
        self.assertIn(styles[mapping['SharedHeading']].find(q('name')).get(q('val'))+',1',toc)
        self.assertIn('\\b m2_BookScope',toc)

    def test_conflicting_default_style_is_explicit_only_for_the_appended_book(self):
        fixture(self.first,'first',normal='FF0000');fixture(self.second,'second',normal='0000FF')
        # Exercise implicit paragraph defaults without python-docx's unused list
        # template. A conflict touching shared numbering stays unsupported and
        # has a separate fail-closed regression test.
        for path in(self.first,self.second):
            parts=read_parts(path);parts.pop('word/numbering.xml',None)
            for name in('word/styles.xml','word/stylesWithEffects.xml'):
                if name not in parts:continue
                styles=xml(parts[name])
                for number in list(styles.iter(q('numPr'))):number.getparent().remove(number)
                parts[name]=serialized(styles)
            relationships=xml(parts['word/_rels/document.xml.rels'])
            for rel in list(relationships):
                if rel.get('Type')==R+'/numbering':relationships.remove(rel)
            parts['word/_rels/document.xml.rels']=serialized(relationships)
            types=xml(parts['[Content_Types].xml'])
            for item in list(types):
                if item.get('PartName')=='/word/numbering.xml':types.remove(item)
            parts['[Content_Types].xml']=serialized(types);write_parts(path,parts)
        report=merge_docx([self.first,self.second],self.out)
        mapping=report['isolatedStyles'][0]['styles'];self.assertIn('Normal',mapping)
        parts=read_parts(self.out);styles=xml(parts['word/styles.xml'])
        defaults=[n.get(q('styleId'))for n in styles.findall(q('style'))if n.get(q('type'))=='paragraph'and n.get(q('default'))in('1','true','on')]
        self.assertEqual(defaults,['Normal'])
        doc=xml(parts['word/document.xml'])
        first=next(p for p in doc.iter(q('p'))if body_text(p)=='Unstyled first')
        second=next(p for p in doc.iter(q('p'))if body_text(p)=='Unstyled second')
        self.assertIsNone(first.find('./'+q('pPr')+'/'+q('pStyle')))
        self.assertEqual(second.find('./'+q('pPr')+'/'+q('pStyle')).get(q('val')),mapping['Normal'])

    def test_ids_are_deterministic_and_each_later_book_gets_an_independent_scope(self):
        fixture(self.first,'first',color='FF0000');fixture(self.second,'second',color='0000FF')
        third=self.root/'third.docx';fixture(third,'third',color='00FF00')
        one=merge_docx([self.first,self.second,third],self.out)
        two=merge_docx([self.first,self.second,third],self.root/'again.docx')
        self.assertEqual(one['isolatedStyles'],two['isolatedStyles'])
        remaps=[row['styles']['SharedHeading']for row in one['isolatedStyles']]
        self.assertEqual(len(set(remaps)),2)
        styles=xml(read_parts(self.out)['word/styles.xml'])
        ids=[n.get(q('styleId'))for n in styles.findall(q('style'))]
        names=[n.get(q('val')).casefold()for n in styles.findall('./'+q('style')+'/'+q('name'))]
        self.assertEqual(len(ids),len(set(ids)));self.assertEqual(len(names),len(set(names)))

    def test_different_document_defaults_and_automatic_numbering_still_fail_closed(self):
        fixture(self.first,'first');parts=fixture(self.second,'second')
        modified=dict(parts);styles=xml(parts['word/styles.xml'])
        styles.find('./'+q('docDefaults')+'/'+q('rPrDefault')+'/'+q('rPr')+'/'+q('sz')).set(q('val'),'40')
        modified['word/styles.xml']=serialized(styles);write_parts(self.second,modified)
        with self.assertRaisesRegex(ValueError,'document style defaults'):merge_docx([self.first,self.second],self.out)
        modified=dict(parts);doc=xml(parts['word/document.xml']);paragraph=next(doc.iter(q('p')))
        prop=etree.SubElement(paragraph,q('pPr'));number=etree.SubElement(prop,q('numPr'));etree.SubElement(number,q('numId'),{q('val'):'1'})
        modified['word/document.xml']=serialized(doc);write_parts(self.second,modified)
        with self.assertRaisesRegex(ValueError,'automatic list numbering'):merge_docx([self.first,self.second],self.out)


if __name__=='__main__':unittest.main()
