"""Prepare the root README and native download pages after assets are verified.

This edits only a checkout. The integration workflow owns the subsequent commit.
"""
from pathlib import Path
import argparse,json
from download_tables import render,merge_readme,verified_books

def prepare(root,folder,repo,tag,commit):
    index=json.loads((folder/'index.json').read_text(encoding='utf-8'))
    if index.get('sourceCommit')!=commit:raise ValueError('README links do not match the source checkout')
    if index.get('previewOnly') is not False:raise ValueError('A verified production export is required; internal previews cannot be the library')
    if not verified_books(index,folder,repo,tag):raise ValueError('No verified Word/PDF download pairs')
    conf=json.loads((root/'books/config.json').read_text(encoding='utf-8'));table,pages=render(conf,index,folder,repo,tag)
    readme=root/'README.md';readme.write_text(merge_readme(readme.read_text(encoding='utf-8'),table),encoding='utf-8')
    for lang,page in pages.items():
        target=root/'books/downloads'/lang/'README.md';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(page,encoding='utf-8')
    return len(pages)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--repo',required=True);ap.add_argument('--tag',required=True);ap.add_argument('--commit',required=True);args=ap.parse_args()
    print(json.dumps({'preparedNativePages':prepare(args.root,args.folder,args.repo,args.tag,args.commit),'rootReadmeUpdated':True}))
if __name__=='__main__':main()
