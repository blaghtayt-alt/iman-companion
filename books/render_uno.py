"""Run with the Linux system Python with python3-uno installed.

Refresh Word contents/page fields and render PDFs using a dedicated LibreOffice
profile. Output Word files retain editable text and embedded fonts.
"""
from pathlib import Path
import argparse,subprocess,tempfile,time,socket,json
import uno
from renderer_pin import verify_renderer
from toc_hyperlinks import read_cached_contents,refresh_cached_contents,verify_cached_contents
from com.sun.star.beans import PropertyValue
def prop(k,v):p=PropertyValue();p.Name=k;p.Value=v;return p
def native_footer(doc,language):
    """Use a live page field in this isolated LibreOffice renderer profile."""
    # Urdu and Persian both use Persian digits; LibreOffice's ur-PK native
    # numbering is ASCII, so use its Persian numeral locale for this field.
    locales={'ar':('ar','SA'),'ur':('fa','IR'),'fa':('fa','IR')}
    if language not in locales:return
    loc=uno.createUnoStruct('com.sun.star.lang.Locale');loc.Language,loc.Country=locales[language]
    styles=doc.getStyleFamilies().getByName('PageStyles')
    for name in styles.getElementNames():
        style=styles.getByName(name)
        if not style.FooterIsOn:continue
        footer=style.FooterText;footer.String='';cursor=footer.createTextCursor()
        cursor.CharLocale=loc;cursor.CharLocaleComplex=loc
        cursor.ParaAdjust=uno.Enum('com.sun.star.style.ParagraphAdjust','CENTER')
        number=doc.createInstance('com.sun.star.text.TextField.PageNumber');number.NumberingType=12
        footer.insertTextContent(cursor,number,False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--keep-contents',action='store_true');args=ap.parse_args();folder=args.folder.resolve()
    verify_renderer()
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
                cached=read_cached_contents(file) if args.keep_contents else None
                doc=desktop.loadComponentFromURL(file.as_uri(),'_blank',0,(prop('Hidden',True),prop('ReadOnly',False),prop('UpdateDocMode',0 if args.keep_contents else 3)))
                if doc is None:raise RuntimeError('Cannot open '+str(file))
                try:
                    indexes=doc.getDocumentIndexes()
                    doc.getTextFields().refresh()
                    if languages[file.name] in {'ar','ur','fa'}:
                        center=uno.Enum('com.sun.star.style.ParagraphAdjust','CENTER');right=uno.Enum('com.sun.star.style.ParagraphAdjust','RIGHT')
                        paragraphs=doc.getText().createEnumeration()
                        while paragraphs.hasMoreElements():
                            paragraph=paragraphs.nextElement()
                            if paragraph.supportsService('com.sun.star.text.Paragraph'):
                                keep_center=(paragraph.ParaAdjust==center)
                                paragraph.WritingMode=uno.getConstantByName('com.sun.star.text.WritingMode2.RL_TB')
                                paragraph.ParaAdjust=center if keep_center else right
                    native_footer(doc,languages[file.name])
                    doc.calculateAll() if hasattr(doc,'calculateAll') else None
                    if not args.keep_contents:
                        # Contents must reflect the final paragraph direction,
                        # footer and complete layout, including long footnotes.
                        # Updating the index first leaves stale Urdu page caches.
                        previous=None;cursor=doc.getCurrentController().getViewCursor()
                        for attempt in range(5):
                            cursor.jumpToLastPage();page_count=cursor.getPage();cursor.jumpToFirstPage()
                            doc.getTextFields().refresh()
                            for i in range(indexes.getCount()):indexes.getByIndex(i).update()
                            state=(page_count,tuple(indexes.getByIndex(i).getAnchor().getString()for i in range(indexes.getCount())))
                            if state==previous:break
                            previous=state
                        else:raise ValueError('Contents pagination did not converge')
                    else:
                        # Native DOCX import drops cached TOC links. Regenerate their
                        # real targets while retaining exact reconciled page labels.
                        refresh_cached_contents(doc,cached)
                    doc.store()
                    if cached is not None:verify_cached_contents(file,cached)
                    doc.storeToURL(file.with_suffix('.pdf').as_uri(),(prop('FilterName','writer_pdf_Export'),prop('Overwrite',True)))
                finally:doc.close(True)
        finally:
            if desktop:desktop.terminate()
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
if __name__=='__main__':main()
