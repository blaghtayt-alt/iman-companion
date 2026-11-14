"""Download and hash advertised bytes even when source freshness is blocked.

Integrity is separate from approval and currency. No HEAD-only success, cached
registry claim, or successful web deployment substitutes for this body check.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse,unquote
from urllib.request import Request,urlopen
from xml.etree import ElementTree
import argparse,hashlib,json,re,sys,tempfile,zipfile

ROOT=Path(__file__).resolve().parents[1]
REPO='blaghtayt-alt/iman-companion'
MAX_BYTES=250_000_000


def inventory(catalog,bundles):
    items={}
    def add(language,collection,format,url,digest,**extra):
        if not re.fullmatch('[a-f0-9]{64}',digest or ''):raise ValueError('Missing advertised hash')
        parsed=urlparse(url)
        if (parsed.scheme!='https' or parsed.netloc!='github.com' or parsed.query or parsed.fragment
            or not parsed.path.startswith('/'+REPO+'/releases/download/')):raise ValueError('Untrusted download URL')
        if len(parsed.path.split('/'))!=7:raise ValueError('Invalid release asset path')
        filename=unquote(parsed.path.rsplit('/',1)[-1])
        if filename!=f'Iman_Companion_{language}_{collection}.{format}':raise ValueError('Download identity mismatch')
        row={'language':language,'collection':collection,'format':format,'url':url,'sha256':digest,**extra}
        if url in items and items[url]!=row:raise ValueError('Conflicting advertised download')
        items[url]=row
    for language,locale in catalog['languages'].items():
        for book in locale['books']:
            for format,field in [('docx','sha256'),('pdf','pdfSha256')]:
                add(language,book['collection'],format,book[format],book[field])
        bundle=bundles.get('languages',{}).get(language)
        if not bundle:continue
        members={f"Iman_Companion_{language}_{part['collection']}.{format}":part[field]
                 for part in bundle['parts'] for format,field in [('docx','sha256'),('pdf','pdfSha256')]}
        for asset in bundle['assets']:
            format=asset['name'].rsplit('.',1)[-1]
            url=f"https://github.com/{REPO}/releases/download/{bundle['releaseTag']}/{asset['name']}"
            if locale.get('bundle',{}).get(format)!=url:raise ValueError('Bundle link differs from its exact manifest')
            add(language,'all-books',format,url,asset['sha256'],bytes=asset['bytes'],**({'members':members} if format=='zip' else {}))
    return list(items.values())


def inspect(item,*,opener=urlopen,contracts=None):
    result={**{k:v for k,v in item.items() if k!='members'},'integrity':'failed'}
    try:
        with tempfile.TemporaryFile() as stream:
            digest=hashlib.sha256();size=0
            with opener(Request(item['url'],headers={'Cache-Control':'no-cache','User-Agent':'Iman-book-byte-audit/1'}),timeout=60) as response:
                if response.status!=200:raise ValueError('Body download did not return HTTP 200')
                if urlparse(response.geturl()).hostname not in {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}:
                    raise ValueError('Unexpected download redirect host')
                while chunk:=response.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES:raise ValueError('Download exceeds bounded book size')
                    digest.update(chunk);stream.write(chunk)
                result['etag']=response.headers.get('ETag')
                result['lastModified']=response.headers.get('Last-Modified')
                result['finalHost']=urlparse(response.geturl()).hostname
            result.update(downloadedSHA256=digest.hexdigest(),downloadedBytes=size)
            if digest.hexdigest()!=item['sha256'] or ('bytes'in item and size!=item['bytes']):raise ValueError('Actual downloadable bytes differ from the published hash/size')
            stream.seek(0)
            if item['format'] in {'zip','docx'}:
                with zipfile.ZipFile(stream) as archive:
                    names=archive.namelist()
                    if len(names)!=len(set(names)) or sum(i.file_size for i in archive.infolist())>MAX_BYTES*4:
                        raise ValueError('Duplicate or oversized ZIP contents')
                    if archive.testzip():raise ValueError('ZIP CRC failure')
                    if item['format']=='zip':
                        if set(names)!=set(item['members']):raise ValueError('Combined ZIP omits or adds book members')
                        actual={n:hashlib.sha256(archive.read(n)).hexdigest() for n in names}
                        if actual!=item['members']:raise ValueError('Combined ZIP contains different book bytes')
                        result['memberSHA256']=actual
                    else:
                        doc=ElementTree.fromstring(archive.read('word/document.xml'))
                        namespace='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                        text='\n'.join(''.join(t.text or '' for t in p.iter(namespace+'t')) for p in doc.iter(namespace+'p'))
                        contract=(contracts or {}).get(item['language']) if item['collection']=='tadabbur-extended' else None
                        if contract:
                            result['textComparison']={key:contract[field] in text for key,field in [('beforePresent','before'),('afterPresent','after')]}
                            result['textComparison'].update({key:contract.get(field,contract[fallback]) in text for key,field,fallback in [('beforeProbePresent','beforeProbe','before'),('afterProbePresent','afterProbe','after')]})
                            result['textComparison']['evidence']='Exact Unicode substring in downloaded word/document.xml'
            elif item['format']=='pdf':
                if stream.read(5)!=b'%PDF-':raise ValueError('Download is not PDF bytes')
                stream.seek(0)
                from pypdf import PdfReader
                result['pages']=len(PdfReader(stream).pages)
                if result['pages']<1:raise ValueError('PDF has no pages')
            else:raise ValueError('Unsupported book format')
            result['integrity']='passed'
    except Exception as error:result['error']=str(error)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--json',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--language',action='append')
    args=parser.parse_args();root=args.root.resolve()
    items=inventory(json.loads((root/'docs/books/catalog.json').read_bytes()),json.loads((root/'books/published-bundles.json').read_bytes()))
    if args.language:items=[i for i in items if i['language']in args.language]
    path=root/'books/regressions/source-propagation-20261114.json'
    contracts=json.loads(path.read_bytes())['fatiha'] if path.is_file() else {}
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,8))) as pool:
        rows=list(pool.map(lambda item:inspect(item,contracts=contracts),items))
    report={'schema':'iman-live-book-byte-audit-v1','observedAt':datetime.now(timezone.utc).isoformat(),
            'integrityPassed':all(r['integrity']=='passed' for r in rows),'downloads':rows,
            'sourceCurrencyVerified':False,'releaseApprovalCreated':False,
            'limitations':['Hash integrity does not establish source currency or approval.','Word execution and visual acceptance are not performed by this audit.']}
    args.json.parent.mkdir(parents=True,exist_ok=True);args.json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'downloads':len(rows),'integrityPassed':report['integrityPassed']}))
    return 0 if report['integrityPassed'] else 1


if __name__=='__main__':raise SystemExit(main())
