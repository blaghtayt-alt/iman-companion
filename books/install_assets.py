from pathlib import Path
import json,hashlib,urllib.request,zipfile,shutil,argparse,tempfile
import os,re,subprocess,time,urllib.parse

METADATA_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300
PUBLIC_READ_TIMEOUT = 60


class AssetDownloadError(RuntimeError):
    pass


def _gh_api(endpoint, accept, *, timeout, output=None):
    # Keep credentials in the inherited environment, never in argv or errors.
    command = ['gh', 'api', '--hostname', 'github.com', endpoint, '-H', f'Accept: {accept}']
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                stdout=output if output is not None else subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise AssetDownloadError(f'GitHub asset request timed out after {timeout} seconds') from None
    except OSError:
        raise AssetDownloadError('Authenticated asset download requires the GitHub CLI (gh)') from None
    if result.returncode:
        # gh stderr may contain a signed redirect URL; report only the status.
        status = re.search(rb'\bHTTP (\d{3})\b', result.stderr or b'')
        detail = f' (HTTP {status.group(1).decode()})' if status else ''
        raise AssetDownloadError(f'GitHub asset request failed{detail}')
    return result.stdout


def _github_release(url):
    parsed = urllib.parse.urlsplit(url)
    parts = parsed.path.strip('/').split('/')
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or parsed.query or parsed.fragment or len(parts) != 6
            or parts[2:4] != ['releases', 'download']
            or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in parts[:2])):
        return None
    owner, repo = parts[:2]
    tag, name = (urllib.parse.unquote(part) for part in parts[4:])
    if not tag or not name:
        return None
    return f'repos/{owner}/{repo}', tag, name


def download_archive(url, destination):
    release = _github_release(url)
    if os.environ.get('GH_TOKEN') and release:
        repo, tag, name = release
        raw = _gh_api(f'{repo}/releases/tags/{urllib.parse.quote(tag, safe="")}',
                      'application/vnd.github+json', timeout=METADATA_TIMEOUT)
        try:
            metadata = json.loads(raw)
        except (ValueError, TypeError):
            raise AssetDownloadError('Invalid GitHub release metadata') from None
        if (not isinstance(metadata, dict) or metadata.get('tag_name') != tag
                or not isinstance(metadata.get('assets'), list)):
            raise AssetDownloadError('GitHub release metadata does not match the pinned tag')
        matches = [asset for asset in metadata['assets'] if isinstance(asset, dict)
                   and asset.get('name') == name and asset.get('browser_download_url') == url]
        if len(matches) != 1 or type(matches[0].get('id')) is not int or matches[0]['id'] <= 0:
            raise AssetDownloadError('GitHub release must contain exactly one matching pinned asset')
        with destination.open('wb') as output:
            _gh_api(f'{repo}/releases/assets/{matches[0]["id"]}',
                    'application/octet-stream', timeout=DOWNLOAD_TIMEOUT, output=output)
        return

    # The original public URL remains usable without gh or a token. read1 checks
    # the total deadline between socket reads, each bounded by the read timeout.
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    with urllib.request.urlopen(url, timeout=PUBLIC_READ_TIMEOUT) as response, destination.open('wb') as output:
        while True:
            if time.monotonic() >= deadline:
                raise AssetDownloadError('Public asset download exceeded its transfer deadline')
            chunk = response.read1(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path('.'));args=ap.parse_args();root=args.root.resolve()
    conf=json.loads((root/'books/assets.json').read_text(encoding='utf-8'))
    for entry in conf['archives']:
        target=root/entry['destination'];target.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'assets.zip';download_archive(entry['url'],file)
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
