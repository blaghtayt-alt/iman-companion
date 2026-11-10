"""Exact source retention and pinned fonts for observed multilingual glyph gaps."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib,json,sys,tempfile,unittest,zipfile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from build_books import add_text,embed_fonts
from font_integrity import families,restore,verify
from merge_public_books import merge_docx
from script_fallbacks import FONT_FAMILIES,fallback_key,fallback_runs,FIQH_SOURCE_PARAGRAPH_SHA256
from script_font_slots import repair_parts,q,W
from reader_xml import body_text


class ScriptFallbackChecks(unittest.TestCase):
    def setUp(self):
        self.conf=json.loads((ROOT/'books/config.json').read_bytes())

    def paragraph(self,value,language):
        doc=Document();paragraph=doc.add_paragraph()
        family=self.conf['fonts'][self.conf['languages'][language]['font']]['family']
        add_text(paragraph,value,language,family,FONT_FAMILIES['Arabic'],bold=True)
        return doc,paragraph

    def test_thai_literal_note_keeps_characters_and_selects_pinned_faces(self):
        value='〔หมายเหตุ Q39:7อธิบาย〕 “ข้อความ” 2020 ʿāṣ อัลลอฮ์ ﷺ'
        _,paragraph=self.paragraph(value,'th')
        self.assertEqual(paragraph.text,value)
        for run in paragraph.runs:
            for character in run.text:
                key=fallback_key('th',character)
                if key:
                    for slot in ('ascii','hAnsi','eastAsia','cs'):
                        self.assertEqual(run._r.rPr.rFonts.get(qn('w:'+slot)),FONT_FAMILIES[key])
            if any('\u0e00'<=character<='\u0e7f' for character in run.text):
                self.assertEqual(run.font.name,'Iman Book Thai')
            self.assertTrue(run.bold)
        self.assertEqual([run.text for run in paragraph.runs if run.text=='39:7'],['39:7'])

    def test_observed_gaps_in_other_languages_are_literal_and_targeted(self):
        examples={'ur':'متن ﻻ ﹲ ﺬ','zh-CN':'文字 ʿʾṣ','vi':'Lời 〔Q39:7〕 ʿʾṣ',
                  'fil':'〈salin〉 〔Q39:7〕','bn':'বাংলা · «উক্তি»','hi':'हिन्दी · «पाठ»'}
        for language,value in examples.items():
            with self.subTest(language=language):
                _,paragraph=self.paragraph(value,language)
                self.assertEqual(paragraph.text,value)
                for run in paragraph.runs:
                    for character in run.text:
                        key=fallback_key(language,character)
                        if key:self.assertEqual(run.font.name,FONT_FAMILIES[key])
        # An unrelated script never inherits these locale-specific exceptions.
        for language in ('ar','fa','en','ja','de'):
            self.assertEqual(list(fallback_runs('〔Q39:7〕 ﻻ ʿṣ «»',language)),[('〔Q39:7〕 ﻻ ʿṣ «»',None)])

    def fiqh_text(self):
        unit=json.loads((ROOT/'books/units/current/en/hadith/essential-01-001.json').read_bytes())
        block=unit['sections'][2]['blocks'][18]
        self.assertEqual(hashlib.sha256(block['text'].encode()).hexdigest(),FIQH_SOURCE_PARAGRAPH_SHA256)
        self.assertEqual(block['sourceLiteralProof']['textSHA256'],FIQH_SOURCE_PARAGRAPH_SHA256)
        return block['text']

    def test_fiqh_private_characters_require_the_exact_source_context(self):
        value=self.fiqh_text()
        doc,paragraph=self.paragraph(value,'en')
        self.assertEqual(paragraph.text,value)
        self.assertEqual([r.text for r in paragraph.runs if r.font.name==FONT_FAMILIES['FiqhSymbols']],['\uf074','\uf065'])
        for language,text in [('en',None),('en',value+' '),('en','An unrelated private glyph \uf074'),('ar',value)]:
            for character in '\uf074\uf065':
                self.assertIsNone(fallback_key(language,character,text))
        self.assertIsNone(fallback_key('en','\uf075',value))

    def test_fiqh_font_restore_preserves_text_breaks_and_other_xml(self):
        value=self.fiqh_text()
        doc=Document();paragraph=doc.add_paragraph();run=paragraph.add_run(value)
        run.bold=True;run.font.color.rgb=__import__('docx').shared.RGBColor.from_string('2563EB')
        buffer=BytesIO();doc.save(buffer)
        with zipfile.ZipFile(buffer) as z:parts={n:z.read(n) for n in z.namelist()}
        from script_font_slots import _reader_content
        before=_reader_content(etree.fromstring(parts['word/document.xml']))
        repair_parts(parts,self.conf,'en')
        tree=etree.fromstring(parts['word/document.xml'])
        self.assertEqual(_reader_content(tree),before)
        self.assertEqual(body_text(tree),value)
        aliases=[]
        for run in tree.iter(q('r')):
            text=body_text(run)
            if any(c in text for c in '\uf074\uf065'):
                aliases.append(text)
                for slot in ('ascii','hAnsi','eastAsia','cs'):
                    self.assertEqual(run.find('.//'+q('rFonts')).get(q(slot)),FONT_FAMILIES['FiqhSymbols'])
                self.assertIsNotNone(run.find('.//'+q('b')))
                self.assertEqual(run.find('.//'+q('color')).get(q('val')),'2563EB')
        self.assertEqual(aliases,['\uf074','\uf065'])
        once=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'en'),{});self.assertEqual(parts,once)

    def test_fiqh_font_pin_matches_the_licensed_outlines_and_aliases(self):
        from fontTools.ttLib import TTFont
        definition=self.conf['fonts']['FiqhSymbols']
        for style,path in definition['files'].items():
            raw=(ROOT/path).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),definition['sha256'][style])
            with TTFont(BytesIO(raw)) as font:
                cmap=font.getBestCmap()
                self.assertEqual(cmap[0xf065],cmap[0xfdfa])
                self.assertEqual(cmap[0xf074],cmap[0xfd41])
                self.assertNotIn(0xf075,cmap)
                self.assertEqual(font['name'].getDebugName(1),FONT_FAMILIES['FiqhSymbols'])
                self.assertIn('Open Font License',font['name'].getDebugName(13))

    def test_font_restore_splits_coalesced_body_and_notes_without_changing_structure(self):
        value='〔หมายเหตุ Q39:41อธิบาย〕 ข้อความ 2020'
        raw=f'''<w:document xmlns:w="{W}"><w:body><w:p>
          <w:bookmarkStart w:id="8" w:name="source"/><w:r><w:rPr>
          <w:rFonts w:ascii="Iman Book Thai" w:asciiTheme="minorHAnsi"/>
          <w:color w:val="2563EB"/><w:b/><w:cs w:val="1"/></w:rPr>
          <w:t xml:space="preserve">{value}</w:t><w:tab/>
          <w:footnoteReference w:id="7"/><w:fldChar w:fldCharType="begin"/>
          <w:instrText xml:space="preserve"> REF source </w:instrText>
          <w:fldChar w:fldCharType="end"/><w:br/></w:r><w:bookmarkEnd w:id="8"/>
          </w:p></w:body></w:document>'''.encode()
        parts={'word/document.xml':raw,'word/footnotes.xml':raw,'image.bin':b'unchanged'}
        repair_parts(parts,self.conf,'th')
        for name in ('word/document.xml','word/footnotes.xml'):
            tree=etree.fromstring(parts[name])
            self.assertEqual(''.join(node.text or '' for node in tree.iter(q('t'))),value)
            for tag in ('bookmarkStart','bookmarkEnd','footnoteReference','tab','br','fldChar','instrText'):
                snapshot=lambda root:[(dict(node.attrib),node.text) for node in root.iter(q(tag))]
                self.assertEqual(snapshot(tree),snapshot(etree.fromstring(raw)),tag)
            for run in tree.iter(q('r')):
                text=''.join(node.text or '' for node in run.findall(q('t')))
                properties=run.find(q('rPr'))
                self.assertEqual(properties.find(q('color')).get(q('val')),'2563EB')
                self.assertIsNotNone(properties.find(q('b')))
                for character in text:
                    key=fallback_key('th',character)
                    if key:
                        self.assertEqual(properties.find(q('rFonts')).get(q('cs')),FONT_FAMILIES[key])
                        self.assertIsNone(properties.find(q('cs')))
        once=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'th'),{});self.assertEqual(parts,once)

    def test_restore_keeps_urdu_presentation_forms_in_canonical_arabic_face(self):
        value='لفظ ﻻ ﹲ ﺬ باقی'
        doc,paragraph=self.paragraph(value,'ur');buffer=BytesIO();doc.save(buffer)
        with zipfile.ZipFile(buffer) as archive:parts={name:archive.read(name) for name in archive.namelist()}
        repair_parts(parts,self.conf,'ur');tree=etree.fromstring(parts['word/document.xml'])
        self.assertEqual(''.join(tree.xpath('//w:body//w:t/text()',namespaces={'w':W})),value)
        for run in tree.iter(q('r')):
            text=''.join(node.text or '' for node in run.findall(q('t')))
            if any(character in text for character in 'ﻻﹲﺬ'):
                self.assertEqual(run.find('.//'+q('rFonts')).get(q('cs')),FONT_FAMILIES['Arabic'])
                self.assertEqual(run.find('.//'+q('rtl')).get(q('val')),'1')

    def test_new_edge_spaces_are_preserved_when_internal_source_spaces_are_split(self):
        for language,value in [('th','ข้อความ Q39:7 กลาง'),('ar','نص — آخر')]:
            with self.subTest(language=language):
                raw=f'<w:document xmlns:w="{W}"><w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:document>'.encode()
                parts={'word/document.xml':raw};repair_parts(parts,self.conf,language)
                nodes=list(etree.fromstring(parts['word/document.xml']).iter(q('t')))
                self.assertEqual(''.join(node.text or '' for node in nodes),value)
                edges=[node for node in nodes if node.text and (node.text[0].isspace() or node.text[-1].isspace())]
                self.assertTrue(edges)
                for node in edges:self.assertEqual(node.get('{http://www.w3.org/XML/1998/namespace}space'),'preserve')

    def test_thai_generated_field_styles_use_pinned_ascii_without_changing_native_slots(self):
        raw=f'''<w:styles xmlns:w="{W}"><w:style w:styleId="Footer"><w:rPr>
          <w:rFonts w:ascii="Iman Book Thai" w:hAnsi="Iman Book Thai" w:asciiTheme="minorHAnsi"
          w:eastAsia="Iman Book Thai" w:cs="Iman Book Thai"/>
          </w:rPr></w:style></w:styles>'''.encode()
        parts={'word/styles.xml':raw};repair_parts(parts,self.conf,'th')
        fonts=etree.fromstring(parts['word/styles.xml']).find('.//'+q('rFonts'))
        for slot in ('ascii','hAnsi'):self.assertEqual(fonts.get(q(slot)),FONT_FAMILIES['Latin'])
        self.assertNotIn(q('asciiTheme'),fonts.attrib)
        for slot in ('eastAsia','cs'):self.assertEqual(fonts.get(q(slot)),'Iman Book Thai')
        once=deepcopy(parts);self.assertEqual(repair_parts(parts,self.conf,'th'),{});self.assertEqual(parts,once)

    def fixture_config(self,root):
        conf=deepcopy(self.conf)
        for key,definition in conf['fonts'].items():
            value=(key.encode()*64);path=root/(key+'.ttf');path.write_bytes(value)
            definition['files']={'Regular':path.name};definition['sha256']={'Regular':hashlib.sha256(value).hexdigest()}
        return conf

    def test_old_font_contract_remains_verifiable_for_every_supported_language(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conf=self.fixture_config(root)
            for language in conf['languages']:
                with self.subTest(language=language):
                    file=root/(language+'.docx');doc=Document();doc.add_paragraph('Existing exact reviewed package.');doc.save(file)
                    legacy={name:{style:root/path for style,path in definition['files'].items()}
                            for name,definition in families(conf,language).items()}
                    embed_fonts(file,legacy)
                    self.assertTrue(verify(file,conf,language))

    def test_new_bracket_font_is_required_pinned_and_preserved_in_mixed_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conf=self.fixture_config(root);files=[]
            for index,value in enumerate(('ข้อความเดิม','〔หมายเหตุ Q39:7〕 ข้อความ')):
                file=root/(str(index)+'.docx');doc=Document();doc.add_paragraph(value);doc.save(file)
                restore(file,conf,'th',root);self.assertTrue(verify(file,conf,'th'));files.append(file)
                with zipfile.ZipFile(file) as archive:
                    table=etree.fromstring(archive.read('word/fontTable.xml'))
                    names={node.get(q('name')) for node in table}
                    self.assertEqual(FONT_FAMILIES['Japanese'] in names,bool(index))
            output=root/'combined.docx';merge_docx(files,output)
            self.assertTrue(verify(output,conf,'th'))
            self.assertEqual([paragraph.text for paragraph in Document(output).paragraphs if paragraph.text],
                             ['ข้อความเดิม','〔หมายเหตุ Q39:7〕 ข้อความ'])
            with zipfile.ZipFile(files[1]) as archive:parts={name:archive.read(name) for name in archive.namelist()}
            table=etree.fromstring(parts['word/fontTable.xml'])
            japanese=next(node for node in table if node.get(q('name'))==FONT_FAMILIES['Japanese'])
            table.remove(japanese);parts['word/fontTable.xml']=etree.tostring(table)
            with zipfile.ZipFile(files[1],'w',zipfile.ZIP_DEFLATED) as archive:
                for name,value in parts.items():archive.writestr(name,value)
            with self.assertRaisesRegex(ValueError,'Missing or ambiguous pinned font'):
                verify(files[1],conf,'th')


if __name__=='__main__':unittest.main()
