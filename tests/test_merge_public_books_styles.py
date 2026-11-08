"""Conservative style compatibility and exact-reader preservation in DOCX merges."""
from copy import deepcopy
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import zipfile

from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
import merge_public_books as merge

W=merge.W
q=merge.q
STYLE='EndnoteCharacters'


class MergeStyleChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.output=self.root/'combined.docx'

    def tearDown(self):
        self.temp.cleanup()

    def parts(self,file):
        with zipfile.ZipFile(file)as archive:
            return {name:archive.read(name)for name in archive.namelist()}

    def write_parts(self,file,parts):
        with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED)as archive:
            for name,raw in parts.items():archive.writestr(name,raw)

    def fixture(self,label,superscript=False,kind='character',default=None,use=False):
        document=etree.Element(q('document'),nsmap={'w':W,'r':merge.R})
        body=etree.SubElement(document,q('body'))
        paragraph=etree.SubElement(body,q('p'))
        properties=etree.SubElement(paragraph,q('pPr'))
        etree.SubElement(properties,q('pStyle'),{q('val'):'Normal'})
        run=etree.SubElement(paragraph,q('r'))
        run_properties=etree.SubElement(run,q('rPr'))
        etree.SubElement(run_properties,q('b'))
        if use:etree.SubElement(run_properties,q('rStyle'),{q('val'):STYLE})
        etree.SubElement(run,q('t'),{'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text='  '+label+' متن عربي '
        etree.SubElement(run,q('tab'))
        etree.SubElement(run,q('t')).text='[123]'
        etree.SubElement(run,q('br'))
        etree.SubElement(run,q('t')).text=' final text '
        etree.SubElement(run,q('footnoteReference'),{q('id'):'1'})
        last=etree.SubElement(body,q('p'))
        etree.SubElement(etree.SubElement(last,q('r')),q('t')).text=label+' END'
        section=etree.SubElement(body,q('sectPr'))
        etree.SubElement(section,q('pgSz'),{q('w'):'8640',q('h'):'12960'})
        styles=etree.Element(q('styles'),nsmap={'w':W})
        etree.SubElement(styles,q('style'),{q('type'):'paragraph',q('styleId'):'Normal',q('default'):'1'})
        attrs={q('type'):kind,q('styleId'):STYLE}
        if default is not None:attrs[q('default')]=default
        style=etree.SubElement(styles,q('style'),attrs)
        rpr=etree.SubElement(style,q('rPr'))
        if superscript:etree.SubElement(rpr,q('vertAlign'),{q('val'):'superscript'})
        notes=etree.Element(q('footnotes'),nsmap={'w':W})
        separator=etree.SubElement(notes,q('footnote'),{q('type'):'separator',q('id'):'0'})
        etree.SubElement(etree.SubElement(etree.SubElement(separator,q('p')),q('r')),q('separator'))
        note=etree.SubElement(notes,q('footnote'),{q('id'):'1'})
        note_run=etree.SubElement(etree.SubElement(note,q('p')),q('r'))
        etree.SubElement(etree.SubElement(note_run,q('rPr')),q('i'))
        etree.SubElement(note_run,q('t')).text=label+' [مرجع: 123] exact footnote'
        relationships=etree.Element('{'+merge.P+'}Relationships')
        for i,(target,kind_name)in enumerate((('styles.xml','styles'),('settings.xml','settings'),('footnotes.xml','footnotes')),1):
            etree.SubElement(relationships,'{'+merge.P+'}Relationship',Id='rId'+str(i),Type=merge.R+'/'+kind_name,Target=target)
        types=etree.Element('{'+merge.C+'}Types')
        for name,kind_name in (('document.xml','document.main'),('styles.xml','styles'),('settings.xml','settings'),('footnotes.xml','footnotes')):
            etree.SubElement(types,'{'+merge.C+'}Override',PartName='/word/'+name,ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind_name+'+xml')
        parts={'word/document.xml':merge.serialized(document),'word/styles.xml':merge.serialized(styles),
               'word/footnotes.xml':merge.serialized(notes),'word/settings.xml':merge.serialized(etree.Element(q('settings'),nsmap={'w':W})),
               'word/_rels/document.xml.rels':merge.serialized(relationships),'[Content_Types].xml':merge.serialized(types)}
        file=self.root/(label+'.docx')
        self.write_parts(file,parts)
        return file

    def add_reference(self,file,part,tag):
        parts=self.parts(file)
        tree=merge.xml(parts[part])if part in parts else etree.Element(q('fixture'),nsmap={'w':W})
        etree.SubElement(tree,q(tag),{q('val'):STYLE})
        parts[part]=merge.serialized(tree)
        self.write_parts(file,parts)

    def reject(self,inputs):
        with self.assertRaisesRegex(ValueError,'incompatible.*'+STYLE):
            merge.merge_docx(inputs,self.output)
        self.assertFalse(self.output.exists())

    def normalized_runs(self,body):
        result=[]
        for run in body.iter(q('r')):
            run=deepcopy(run)
            for reference in run.iter(q('footnoteReference')):reference.set(q('id'),'NORMALIZED')
            result.append(merge.semantic(run))
        return result

    def normalized_notes(self,parts):
        result=[]
        for note in merge.xml(parts['word/footnotes.xml']):
            if note.get(q('type'))not in(None,'normal'):continue
            note=deepcopy(note);note.set(q('id'),'NORMALIZED');result.append(merge.semantic(note))
        return result

    def test_unused_character_difference_merges_with_exact_body_and_footnotes(self):
        inputs=[self.fixture('first',True),self.fixture('second')]
        original=[self.parts(file)for file in inputs]
        hashes=[hashlib.sha256(file.read_bytes()).hexdigest()for file in inputs]
        bodies=[merge.xml(parts['word/document.xml']).find(q('body'))for parts in original]
        result=merge.merge_docx(inputs,self.output)
        merged=self.parts(self.output);body=merge.xml(merged['word/document.xml']).find(q('body'))
        self.assertEqual(merge.body_text(body),''.join(merge.body_text(item)for item in bodies))
        self.assertEqual(self.normalized_runs(body),[run for item in bodies for run in self.normalized_runs(item)])
        self.assertEqual(self.normalized_notes(merged),[note for parts in original for note in self.normalized_notes(parts)])
        self.assertEqual(merge.normal_notes(merged,body),[note for parts,item in zip(original,bodies)for note in merge.normal_notes(parts,item)])
        self.assertEqual([hashlib.sha256(file.read_bytes()).hexdigest()for file in inputs],hashes)
        merged_style=merge.xml(merged['word/styles.xml']).find("w:style[@w:styleId='"+STYLE+"']",merge.NS)
        first_style=merge.xml(original[0]['word/styles.xml']).find("w:style[@w:styleId='"+STYLE+"']",merge.NS)
        self.assertEqual(merge.semantic(merged_style),merge.semantic(first_style))
        self.assertTrue(result['sourceBodyExactlyPreserved'])
        self.assertEqual(result['sourceFootnotesExactlyPreserved'],2)

    def test_used_character_difference_in_either_constituent_is_rejected(self):
        for used_source in (0,1):
            with self.subTest(used_source=used_source):
                self.reject([self.fixture('first',True,use=used_source==0),self.fixture('second',use=used_source==1)])

    def test_third_constituent_use_protects_earlier_conflict(self):
        self.reject([self.fixture('first',True),self.fixture('second'),self.fixture('third',True,use=True)])

    def test_references_in_every_word_xml_part_are_protected(self):
        for part in ('word/document.xml','word/footnotes.xml','word/endnotes.xml','word/header1.xml','word/footer1.xml','word/comments.xml','word/glossary/document.xml'):
            with self.subTest(part=part):
                first=self.fixture('first',True);second=self.fixture('second')
                self.add_reference(second,part,'rStyle');self.reject([first,second])

    def test_all_style_dependency_kinds_are_protected_even_when_owner_unused(self):
        for tag in ('pStyle','tblStyle','basedOn','link','next','styleLink','numStyleLink'):
            with self.subTest(tag=tag):
                first=self.fixture('first',True);second=self.fixture('second')
                self.add_reference(second,'word/numbering.xml'if tag in('styleLink','numStyleLink')else'word/styles.xml',tag)
                self.reject([first,second])

    def test_dependency_in_third_constituent_protects_earlier_conflict(self):
        inputs=[self.fixture('first',True),self.fixture('second'),self.fixture('third',True)]
        self.add_reference(inputs[2],'word/styles.xml','basedOn');self.reject(inputs)

    def test_default_character_styles_are_never_ignored(self):
        for value in ('1','true','on','unexpected'):
            for default_source in (0,1):
                with self.subTest(value=value,default_source=default_source):
                    self.reject([self.fixture('first',True,default=value if default_source==0 else None),self.fixture('second',default=value if default_source==1 else None)])

    def test_default_in_later_constituent_protects_earlier_conflict(self):
        self.reject([self.fixture('first',True),self.fixture('second'),self.fixture('third',True,default='1')])

    def test_explicit_false_default_flag_is_not_implicit_use(self):
        for value in ('0','false','off'):
            with self.subTest(value=value):
                merge.merge_docx([self.fixture('first',True,default=value),self.fixture('second',default=value)],self.output)
                self.assertTrue(self.output.exists());self.output.unlink()

    def test_unused_paragraph_or_table_style_conflicts_still_fail(self):
        for kind in ('paragraph','table','numbering'):
            with self.subTest(kind=kind):self.reject([self.fixture('first',True,kind),self.fixture('second',kind=kind)])

    def test_type_mismatch_cannot_be_ignored(self):
        self.reject([self.fixture('first',True,'character'),self.fixture('second',kind='paragraph')])

    def test_identical_used_character_style_is_still_compatible(self):
        merge.merge_docx([self.fixture('first',True,use=True),self.fixture('second',True,use=True)],self.output)
        self.assertTrue(self.output.exists())


if __name__=='__main__':unittest.main()
