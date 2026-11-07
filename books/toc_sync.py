"""Reconcile cached Word contents numbers to their actual PDF link targets.

The layout may change after the first contents refresh. Never release a book
whose visible page number points somewhere other than its own live link.
"""
from pathlib import Path
import argparse,json,os,tempfile,zipfile
from lxml import etree
from pypdf import PdfReader
from locale_copy import NATIVE_DIGITS

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
def tag(name):return '{'+W+'}'+name
def toc_nodes(root):
 result=[]
 for paragraph in root.findall('.//'+tag('p')):
  style=paragraph.find('./'+tag('pPr')+'/'+tag('pStyle'))
  if style is None or style.get(tag('val')) not in {'TOC1','TOC2','TOC 1','TOC 2'}:continue
  if len(paragraph.findall('.//'+tag('hyperlink')))!=1:raise ValueError('Contents entry has no unique link')
  nodes=list(paragraph.iter());tabs=[i for i,n in enumerate(nodes) if n.tag==tag('tab')]
  if not tabs:raise ValueError('Contents entry has no page separator')
  values=[n for n in nodes[tabs[-1]+1:] if n.tag==tag('t') and (n.text or '').strip()]
  if len(values)!=1 or not values[0].text.strip().isdigit():raise ValueError('Contents page number is not a single number')
  result.append(values[0])
 if not result:raise ValueError('Contents entries are missing')
 return result

def linked_pages(pdf,count):
 reader=PdfReader(pdf);page_ids={p.indirect_reference.idnum:i+1 for i,p in enumerate(reader.pages)};out=[]
 for page in reader.pages:
  links=[]
  for ref in page.get('/Annots',[]):
   item=ref.get_object();dest=item.get('/Dest');rect=item.get('/Rect')
   if item.get('/Subtype')!='/Link' or not isinstance(dest,list) or not dest or not rect:continue
   page_ref=dest[0];number=page_ids.get(getattr(page_ref,'idnum',None))
   if number is None:raise ValueError('Contents link target is not a PDF page')
   links.append((float(rect[3]),number))
  out.extend(n for _,n in sorted(links,reverse=True))
  if len(out)>=count:break
 if len(out)!=count:raise ValueError('Contents links do not match the Word contents entries')
 return out

def reconcile(docx,pdf,lang,write=False):
 with zipfile.ZipFile(docx) as z:parts={n:z.read(n) for n in z.namelist()}
 root=etree.fromstring(parts['word/document.xml']);nodes=toc_nodes(root);actual=linked_pages(pdf,len(nodes));shown=[int(n.text.strip()) for n in nodes];mismatches=[(i+1,a,b) for i,(a,b) in enumerate(zip(shown,actual)) if a!=b]
 if write and mismatches:
  native=NATIVE_DIGITS.get(lang,'0123456789');mapping=str.maketrans('0123456789',native)
  for node,n in zip(nodes,actual):node.text=str(n).translate(mapping)
  parts['word/document.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
  fd,tmp=tempfile.mkstemp(dir=Path(docx).parent,suffix='.docx');os.close(fd)
  try:
   with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
    for name,body in parts.items():z.writestr(name,body)
   os.replace(tmp,docx)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 return {'entries':len(nodes),'mismatches':len(mismatches),'sample':mismatches[:5]}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--write',action='store_true');args=parser.parse_args()
 data=json.loads((args.folder/'index.json').read_bytes());results=[]
 for book in data['books']:
  docx=args.folder/book['file'];result=reconcile(docx,docx.with_suffix('.pdf'),book['language'],args.write);results.append(result)
 print(json.dumps(results))
 if not args.write and any(x['mismatches'] for x in results):raise SystemExit('Contents page numbers differ from PDF link targets')
if __name__=='__main__':main()
