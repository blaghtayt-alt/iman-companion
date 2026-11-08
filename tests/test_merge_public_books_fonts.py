"""Embedded fonts must survive a legacy/new translated-book bundle."""
from pathlib import Path
import hashlib,sys,tempfile,unittest,uuid,zipfile
from copy import deepcopy

from docx import Document
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from build_books import embed_fonts
from merge_public_books import C,P,R,body_text,merge_docx,q,serialized,xml


def read_parts(path):
    with zipfile.ZipFile(path)as archive:return {name:archive.read(name)for name in archive.namelist()}


def write_parts(path,parts):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as archive:
        for name,raw in parts.items():archive.writestr(name,raw)


def decoded_fonts(path):
    parts=read_parts(path);rels={n.get('Id'):n for n in xml(parts['word/_rels/fontTable.xml.rels'])};result={}
    for font in xml(parts['word/fontTable.xml']):
        for face in font:
            if not etree.QName(face).localname.startswith('embed'):continue
            rel=rels[face.get('{'+R+'}id')]
            assert rel.get('Type')==R+'/font'and rel.get('TargetMode')!='External'
            raw=bytearray(parts['word/'+rel.get('Target')]);key=uuid.UUID(face.get(q('fontKey')).strip('{}')).bytes[::-1]
            for i in range(32):raw[i]^=key[i%16]
            result[font.get(q('name')),etree.QName(face).localname]=bytes(raw)
    return result


class MergePublicBookFonts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.first=self.root/'first.docx';self.second=self.root/'second.docx';self.output=self.root/'merged.docx'

    def tearDown(self):self.temp.cleanup()

    def fixture(self,path,label,definitions):
        document=Document();paragraph=document.add_paragraph(label)
        for family in definitions:paragraph.add_run(' '+family).font.name=family
        document.save(path);files={}
        for family,faces in definitions.items():
            files[family]={}
            for style,raw in faces.items():
                file=self.root/(path.stem+'-'+hashlib.sha256((family+style).encode()).hexdigest()+'.ttf')
                file.write_bytes(raw);files[family][style]=file
        embed_fonts(path,files)

    def test_later_family_and_faces_keep_bytes_relationships_and_reader_text(self):
        base=b'base-face'*16;japanese=b'new-bracket-face'*16;bold=b'new-bold-face'*16
        self.fixture(self.first,'Legacy',{'Pinned Base':{'Regular':base}})
        self.fixture(self.second,'Translated',{'Pinned Base':{'Regular':base},'Pinned Japanese':{'Regular':japanese,'Bold':bold}})
        hashes=[hashlib.sha256(p.read_bytes()).hexdigest()for p in(self.first,self.second)]
        expected=''.join(body_text(xml(read_parts(p)['word/document.xml']).find(q('body')))for p in(self.first,self.second))
        merge_docx([self.first,self.second],self.output)
        self.assertEqual(decoded_fonts(self.output),{('Pinned Base','embedRegular'):base,('Pinned Japanese','embedRegular'):japanese,('Pinned Japanese','embedBold'):bold})
        parts=read_parts(self.output)
        self.assertEqual(body_text(xml(parts['word/document.xml']).find(q('body'))),expected)
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest()for p in(self.first,self.second)])
        rels=list(xml(parts['word/_rels/fontTable.xml.rels']))
        self.assertEqual(len(rels),3)
        self.assertEqual(len({r.get('Id')for r in rels}),3)
        types=xml(parts['[Content_Types].xml'])
        for rel in rels[1:]:
            self.assertTrue(any(n.get('PartName')=='/word/'+rel.get('Target')and n.get('ContentType')=='application/vnd.openxmlformats-officedocument.obfuscatedFont'for n in types))

    def test_existing_family_gains_a_missing_face(self):
        self.fixture(self.first,'Legacy',{'Pinned Base':{'Regular':b'r'*64}})
        self.fixture(self.second,'Current',{'Pinned Base':{'Regular':b'r'*64,'Bold':b'b'*64}})
        merge_docx([self.first,self.second],self.output)
        self.assertEqual(decoded_fonts(self.output),{('Pinned Base','embedRegular'):b'r'*64,('Pinned Base','embedBold'):b'b'*64})
        self.assertEqual(len(list(xml(read_parts(self.output)['word/fontTable.xml']))),1)

    def test_same_face_with_a_different_obfuscation_key_reuses_verified_bytes(self):
        raw=b'same pinned source'*16
        for path in(self.first,self.second):self.fixture(path,path.stem,{'Pinned Base':{'Regular':raw}})
        parts=read_parts(self.second);table=xml(parts['word/fontTable.xml']);face=table.find('.//'+q('embedRegular'))
        key=uuid.UUID('0ce25785-b4be-4bd0-8005-715868be6fd5');face.set(q('fontKey'),'{'+str(key).upper()+'}')
        data=bytearray(raw)
        for i in range(32):data[i]^=key.bytes[::-1][i%16]
        rel=xml(parts['word/_rels/fontTable.xml.rels'])[0];parts['word/'+rel.get('Target')]=bytes(data)
        parts['word/fontTable.xml']=serialized(table);write_parts(self.second,parts)
        first=read_parts(self.first)
        merge_docx([self.first,self.second],self.output)
        self.assertEqual(decoded_fonts(self.output),{('Pinned Base','embedRegular'):raw})
        self.assertEqual(read_parts(self.output)['word/fonts/book-0-Regular.odttf'],first['word/fonts/book-0-Regular.odttf'])

    def test_differing_embedded_bytes_for_one_family_and_face_are_rejected(self):
        self.fixture(self.first,'Legacy',{'Pinned Base':{'Regular':b'a'*64}})
        self.fixture(self.second,'Changed',{'Pinned Base':{'Regular':b'b'*64}})
        with self.assertRaisesRegex(ValueError,'incompatible embedded font'):
            merge_docx([self.first,self.second],self.output)
        self.assertFalse(self.output.exists())

    def test_unresolved_external_and_duplicate_embeddings_are_rejected(self):
        self.fixture(self.first,'Legacy',{'Pinned Base':{'Regular':b'a'*64}})
        self.fixture(self.second,'Translated',{'Pinned New':{'Regular':b'b'*64}})
        original=read_parts(self.second)
        for defect in('missing','external','duplicate-family','duplicate-face'):
            with self.subTest(defect=defect):
                parts=dict(original);table=xml(parts['word/fontTable.xml']);rels=xml(parts['word/_rels/fontTable.xml.rels'])
                if defect=='missing':parts.pop('word/'+rels[0].get('Target'))
                if defect=='external':rels[0].set('TargetMode','External')
                if defect=='duplicate-family':table.append(deepcopy(table[0]))
                if defect=='duplicate-face':table[0].append(deepcopy(table[0].find(q('embedRegular'))))
                parts['word/fontTable.xml']=serialized(table);parts['word/_rels/fontTable.xml.rels']=serialized(rels);write_parts(self.second,parts)
                with self.assertRaises(ValueError):merge_docx([self.first,self.second],self.output)
                self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
