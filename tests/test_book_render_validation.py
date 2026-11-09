import sys,unittest
from pathlib import Path
from copy import deepcopy
from lxml import etree
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from check_outputs import validate_footnotes,validate_toc
from reader_xml import body_text
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
Q=lambda name:'{'+W+'}'+name

def notes_fixture():
    root=etree.Element(Q('footnotes'))
    for ident,kind,text in [(1,'separator',''),(2,'continuationSeparator',''),(0,None,' source one'),(3,'normal',' source two')]:
        n=etree.SubElement(root,Q('footnote'));n.set(Q('id'),str(ident))
        if kind:n.set(Q('type'),kind)
        p=etree.SubElement(n,Q('p'));r=etree.SubElement(p,Q('r'));etree.SubElement(r,Q('t')).text=text
    body=etree.Element(Q('document'))
    for ident in [0,3]:etree.SubElement(body,Q('footnoteReference')).set(Q('id'),str(ident))
    return root,body

def toc_fixture():
    root=etree.Element(Q('document'));etree.SubElement(root,Q('bookmarkStart')).set(Q('name'),'heading-a')
    p=etree.SubElement(root,Q('p'));pr=etree.SubElement(p,Q('pPr'));etree.SubElement(pr,Q('pStyle')).set(Q('val'),'TOC1')
    link=etree.SubElement(p,Q('hyperlink'));link.set(Q('anchor'),'heading-a');etree.SubElement(link,Q('tab'));etree.SubElement(link,Q('t')).text='٣'
    return root

class RenderChecks(unittest.TestCase):
    def test_separator_ids_are_not_notes_and_zero_can_be_normal(self):
        notes,body=notes_fixture();validate_footnotes(notes,body,['source one','source two'],'en')
    def test_missing_and_duplicate_anchors_fail(self):
        notes,body=notes_fixture();body.remove(body[-1])
        with self.assertRaisesRegex(ValueError,'anchors'):validate_footnotes(notes,body,['source one','source two'],'en')
        notes,body=notes_fixture();body[-1].set(Q('id'),'0')
        with self.assertRaisesRegex(ValueError,'anchors'):validate_footnotes(notes,body,['source one','source two'],'en')
    def test_swapped_or_altered_note_fails(self):
        notes,body=notes_fixture()
        with self.assertRaisesRegex(ValueError,'text changed'):validate_footnotes(notes,body,['source two','source one'],'en')
        notes[-1].find('.//'+Q('t')).text=' source two changed'
        with self.assertRaisesRegex(ValueError,'text changed'):validate_footnotes(notes,body,['source one','source two'],'en')
    def test_duplicate_note_id_fails(self):
        notes,body=notes_fixture();notes[-1].set(Q('id'),'0')
        with self.assertRaisesRegex(ValueError,'Duplicate footnote ID'):validate_footnotes(notes,body,['source one','source two'],'en')
    def test_literal_line_breaks_and_tabs_survive(self):
        body=etree.fromstring(('<w:body xmlns:w="'+W+'"><w:p><w:r><w:t>A</w:t><w:br/><w:t>B</w:t><w:tab/><w:t>C</w:t><w:br w:type="page"/></w:r></w:p></w:body>').encode())
        self.assertEqual(body_text(body),'A\nB\tC')
    def test_literal_soft_hyphen_survives_word_element_serialization(self):
        expected="Yüce Al\u00adlah'ı"
        before=etree.fromstring(('<w:body xmlns:w="'+W+'"><w:p><w:r><w:t>'+expected+'</w:t></w:r></w:p></w:body>').encode())
        after=etree.fromstring(('<w:body xmlns:w="'+W+'"><w:p><w:r><w:t>Yüce Al</w:t><w:softHyphen/><w:t>lah\'ı</w:t></w:r></w:p></w:body>').encode())
        self.assertEqual(body_text(before),expected)
        self.assertEqual(body_text(after),expected)
        marker=after.find('.//'+Q('softHyphen'));marker.getparent().remove(marker)
        self.assertEqual(body_text(after),"Yüce Allah'ı")
        self.assertNotIn(expected,body_text(after))
    def test_contents_links_and_native_digits(self):
        root=toc_fixture();validate_toc(root,'ar',1)
        broken=deepcopy(root);broken.find('.//'+Q('hyperlink')).set(Q('anchor'),'missing')
        with self.assertRaisesRegex(ValueError,'contents link'):validate_toc(broken,'ar',1)
        broken=deepcopy(root);broken.find('.//'+Q('t')).text='3'
        with self.assertRaisesRegex(ValueError,'digit set'):validate_toc(broken,'ar',1)
        with self.assertRaisesRegex(ValueError,'Missing contents'):validate_toc(root,'ar',2)
if __name__=='__main__':unittest.main()
