from pathlib import Path
import tempfile,unittest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject,DictionaryObject,NameObject,NumberObject,TextStringObject
from toc_sync import linked_pages

class ContentsLinkTests(unittest.TestCase):
    def fixture(self,folder,duplicate_target=False):
        writer=PdfWriter();writer.add_blank_page(432,648);writer.add_blank_page(432,648)
        target=writer.pages[1].indirect_reference;items=[]
        for y,dest_y,label in [(600,600,'wrapped-title'),(585,600,'wrapped-title'),(560,600 if duplicate_target else 520,'second-title')]:
            dest=ArrayObject([target,NameObject('/XYZ'),NumberObject(30),NumberObject(dest_y),NumberObject(0)])
            item=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),NameObject('/Rect'):ArrayObject([NumberObject(30),NumberObject(y-10),NumberObject(400),NumberObject(y)]),NameObject('/Contents'):TextStringObject(label)})
            if y==560:item[NameObject('/A')]=DictionaryObject({NameObject('/S'):NameObject('/GoTo'),NameObject('/D'):dest})
            else:item[NameObject('/Dest')]=dest
            items.append(writer._add_object(item))
        writer.pages[0][NameObject('/Annots')]=ArrayObject(items);path=folder/'fixture.pdf';writer.write(path);return path
    def test_wrapped_rectangles_are_one_entry_distinct_heading_target_preserved(self):
        with tempfile.TemporaryDirectory() as temp:self.assertEqual(linked_pages(self.fixture(Path(temp)),2),[2,2])
    def test_duplicate_heading_destination_does_not_fake_two_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'do not match'):linked_pages(self.fixture(Path(temp),True),2)

if __name__=='__main__':unittest.main()
