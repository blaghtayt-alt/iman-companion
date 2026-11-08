"""Preserve inactive list libraries without admitting active automatic lists."""
from copy import deepcopy
from pathlib import Path
import hashlib
import sys
import unittest

from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import merge_public_books as merge
import test_merge_public_books_styles as style_fixtures

q=merge.q


class MergeNumberingChecks(unittest.TestCase):
    def setUp(self):
        self.files=style_fixtures.MergeStyleChecks();self.files.setUp()
        self.output=self.files.output

    def tearDown(self):self.files.tearDown()

    def fixture(self,label,logical=False):
        file=self.files.fixture(label);parts=self.files.parts(file)
        styles=merge.xml(parts['word/styles.xml'])
        numbering=etree.Element(q('numbering'),nsmap={'w':merge.W})
        for ident,name,kind in [('1','ListBullet','bullet'),('2','ListNumber','decimal')]:
            definition=etree.SubElement(numbering,q('abstractNum'),{q('abstractNumId'):ident})
            for level in range(2):
                lvl=etree.SubElement(definition,q('lvl'),{q('ilvl'):str(level)})
                etree.SubElement(lvl,q('start'),{q('val'):'1'})
                etree.SubElement(lvl,q('numFmt'),{q('val'):kind})
                etree.SubElement(lvl,q('lvlText'),{q('val'):'•'if kind=='bullet'else'%'+str(level+1)+'.'})
                etree.SubElement(lvl,q('lvlJc'),{q('val'):'start'if logical else'left'})
                props=etree.SubElement(lvl,q('pPr'))
                etree.SubElement(props,q('ind'),{q('start'if logical else'left'):'720',q('hanging'):'360'})
            style=etree.SubElement(styles,q('style'),{q('type'):'paragraph',q('styleId'):name})
            etree.SubElement(style,q('name'),{q('val'):name})
            props=etree.SubElement(style,q('pPr'))
            etree.SubElement(etree.SubElement(props,q('numPr')),q('numId'),{q('val'):ident})
        for ident in ('1','2'):
            number=etree.SubElement(numbering,q('num'),{q('numId'):ident})
            etree.SubElement(number,q('abstractNumId'),{q('val'):ident})
            override=etree.SubElement(number,q('lvlOverride'),{q('ilvl'):'1'})
            etree.SubElement(override,q('startOverride'),{q('val'):'7'})
        derived=etree.SubElement(styles,q('style'),{q('type'):'paragraph',q('styleId'):'DerivedList'})
        etree.SubElement(derived,q('basedOn'),{q('val'):'ListBullet'})
        parts['word/styles.xml']=merge.serialized(styles)
        parts['word/numbering.xml']=merge.serialized(numbering)
        rels=merge.xml(parts['word/_rels/document.xml.rels'])
        etree.SubElement(rels,'{'+merge.P+'}Relationship',Id='numbering',Type=merge.R+'/numbering',Target='numbering.xml')
        parts['word/_rels/document.xml.rels']=merge.serialized(rels)
        self.files.write_parts(file,parts);return file

    def assert_preserved(self,source,merged,mapping=None):
        original=merge.xml(source['word/numbering.xml'])
        result=merge.xml(merged['word/numbering.xml'])
        ids=mapping or{'abstractNumIds':{},'numIds':{}}
        for node in original:
            abstract=node.tag==q('abstractNum');attribute='abstractNumId'if abstract else'numId'
            key='abstractNumIds'if abstract else'numIds';old=node.get(q(attribute));new=ids[key].get(old,old)
            found=next(n for n in result if n.tag==node.tag and n.get(q(attribute))==new)
            actual=deepcopy(found);actual.set(q(attribute),old)
            if not abstract:
                ref=actual.find(q('abstractNumId'));reverse={v:k for k,v in ids['abstractNumIds'].items()}
                ref.set(q('val'),reverse.get(ref.get(q('val')),ref.get(q('val'))))
            self.assertEqual(merge.semantic(node),merge.semantic(actual))

    def test_physical_and_logical_definitions_keep_every_level_and_override(self):
        files=[self.fixture('old'),self.fixture('new',True)]
        originals=[self.files.parts(f)for f in files];hashes=[hashlib.sha256(f.read_bytes()).hexdigest()for f in files]
        result=merge.merge_docx(files,self.output);merged=self.files.parts(self.output)
        mapping=result['isolatedNumbering'][0];self.assertEqual(mapping['part'],2)
        self.assertTrue(set(mapping['numIds'].values()).isdisjoint({'1','2'}))
        self.assert_preserved(originals[0],merged);self.assert_preserved(originals[1],merged,mapping)
        style_ids=result['isolatedStyles'][0]['styles'];styles=merge.style_index(merge.xml(merged['word/styles.xml']))
        for name,old in [('ListBullet','1'),('ListNumber','2')]:
            self.assertEqual(styles[name].find('.//'+q('numId')).get(q('val')),old)
            self.assertEqual(styles[style_ids[name]].find('.//'+q('numId')).get(q('val')),mapping['numIds'][old])
        self.assertEqual(styles[style_ids['DerivedList']].find(q('basedOn')).get(q('val')),style_ids['ListBullet'])
        body=merge.xml(merged['word/document.xml']).find(q('body'))
        bodies=[merge.xml(p['word/document.xml']).find(q('body'))for p in originals]
        self.assertEqual(merge.body_text(body),''.join(merge.body_text(b)for b in bodies))
        self.assertEqual(merge.normal_notes(merged,body),[n for p,b in zip(originals,bodies)for n in merge.normal_notes(p,b)])
        self.assertEqual([hashlib.sha256(f.read_bytes()).hexdigest()for f in files],hashes)

    def test_three_books_reusing_ids_preserve_each_own_definitions(self):
        files=[self.fixture('first'),self.fixture('second',True),self.fixture('third')]
        originals=[self.files.parts(f)for f in files]
        result=merge.merge_docx(files,self.output);merged=self.files.parts(self.output)
        self.assertEqual(len(result['isolatedNumbering']),2)
        self.assert_preserved(originals[0],merged)
        for original,mapping in zip(originals[1:],result['isolatedNumbering']):self.assert_preserved(original,merged,mapping)
        numbers=merge.xml(merged['word/numbering.xml']).findall(q('num'))
        self.assertEqual(len(numbers),6);self.assertEqual(len({n.get(q('numId'))for n in numbers}),6)

    def test_identical_libraries_remain_shared(self):
        files=[self.fixture('first'),self.fixture('second')]
        result=merge.merge_docx(files,self.output)
        self.assertFalse(result['isolatedNumbering']);self.assertFalse(result['isolatedStyles'])
        self.assert_preserved(self.files.parts(files[0]),self.files.parts(self.output))

    def test_missing_first_library_imports_numbering_relationship_and_content_type(self):
        first=self.files.fixture('first');second=self.fixture('second',True)
        result=merge.merge_docx([first,second],self.output);parts=self.files.parts(self.output)
        self.assert_preserved(self.files.parts(second),parts,result['isolatedNumbering'][0])
        rels=merge.xml(parts['word/_rels/document.xml.rels'])
        self.assertEqual(len([r for r in rels if r.get('Type')==merge.R+'/numbering']),1)
        types=merge.xml(parts['[Content_Types].xml'])
        self.assertEqual(len([t for t in types if t.get('PartName')=='/word/numbering.xml']),1)

    def test_later_book_without_numbering_preserves_first_library(self):
        first=self.fixture('first');second=self.files.fixture('second')
        result=merge.merge_docx([first,second],self.output)
        self.assertFalse(result['isolatedNumbering'])
        self.assert_preserved(self.files.parts(first),self.files.parts(self.output))

    def test_active_lists_in_body_notes_headers_and_inherited_styles_still_rejected(self):
        for place in('body','footnote','header','derived','default'):
            with self.subTest(place=place):
                first=self.fixture('first');second=self.fixture('second',True);parts=self.files.parts(second)
                name='word/styles.xml'if place in('derived','default')else'word/footnotes.xml'if place=='footnote'else'word/document.xml'
                tree=merge.xml(parts[name])
                if place in('derived','default'):
                    if place=='default':
                        normal=merge.style_index(tree)['Normal'];etree.SubElement(normal,q('basedOn'),{q('val'):'ListNumber'})
                    else:
                        name='word/document.xml';tree=merge.xml(parts[name]);tree.find('.//'+q('pStyle')).set(q('val'),'DerivedList')
                else:
                    if place=='header':name='word/header1.xml';tree=etree.Element(q('hdr'));etree.SubElement(tree,q('p'))
                    paragraph=next(tree.iter(q('p')));props=paragraph.find(q('pPr'))
                    if props is None:props=etree.SubElement(paragraph,q('pPr'))
                    etree.SubElement(etree.SubElement(props,q('numPr')),q('numId'),{q('val'):'1'})
                parts[name]=merge.serialized(tree);self.files.write_parts(second,parts)
                with self.assertRaisesRegex(ValueError,'automatic list numbering'):merge.merge_docx([first,second],self.output)
                self.assertFalse(self.output.exists())

    def test_picture_style_links_and_relationships_still_fail_closed(self):
        for kind in('numPicBullet','lvlPicBulletId','pStyle','styleLink','numStyleLink','relationship'):
            with self.subTest(kind=kind):
                first=self.fixture('first');second=self.fixture('second',True);parts=self.files.parts(second)
                tree=merge.xml(parts['word/numbering.xml']);parent=tree if kind=='numPicBullet'else tree.find(q('abstractNum'))
                if kind=='relationship':parent.set('{'+merge.R+'}id','image')
                else:etree.SubElement(parent,q(kind),{q('val'):'ListBullet'})
                parts['word/numbering.xml']=merge.serialized(tree);self.files.write_parts(second,parts)
                with self.assertRaisesRegex(ValueError,'Unsupported.*numbering'):merge.merge_docx([first,second],self.output)
                self.assertFalse(self.output.exists())

    def test_invalid_duplicate_and_unresolved_numbering_rejected(self):
        for kind in('duplicate-num','duplicate-abstract','invalid-id','missing-abstract','unknown-style-reference','missing-library'):
            with self.subTest(kind=kind):
                first=self.fixture('first');second=self.fixture('second',True);parts=self.files.parts(second)
                tree=merge.xml(parts['word/numbering.xml'])
                if kind.startswith('duplicate'):
                    tree.append(deepcopy(tree.find(q('num'if kind=='duplicate-num'else'abstractNum'))))
                elif kind=='invalid-id':tree.find(q('num')).set(q('numId'),'-1')
                elif kind=='missing-abstract':tree.find(q('num')+'/'+q('abstractNumId')).set(q('val'),'999')
                elif kind=='unknown-style-reference':
                    styles=merge.xml(parts['word/styles.xml']);styles.find('.//'+q('numId')).set(q('val'),'999');parts['word/styles.xml']=merge.serialized(styles)
                parts['word/numbering.xml']=merge.serialized(tree)
                if kind=='missing-library':parts.pop('word/numbering.xml')
                self.files.write_parts(second,parts)
                with self.assertRaisesRegex(ValueError,'numbering'):merge.merge_docx([first,second],self.output)
                self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
