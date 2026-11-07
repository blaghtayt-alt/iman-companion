"""Consume exact approved source transactions from the existing source-push job.

Source publishers commit handoffs under materials/book-publication-intake.
Raw translations are never converted into approvals. Each accepted transaction
retains its original review identities, all conditions and exact reader bytes.
"""
from pathlib import Path
import argparse,json
from published_library import read,sha,inside
from publish_approved_material import apply,atomic,bytes_json,key

HISTORY='materials/book-publication-intake-history'

def process(root):
    base=sha((root/'materials/catalog.json').read_bytes())
    report={'schema':'iman-book-publication-intake-report-v1','accepted':[],'unchanged':[],'errors':[],'generatedFiles':[],'sourceApprovalCreated':False}
    pending=[];identities={}
    for file in sorted((root/'materials/book-publication-intake').glob('*.json')):
        raw=file.read_bytes();digest=sha(raw);history=f'{HISTORY}/{digest}.json'
        try:
            if (root/history).exists():
                prior=read(root/history)
                if prior.get('intakeSHA256')!=digest:raise ValueError('Intake history binding differs')
                report['unchanged'].append(file.relative_to(root).as_posix());continue
            data=json.loads(raw)
            if data.get('schema')!='iman-approved-material-publication-v1':raise ValueError('Intake requires an explicit approved-material publication handoff')
            identity=key(data.get('catalogEntry',{}));identities.setdefault(identity,[]).append(digest)
            pending.append((file,digest,history,identity))
        except Exception as error:report['errors'].append({'path':file.relative_to(root).as_posix(),'error':str(error)})
    conflicts={k for k,v in identities.items() if len(set(v))>1};seen=set()
    for file,digest,history,identity in pending:
        if digest in seen:continue
        seen.add(digest)
        try:
            if identity in conflicts:raise ValueError('Conflicting pending transactions for the same material; neither was applied')
            receipt=apply(root,file,transaction_base=base)
            receipt.update({'intakeSHA256':digest,'intakePath':file.relative_to(root).as_posix()})
            atomic(inside(root,history),bytes_json(receipt))
            report['accepted'].append(receipt)
            report['generatedFiles']+=receipt['generatedFiles']+[history]
        except Exception as error:report['errors'].append({'path':file.relative_to(root).as_posix(),'error':str(error)})
    report['generatedFiles']=sorted(set(report['generatedFiles']))
    target=root/'books/.cache/material-intake-report.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes_json(report))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(process(args.root.resolve()),ensure_ascii=False))
