"""Style isolation, fail-closed globals and exact-reader preservation in DOCX merges."""
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
        if part in parts:
            tree=merge.xml(parts[part])
            content=next(note for note in tree if note.get(q('type'))in(None,'normal'))if part=='word/footnotes.xml'else tree
            run=next(content.iter(q('r')))
        else:
            kind={'word/endnotes.xml':'endnotes','word/header1.xml':'header','word/footer1.xml':'footer','word/comments.xml':'comments','word/glossary/document.xml':'glossaryDocument'}[part]
            root_tag={'header':'hdr','footer':'ftr','glossaryDocument':'glossaryDocument'}.get(kind,kind)
            tree=etree.Element(q(root_tag),nsmap={'w':W})
            run=etree.SubElement(etree.SubElement(tree,q('p')),q('r'))
            etree.SubElement(run,q('t')).text='Referenced part '+part
            relationships=merge.xml(parts['word/_rels/document.xml.rels'])
            etree.SubElement(relationships,'{'+merge.P+'}Relationship',Id='fixture-part',Type=merge.R+'/'+kind,Target=part.removeprefix('word/'))
            parts['word/_rels/document.xml.rels']=merge.serialized(relationships)
            types=merge.xml(parts['[Content_Types].xml'])
            etree.SubElement(types,'{'+merge.C+'}Override',PartName='/'+part,ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.'+kind+'+xml')
            parts['[Content_Types].xml']=merge.serialized(types)
        prop=run.find(q('rPr'))
        if prop is None:prop=etree.SubElement(run,q('rPr'))
        etree.SubElement(prop,q(tag),{q('val'):STYLE})
        parts[part]=merge.serialized(tree)
        self.write_parts(file,parts)

    def reject(self,inputs,reason):
        with self.assertRaisesRegex(ValueError,reason):
            merge.merge_docx(inputs,self.output)
        self.assertFalse(self.output.exists())

    def normalized_runs(self,body,reverse_styles=None):
        result=[]
        for run in body.iter(q('r')):
            run=deepcopy(run)
            for reference in run.iter(q('footnoteReference')):reference.set(q('id'),'NORMALIZED')
            for reference in run.iter(q('rStyle')):
                value=reference.get(q('val'))
                if reverse_styles and value in reverse_styles:reference.set(q('val'),reverse_styles[value])
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

    def test_used_character_difference_preserves_both_styles_and_exact_runs(self):
        for used_source in (0,1):
            with self.subTest(used_source=used_source):
                inputs=[self.fixture('first',True,use=used_source==0),self.fixture('second',use=used_source==1)]
                originals=[self.parts(file)for file in inputs]
                result=merge.merge_docx(inputs,self.output);parts=self.parts(self.output)
                mapping=result['isolatedStyles'][0]['styles'];self.assertIn(STYLE,mapping)
                styles=merge.style_index(merge.xml(parts['word/styles.xml']))
                self.assertEqual(styles[STYLE].find('.//'+q('vertAlign')).get(q('val')),'superscript')
                self.assertIsNone(styles[mapping[STYLE]].find('.//'+q('vertAlign')))
                body=merge.xml(parts['word/document.xml']).find(q('body'))
                original_runs=[run for original in originals for run in self.normalized_runs(merge.xml(original['word/document.xml']).find(q('body')))]
                self.assertEqual(self.normalized_runs(body,{new:old for old,new in mapping.items()}),original_runs)
                self.assertEqual(self.normalized_notes(parts),[note for original in originals for note in self.normalized_notes(original)])

    def test_third_constituent_use_protects_earlier_conflict(self):
        result=merge.merge_docx([self.fixture('first',True),self.fixture('second'),self.fixture('third',True,use=True)],self.output)
        self.assertEqual([item['part']for item in result['isolatedStyles']],[2])
        parts=self.parts(self.output);doc=merge.xml(parts['word/document.xml'])
        run=next(run for run in doc.iter(q('r'))if ''.join(run.itertext()).startswith('  third'))
        self.assertEqual(run.find('./'+q('rPr')+'/'+q('rStyle')).get(q('val')),STYLE)
        self.assertEqual(merge.style_index(merge.xml(parts['word/styles.xml']))[STYLE].find('.//'+q('vertAlign')).get(q('val')),'superscript')

    def test_references_in_every_copied_word_xml_part_are_remapped(self):
        for part in ('word/document.xml','word/footnotes.xml','word/endnotes.xml','word/header1.xml','word/footer1.xml','word/comments.xml','word/glossary/document.xml'):
            with self.subTest(part=part):
                first=self.fixture('first',True);second=self.fixture('second')
                self.add_reference(second,part,'rStyle')
                result=merge.merge_docx([first,second],self.output)
                new=result['isolatedStyles'][0]['styles'][STYLE]
                target=part if part in('word/document.xml','word/footnotes.xml')else str(Path(part).with_name('m2-'+Path(part).name))
                copied=merge.xml(self.parts(self.output)[target])
                self.assertEqual([node.get(q('val'))for node in copied.iter(q('rStyle'))],[new])

    def test_style_dependencies_are_isolated_even_when_owner_unused(self):
        for tag in ('basedOn','link','next'):
            with self.subTest(tag=tag):
                first=self.fixture('first',True);second=self.fixture('second')
                for file in(first,second):
                    parts=self.parts(file);styles=merge.xml(parts['word/styles.xml'])
                    dependent=etree.SubElement(styles,q('style'),{q('type'):'character',q('styleId'):'Dependent'})
                    etree.SubElement(dependent,q(tag),{q('val'):STYLE})
                    parts['word/styles.xml']=merge.serialized(styles);self.write_parts(file,parts)
                result=merge.merge_docx([first,second],self.output)
                mapping=result['isolatedStyles'][0]['styles'];self.assertIn('Dependent',mapping)
                styles=merge.style_index(merge.xml(self.parts(self.output)['word/styles.xml']))
                self.assertEqual(styles['Dependent'].find(q(tag)).get(q('val')),STYLE)
                self.assertEqual(styles[mapping['Dependent']].find(q(tag)).get(q('val')),mapping[STYLE])

    def test_shared_numbering_style_references_still_fail_closed(self):
        for tag in ('pStyle','styleLink','numStyleLink'):
            with self.subTest(tag=tag):
                inputs=[self.fixture('first',True),self.fixture('second')]
                for file in inputs:
                    parts=self.parts(file);numbering=etree.Element(q('numbering'),nsmap={'w':W})
                    definition=etree.SubElement(numbering,q('abstractNum'),{q('abstractNumId'):'1'})
                    etree.SubElement(definition,q(tag),{q('val'):STYLE})
                    parts['word/numbering.xml']=merge.serialized(numbering);self.write_parts(file,parts)
                self.reject(inputs,'shared automatic numbering')

    def test_default_character_styles_are_explicitly_preserved(self):
        for value in ('1','true','on'):
            with self.subTest(value=value):
                result=merge.merge_docx([self.fixture('first',True,default=value),self.fixture('second',default=value)],self.output)
                mapping=result['isolatedStyles'][0]['styles'];parts=self.parts(self.output)
                styles=merge.style_index(merge.xml(parts['word/styles.xml']))
                self.assertEqual(styles[STYLE].get(q('default')),value)
                self.assertIsNone(styles[mapping[STYLE]].get(q('default')))
                body=merge.xml(parts['word/document.xml'])
                for run in body.iter(q('r')):
                    if 'second'in ''.join(run.itertext()):self.assertEqual(run.find('./'+q('rPr')+'/'+q('rStyle')).get(q('val')),mapping[STYLE])

    def test_unknown_default_flags_and_unrepresentable_absent_defaults_fail_closed(self):
        for default_source in (0,1):
            with self.subTest(default_source=default_source):
                self.reject([self.fixture('first',True,default='unexpected'if default_source==0 else None),self.fixture('second',default='unexpected'if default_source==1 else None)],'default style flag')
        self.reject([self.fixture('first',True,default='1'),self.fixture('second')],'incompatible implicit style defaults')

    def test_default_in_later_constituent_protects_earlier_conflict(self):
        result=merge.merge_docx([self.fixture('first',True),self.fixture('second'),self.fixture('third',True,default='1')],self.output)
        mapping=next(item['styles']for item in result['isolatedStyles']if item['part']==3)
        parts=self.parts(self.output);styles=merge.style_index(merge.xml(parts['word/styles.xml']))
        self.assertFalse(any(style.get(q('default'))in('1','true','on')for style in styles.values()if style.get(q('type'))=='character'))
        for run in merge.xml(parts['word/document.xml']).iter(q('r')):
            text=''.join(run.itertext());reference=run.find('./'+q('rPr')+'/'+q('rStyle'))
            if 'third'in text:self.assertEqual(reference.get(q('val')),mapping[STYLE])
            elif text:self.assertIsNone(reference)

    def test_explicit_false_default_flag_is_not_implicit_use(self):
        for value in ('0','false','off'):
            with self.subTest(value=value):
                merge.merge_docx([self.fixture('first',True,default=value),self.fixture('second',default=value)],self.output)
                self.assertTrue(self.output.exists());self.output.unlink()

    def test_unused_style_conflicts_keep_each_constituent_definition(self):
        for kind in ('paragraph','table','numbering'):
            with self.subTest(kind=kind):
                result=merge.merge_docx([self.fixture('first',True,kind),self.fixture('second',kind=kind)],self.output)
                styles=merge.style_index(merge.xml(self.parts(self.output)['word/styles.xml']))
                new=result['isolatedStyles'][0]['styles'][STYLE]
                self.assertEqual(styles[new].get(q('type')),kind)
                self.assertIsNone(styles[new].find('.//'+q('vertAlign')))
                self.assertIsNotNone(styles[STYLE].find('.//'+q('vertAlign')))

    def test_conflicting_style_types_are_separate(self):
        result=merge.merge_docx([self.fixture('first',True,'character'),self.fixture('second',kind='paragraph')],self.output)
        styles=merge.style_index(merge.xml(self.parts(self.output)['word/styles.xml']))
        self.assertEqual(styles[STYLE].get(q('type')),'character')
        self.assertEqual(styles[result['isolatedStyles'][0]['styles'][STYLE]].get(q('type')),'paragraph')

    def test_global_defaults_and_inherited_list_numbering_still_fail_closed(self):
        first=self.fixture('first');second=self.fixture('second')
        parts=self.parts(second);styles=merge.xml(parts['word/styles.xml'])
        defaults=etree.SubElement(styles,q('docDefaults'));etree.SubElement(defaults,q('rPrDefault'))
        parts['word/styles.xml']=merge.serialized(styles);self.write_parts(second,parts)
        self.reject([first,second],'incompatible document style defaults')
        second=self.fixture('second');parts=self.parts(second);styles=merge.xml(parts['word/styles.xml'])
        normal=merge.style_index(styles)['Normal'];props=etree.SubElement(normal,q('pPr'))
        etree.SubElement(etree.SubElement(props,q('numPr')),q('numId'),{q('val'):'1'})
        parts['word/styles.xml']=merge.serialized(styles);self.write_parts(second,parts)
        self.reject([first,second],'automatic list numbering')

    def test_identical_used_character_style_is_still_compatible(self):
        merge.merge_docx([self.fixture('first',True,use=True),self.fixture('second',True,use=True)],self.output)
        self.assertTrue(self.output.exists())


if __name__=='__main__':unittest.main()
