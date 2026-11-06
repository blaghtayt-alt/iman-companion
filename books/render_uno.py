"""Run with the Linux system Python with python3-uno installed.

Refresh Word contents/page fields and render PDFs using a dedicated LibreOffice
profile. Output Word files retain editable text and embedded fonts.
"""
from pathlib import Path
import argparse,subprocess,tempfile,time,socket,json
import uno
from com.sun.star.beans import PropertyValue
def prop(k,v):p=PropertyValue();p.Name=k;p.Value=v;return p
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--keep-contents',action='store_true');args=ap.parse_args();folder=args.folder.resolve()
    languages={b['file']:b['language'] for b in json.loads((folder/'index.json').read_text(encoding='utf-8'))['books']}
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with tempfile.TemporaryDirectory() as temp:
        profile=Path(temp)/'profile';process=subprocess.Popen(['soffice','-env:UserInstallation='+profile.as_uri(),'--headless','--norestore','--nodefault','--nofirststartwizard',f'--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        desktop=None
        try:
            local=uno.getComponentContext();resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                try:context=resolver.resolve(f'uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext');break
                except Exception:time.sleep(.3)
            else:raise RuntimeError('LibreOffice did not start')
            desktop=context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',context)
            for file in sorted(folder.glob('*.docx')):
                doc=desktop.loadComponentFromURL(file.as_uri(),'_blank',0,(prop('Hidden',True),prop('ReadOnly',False),prop('UpdateDocMode',3)))
                if doc is None:raise RuntimeError('Cannot open '+str(file))
                try:
                    doc.getTextFields().refresh();indexes=doc.getDocumentIndexes()
                    if not args.keep_contents:
                        for i in range(indexes.getCount()):indexes.getByIndex(i).update()
                    if languages[file.name] in {'ar','ur','fa'}:
                        center=uno.Enum('com.sun.star.style.ParagraphAdjust','CENTER');right=uno.Enum('com.sun.star.style.ParagraphAdjust','RIGHT')
                        paragraphs=doc.getText().createEnumeration()
                        while paragraphs.hasMoreElements():
                            paragraph=paragraphs.nextElement()
                            if paragraph.supportsService('com.sun.star.text.Paragraph'):
                                keep_center=(paragraph.ParaAdjust==center)
                                paragraph.WritingMode=uno.getConstantByName('com.sun.star.text.WritingMode2.RL_TB')
                                paragraph.ParaAdjust=center if keep_center else right
                    doc.calculateAll() if hasattr(doc,'calculateAll') else None
                    doc.store()
                    doc.storeToURL(file.with_suffix('.pdf').as_uri(),(prop('FilterName','writer_pdf_Export'),prop('Overwrite',True)))
                finally:doc.close(True)
        finally:
            if desktop:desktop.terminate()
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
if __name__=='__main__':main()
