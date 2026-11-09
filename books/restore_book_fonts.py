"""Restore pinned fonts and exact reviewed link targets after LibreOffice save."""
from pathlib import Path
import argparse,json
from font_integrity import restore,verify
from restore_source_hyperlinks import restore as restore_source_hyperlinks

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--folder',type=Path,required=True);a=p.parse_args();root=a.root.resolve();folder=a.folder.resolve();conf=json.loads((root/'books/config.json').read_text(encoding='utf8'));index=json.loads((folder/'index.json').read_text(encoding='utf8'))
    links_restored=0
    for book in index['books']:
        file=folder/book['file']
        if file.parent!=folder or not file.is_file():raise ValueError('Invalid indexed book path')
        restore(file,conf,book['language'],root);verify(file,conf,book['language'])
        checks_file=folder/(file.name+'.reader-checks.json')
        checks=json.loads(checks_file.read_text(encoding='utf8')) if checks_file.is_file() else {}
        links_restored+=restore_source_hyperlinks(file,checks.get('sourceHyperlinks',[]) if isinstance(checks,dict) else [],book['language'],root)
    print(json.dumps({'fontRestoredBooks':len(index['books']),'sourceHyperlinkTargetsRestored':links_restored}))
if __name__=='__main__':main()
