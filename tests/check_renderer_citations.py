"""Render the exact historical bidi citation failure with the pinned engine.

This integration check creates diagnostic files only. It never creates a
publication receipt, preparation queue entry, or visual acceptance.
"""
from copy import deepcopy
from pathlib import Path
import argparse,base64,hashlib,io,json,shutil,subprocess,sys,zipfile

from docx import Document
from docx.oxml import parse_xml
from docx.text.paragraph import Paragraph
from lxml import etree
import pdfplumber
import pypdfium2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from build_books import add_text
from reader_xml import body_text
from renderer_pin import verify_packages

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
FIXTURE_SHA='7dd022448d514417d0db22c4564cb16b64f1586112882b48a90b2676d5dfc1b1'


def unpack(file):
    with zipfile.ZipFile(file)as archive:return {name:archive.read(name)for name in archive.namelist()}


def literal_and_notes(parts):
    doc=etree.fromstring(parts['word/document.xml'])
    notes={n.get(W+'id'):''.join(t.text or ''for t in n.iter(W+'t'))for n in etree.fromstring(parts['word/footnotes.xml'])}
    return body_text(doc.find(W+'body')),[notes[n.get(W+'id')]for n in doc.iter(W+'footnoteReference')]


def pdf_evidence(file,out):
    brackets=[];digits=[]
    with pdfplumber.open(file)as doc:
        for number,page in enumerate(doc.pages,1):
            for char in page.chars:
                if char['top']>=250:continue
                row={'page':number,'char':char['text'],'x':char['x0'],'baseline':char['matrix'][5],'font':char['fontname']}
                if char['text']in('[' ,']'):brackets.append(row)
                elif char['text']in('١','٦'):digits.append(row)
    same_line=len(brackets)==2 and brackets[0]['page']==brackets[1]['page']and abs(brackets[0]['baseline']-brackets[1]['baseline'])<.5
    contained=[]
    if same_line:
        left,right=sorted(b['x']for b in brackets)
        contained=[d for d in digits if d['page']==brackets[0]['page']and abs(d['baseline']-brackets[0]['baseline'])<.5 and left<d['x']<right]
    ordered=sorted(contained,key=lambda d:d['x'])
    correct_order=len(ordered)==2 and [d['char']for d in ordered]==list('١٦')and ordered[0]['x']<ordered[1]['x']
    complete=same_line and correct_order
    out.mkdir(parents=True,exist_ok=True)
    pdf=pypdfium2.PdfDocument(file)
    for index in range(len(pdf)):pdf[index].render(scale=2).to_pil().save(out/f'page-{index+1:04d}.png')
    pdf.close()
    return {'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'markerCompleteSingleLine':complete,
            'markerDigitsLeftToRight':correct_order,'brackets':brackets,'bodyNativeDigits':digits,'enclosedDigitsInVisualOrder':ordered}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    root=args.root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'diagnosticOnly':True,'publicationAcceptance':False,'renderer':verify_packages(),'stages':{}}
    archive=base64.b64decode((root/'test-fixtures/books/rtl-marker-roundtrip.b64').read_text())
    if hashlib.sha256(archive).hexdigest()!=FIXTURE_SHA:raise ValueError('Citation regression fixture changed')
    with zipfile.ZipFile(io.BytesIO(archive))as bundle:
        if set(bundle.namelist())!={'source-prepared.docx','source.json'}:raise ValueError('Unexpected citation fixture members')
        original=bundle.read('source-prepared.docx');source=json.loads(bundle.read('source.json'))
    with zipfile.ZipFile(io.BytesIO(original))as bundle:parts={name:bundle.read(name)for name in bundle.namelist()}
    expected=literal_and_notes(parts)
    if expected[0]!=source['text']:raise ValueError('Citation fixture no longer matches its exact source paragraph')
    work=out/'work';work.mkdir();files=[]
    for name,indent in [('prepared',None),('rebuilt',0),('rebuilt-narrow4',80),('rebuilt-narrow8',160)]:
        content=dict(parts)
        if indent is not None:
            document=parse_xml(content['word/document.xml']);owner=Document();p=Paragraph(document.find(W+'body').find(W+'p'),owner._body)
            anchors=[deepcopy(r)for r in p._p.findall(W+'r')if r.find(W+'footnoteReference')is not None]
            if len(anchors)!=1:raise ValueError('Unexpected fixture note anchors')
            for child in list(p._p):
                if child.tag!=W+'pPr':p._p.remove(child)
            for segment in source['segments']:
                add_text(p,segment['text'],'ar','Iman Book Arabic','Iman Book Naskh',12,'body')
                if segment.get('note'):p._p.append(anchors.pop(0))
            if indent:
                properties=p._p.find(W+'pPr');ind=properties.find(W+'ind')
                if ind is None:ind=etree.SubElement(properties,W+'ind')
                ind.set(W+'left',str(indent))
            content['word/document.xml']=etree.tostring(document,xml_declaration=True,encoding='UTF-8',standalone=True)
        if literal_and_notes(content)!=expected:raise ValueError('Building the citation probe changed source content')
        file=work/(name+'.docx');files.append(file)
        with zipfile.ZipFile(file,'w',zipfile.ZIP_DEFLATED)as archive:
            for member,raw in content.items():archive.writestr(member,raw)
    (work/'index.json').write_text(json.dumps({'diagnosticOnly':True,'previewOnly':True,'books':[{'file':p.name,'language':'ar','collection':'articles'}for p in files]}))
    commands=[('roundtrip-1',['/usr/bin/python3','books/render_uno.py','--folder',str(work)]),
              ('roundtrip-2',['/usr/bin/python3','books/render_uno.py','--folder',str(work),'--keep-contents']),
              ('font-restored',[sys.executable,'books/restore_book_fonts.py','--root',str(root),'--folder',str(work)]),
              ('page-break-normalized',[sys.executable,'books/normalize_word_page_breaks.py','--folder',str(work)])]
    failures=[]
    for stage,command in commands:
        result=subprocess.run(command,cwd=root,capture_output=True,text=True)
        (out/(stage+'.log')).write_text(result.stdout+'\n'+result.stderr)
        if result.returncode:raise RuntimeError(stage+' failed: '+result.stderr[-2000:])
        rows={};report['stages'][stage]=rows
        for file in files:
            destination=out/stage/file.stem;destination.mkdir(parents=True)
            shutil.copy2(file,destination/file.name);pdf=file.with_suffix('.pdf');shutil.copy2(pdf,destination/pdf.name)
            exact=literal_and_notes(unpack(file))==expected
            row={'sourceBodyAndNotesExact':exact,'pdf':pdf_evidence(pdf,destination/'pages')};rows[file.stem]=row
            if not exact or not row['pdf']['markerCompleteSingleLine']:failures.append(stage+'/'+file.stem)
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    report['passed']=not failures;report['failures']=failures
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'passed':not failures,'renderer':report['renderer'],'failures':failures},ensure_ascii=False))
    if failures:raise ValueError('Citation marker split or source fidelity changed: '+', '.join(failures))


if __name__=='__main__':main()
