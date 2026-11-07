"""Restore pinned fonts after the final LibreOffice save, without changing text."""
from pathlib import Path
import argparse,json
from font_integrity import restore,verify

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--folder',type=Path,required=True);a=p.parse_args();root=a.root.resolve();folder=a.folder.resolve();conf=json.loads((root/'books/config.json').read_text(encoding='utf8'));index=json.loads((folder/'index.json').read_text(encoding='utf8'))
    for book in index['books']:
        file=folder/book['file']
        if file.parent!=folder or not file.is_file():raise ValueError('Invalid indexed book path')
        restore(file,conf,book['language'],root);verify(file,conf,book['language'])
    print(json.dumps({'fontRestoredBooks':len(index['books'])}))
if __name__=='__main__':main()
