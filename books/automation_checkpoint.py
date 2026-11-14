"""Persist only validated intake outputs or freshness status, with a HEAD lease.

No source approval, review receipt or release is created here. A collision stops
the write; a later run recomputes from the new HEAD instead of replaying old bytes.
"""
from pathlib import Path
import argparse,json,os,re,subprocess
from material_publication_intake import process
from publish_approved_material import atomic,bytes_json
from source_update_status import audit,write_public,PUBLIC_PATH


def run(root,args):
    result=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True,check=True)
    return result.stdout.strip()


def commit_files(root,expected,paths,message):
    if not re.fullmatch('[a-f0-9]{40}',expected):raise ValueError('Invalid expected HEAD')
    if run(root,['rev-parse','HEAD'])!=expected:raise ValueError('Local HEAD advanced; recompute')
    if run(root,['diff','--cached','--name-only']):raise ValueError('Checkpoint refuses unrelated staged changes')
    allowed={'materials/catalog.json','books/reviewed-books.json','materials/README.md',PUBLIC_PATH}
    prefixes=('books/units/current/','books/units/history/','materials/book-publication-approvals/',
              'materials/book-publication-intake-history/','materials/audio/')
    paths=sorted(set(paths))
    for relative in paths:
        path=(root/relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or (relative not in allowed and not relative.startswith(prefixes)):
            raise ValueError('Unexpected checkpoint path: '+relative)
    remote=run(root,['ls-remote','origin','refs/heads/main']).split()
    if not remote or remote[0]!=expected:raise ValueError('Main advanced; recompute the transaction from the new HEAD')
    if paths:run(root,['add','--',*paths])
    changed=run(root,['diff','--cached','--name-only']).splitlines()
    if not set(changed).issubset(paths):raise ValueError('Unexpected staged checkpoint path')
    if changed:
        run(root,['-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m',message])
        # Normal fast-forward push provides the second, server-side race check.
        run(root,['push','origin','HEAD:refs/heads/main'])
    return run(root,['rev-parse','HEAD'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['intake','status'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--commit',action='store_true')
    args=parser.parse_args();root=args.root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    expected=run(root,['rev-parse','HEAD']);files=[];intake=None
    if args.action=='intake':
        intake=process(root);files+=intake['generatedFiles']
        from update_source_inventory import refresh
        files+=refresh(root)
        atomic(out/'source-intake.json',bytes_json(intake))
    report=audit(root);write_public(root,report);files.append(PUBLIC_PATH)
    atomic(out/'source-update-status.json',bytes_json(report))
    head=commit_files(root,expected,files,'Record approved book intake and pending source updates') if args.commit else expected
    result={'commit':head,'summary':report['summary'],'intakeErrors':len(intake['errors']) if intake else 0,
            'sourceApprovalCreated':False,'releaseApprovalCreated':False}
    atomic(out/'checkpoint.json',bytes_json(result))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('commit='+head+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
