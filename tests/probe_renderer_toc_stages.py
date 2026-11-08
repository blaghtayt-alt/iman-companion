"""Diagnostic only: locate keep-contents link loss without accepting any book."""
from pathlib import Path
import argparse
import json
import sys

from lxml import etree
from check_renderer_toc import exercise, read_parts, style, tag, TOC


TRACE = '''
def trace_contents(doc, stage, keep):
    rows=[]; paragraphs=doc.getText().createEnumeration()
    while paragraphs.hasMoreElements():
        paragraph=paragraphs.nextElement()
        if not paragraph.supportsService('com.sun.star.text.Paragraph'):continue
        portions=paragraph.createEnumeration(); links=[]
        while portions.hasMoreElements():
            portion=portions.nextElement()
            info=portion.getPropertySetInfo()
            if info.hasPropertyByName('HyperLinkURL'):
                url=portion.getPropertyValue('HyperLinkURL')
                if url:links.append({'text':portion.getString(),'url':url})
        rows.append({'style':paragraph.ParaStyleName,'text':paragraph.getString(),'links':links})
    formats=[]; indexes=doc.getDocumentIndexes()
    for i in range(indexes.getCount()):
        index=indexes.getByIndex(i)
        if index.getServiceName()!='com.sun.star.text.ContentIndex':continue
        levels=index.LevelFormat
        formats.append([[next(p.Value for p in token if p.Name=='TokenType')
                         for token in levels.getByIndex(n)]
                        for n in range(1,min(levels.getCount(),3))])
    print(json.dumps({'tocTrace':True,'stage':stage,'keepContents':keep,'rows':rows,
                      'formats':formats,'bookmarks':list(doc.getBookmarks().getElementNames())},ensure_ascii=True),flush=True)
'''


def instrument(source, variant):
    if variant == 'skip-field-refresh':
        old = '\n                    doc.getTextFields().refresh()\n'
        assert source.count(old) == 1
        source = source.replace(old, '\n                    if not args.keep_contents:doc.getTextFields().refresh()\n')
    elif variant == 'update-index':
        old = '                    native_footer(doc,languages[file.name])'
        source = source.replace(old, old + '\n                    if args.keep_contents:\n                        for i in range(indexes.getCount()):indexes.getByIndex(i).update()')
    source = source.replace('\ndef main():', TRACE + '\ndef main():')
    old = '                    indexes=doc.getDocumentIndexes()'
    source = source.replace(old, '                    trace_contents(doc,"loaded",args.keep_contents)\n' + old)
    old = '                    ensure_contents_hyperlinks(indexes,uno,prop)'
    source = source.replace(old, old + '\n                    trace_contents(doc,"after-format",args.keep_contents)')
    old = '                    if languages[file.name] in'
    source = source.replace(old, '                    trace_contents(doc,"after-fields",args.keep_contents)\n' + old)
    old = '                    doc.store()'
    source = source.replace(old, '                    trace_contents(doc,"before-store",args.keep_contents)\n' + old + '\n                    trace_contents(doc,"after-store",args.keep_contents)')
    return source


def raw_labels(file):
    body = etree.fromstring(read_parts(file)['word/document.xml']); result = []
    for p in body.iter(tag('p')):
        if style(p) not in TOC:continue
        nodes=list(p.iter());tabs=[i for i,n in enumerate(nodes) if n.tag==tag('tab')]
        values=[n.text.strip() for n in nodes[tabs[-1]+1:] if n.tag==tag('t') and (n.text or '').strip()]
        assert len(values)==1, values
        result.append(values[0])
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    root=args.root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=(root/'books/render_uno.py').read_text(encoding='utf-8')
    report={'schema':'iman-toc-stage-probe-v1','publicationAcceptance':False,'variants':[]}
    for variant in ('current','skip-field-refresh','update-index'):
        renderer=out/(variant+'-renderer.py');renderer.write_text(instrument(source,variant),encoding='utf-8')
        result={'variant':variant,**exercise(root,out/variant,renderer,'ar',False)}
        before=raw_labels(out/variant/'first-pass'/'toc-ar.docx')
        expected=[n.translate(str.maketrans('0123456789','٠١٢٣٤٥٦٧٨٩')) for n in before]
        after=raw_labels(out/variant/'input'/'toc-ar.docx')
        result.update({'expectedKeepLabels':expected,'actualKeepLabels':after,'cachedLabelsPreserved':expected==after})
        report['variants'].append(result)
        (out/'stage-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
