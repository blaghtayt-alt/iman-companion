from pathlib import Path
import json,hashlib,urllib.request,zipfile,shutil,argparse,tempfile
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path('.'));args=ap.parse_args();root=args.root.resolve()
    conf=json.loads((root/'books/assets.json').read_text(encoding='utf-8'))
    for entry in conf['archives']:
        target=root/entry['destination'];target.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'assets.zip';urllib.request.urlretrieve(entry['url'],file)
            if hashlib.sha256(file.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Asset archive hash mismatch')
            with zipfile.ZipFile(file) as z:
                for name in z.namelist():
                    member=z.getinfo(name)
                    if member.is_dir():continue
                    dest=(target/name).resolve()
                    if target.resolve() not in dest.parents:raise ValueError('Archive path escapes destination')
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(member) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
if __name__=='__main__':main()
