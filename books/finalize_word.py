"""Reconcile Word contents against actual Word; keep the PDF independent.

Run on Windows with pywin32 and an installed Microsoft Word. This creates an
exact-file operational readback, never a source/translation approval.
"""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from copy import deepcopy
import argparse,hashlib,json,os,shutil,subprocess,tempfile,time,re
from lxml import etree
from locale_copy import COPY,NATIVE_DIGITS
from word_layout_check import contents,verify,W

def processes():
    return{int(n)for n in subprocess.check_output(['powershell','-NoProfile','-Command','(Get-Process WINWORD -ErrorAction SilentlyContinue).Id']).split()}

def _finalize_staged(file,language,proof_dir=None,root=None):
    import win32com.client
    if language not in COPY:raise ValueError('Unknown book language')
    file=file.resolve();native_footer=None
    if language in {'ar','ur','fa'}:
        if root is None:raise ValueError('Native Word pagination requires --root with pinned numeral fonts')
        if proof_dir is None:raise ValueError('Native Word pagination requires --proof-dir for actual printed glyph checks')
        from native_word_footer import prepare
        native_footer=prepare(file,root.resolve(),language)
    before=processes();app=win32com.client.DispatchEx('Word.Application');time.sleep(1)
    if len(processes()-before)!=1:raise RuntimeError('Cannot establish a separate owned Word process')
    history=[]
    try:
        app.Visible=False;app.DisplayAlerts=0;app.AutomationSecurity=3;engine={'application':'Microsoft Word','version':str(app.Version),'build':str(app.Build)}
        for attempt in range(4):
            with ZipFile(file)as z:
                names=z.namelist()
                if len(names)!=len(set(names)):raise ValueError('Duplicate document parts; preserve input')
                parts={n:z.read(n)for n in names}
            document_root=etree.fromstring(parts['word/document.xml']);rows=contents(document_root);doc=app.Documents.Open(str(file),ReadOnly=True,AddToRecentFiles=False,Visible=False,ConfirmConversions=False)
            try:
                pages=doc.ComputeStatistics(2);checked=[]
                for row in rows:
                    if not doc.Bookmarks.Exists(row['anchor']):raise ValueError('Actual Word bookmark is missing')
                    target=doc.Bookmarks.Item(row['anchor']).Range
                    checked.append({**row,'actualPage':int(target.Information(1)),'physicalPage':int(target.Information(3))})
                passed=all(x['cachedPage']==x['actualPage']for x in checked);history.append({'attempt':attempt+1,'pages':pages,'contents':checked,'pass':passed})
                if passed and proof_dir is not None:
                    proof_dir.mkdir(parents=True,exist_ok=True);doc.ExportAsFixedFormat(str((proof_dir/'Word-visual-proof.pdf').resolve()),17)
            finally:doc.Close(False)
            if passed:break
            targets={x['anchor']:x['actualPage']for x in checked};native=str.maketrans('0123456789',NATIVE_DIGITS.get(language,'0123456789'));old=deepcopy(document_root)
            def cache_nodes(body):
                for p in body.iter(W+'p'):
                    style=p.find('./'+W+'pPr/'+W+'pStyle')
                    if style is None or not re.fullmatch(r'TOC\s*[1-9]',style.get(W+'val','')):continue
                    link=p.find('.//'+W+'hyperlink');nodes=list(link.iter());last=max(i for i,n in enumerate(nodes)if n.tag==W+'tab');value=next(n for n in nodes[last+1:]if n.tag==W+'t'and(n.text or'').strip());yield link.get(W+'anchor'),value
            for anchor,node in cache_nodes(document_root):node.text=str(targets[anchor]).translate(native)
            # Apart from numeric furniture, the complete XML and every other
            # package part stay byte-identical to the renderer's checked file.
            restored=deepcopy(document_root)
            for(_,node),(_,original)in zip(cache_nodes(restored),cache_nodes(old)):node.text=original.text
            if etree.tostring(restored)!=etree.tostring(old):raise ValueError('Unexpected non-cache Word edit')
            parts['word/document.xml']=etree.tostring(document_root,xml_declaration=True,encoding='UTF-8',standalone=True)
            with ZipFile(file,'w',ZIP_DEFLATED)as z:
                for name,raw in parts.items():z.writestr(name,raw)
        else:raise ValueError('Word contents failed to converge')
    finally:app.Quit(False)
    receipt={'schema':'iman-word-layout-readback-v1','scope':'Actual final-file Word pagination; no source review, rights, scholarly approval or hosted Windows CI runner is implied.','language':language,'docxSHA256':hashlib.sha256(file.read_bytes()).hexdigest(),'engine':engine,'readOnly':True,'savedByWord':False,'pages':pages,'contents':checked,'history':history}
    if native_footer:
        from native_word_footer import verify_rendered_footer
        native_footer['actualWordOutput']=verify_rendered_footer(proof_dir/'Word-visual-proof.pdf',root.resolve(),language)
        receipt['nativeFooter']=native_footer
    sidecar=file.with_name(file.name+'.word-layout.json');sidecar.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8');verify(file,sidecar);return receipt

def finalize(file,language,proof_dir=None,root=None):
    # Word and footer changes happen in an isolated copy. Never replace a
    # candidate that changed while Word was being checked.
    file=file.resolve();original_hash=hashlib.sha256(file.read_bytes()).hexdigest()
    sidecar=file.with_name(file.name+'.word-layout.json')
    old_sidecar=sidecar.read_bytes() if sidecar.exists() else None
    with tempfile.TemporaryDirectory(dir=file.parent,prefix='.word-finalize-') as tmp:
        temporary=Path(tmp);staged=temporary/file.name;backup=temporary/'original.docx';shutil.copy2(file,staged);shutil.copy2(file,backup)
        staged_proof=temporary/'proof' if proof_dir is not None else None
        receipt=_finalize_staged(staged,language,staged_proof,root)
        staged_sidecar=staged.with_name(staged.name+'.word-layout.json');verify(staged,staged_sidecar)
        if hashlib.sha256(file.read_bytes()).hexdigest()!=original_hash:raise ValueError('Input changed during Word verification; preserve the newer file')
        if (sidecar.read_bytes() if sidecar.exists() else None)!=old_sidecar:raise ValueError('Word receipt changed during verification')
        if proof_dir is not None:
            proof_dir=Path(proof_dir);proof_dir.mkdir(parents=True,exist_ok=True);source=staged_proof/'Word-visual-proof.pdf';target=proof_dir/source.name
            if target.exists():
                if target.read_bytes()!=source.read_bytes():raise ValueError('Existing Word proof differs; preserve it')
            else:
                fd,proof_temp=tempfile.mkstemp(dir=proof_dir,suffix='.pdf');os.close(fd)
                try:shutil.copyfile(source,proof_temp);os.replace(proof_temp,target)
                finally:
                    if os.path.exists(proof_temp):os.unlink(proof_temp)
        os.replace(staged,file)
        try:os.replace(staged_sidecar,sidecar)
        except Exception:
            os.replace(backup,file)
            raise
        return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--docx',type=Path,required=True);p.add_argument('--language',required=True);p.add_argument('--proof-dir',type=Path);p.add_argument('--root',type=Path);a=p.parse_args();print(json.dumps(finalize(a.docx,a.language,a.proof_dir,a.root),ensure_ascii=False))
