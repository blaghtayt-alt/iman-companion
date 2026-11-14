"""Exact historical inputs for code regressions, never current approval.

CI explicitly fetches this existing commit. Production selection always reads
the live checkout; only temporary test roots receive these historical bytes.
"""
from pathlib import Path
import hashlib,subprocess

QURAN_FIXTURE_COMMIT='80c666acc4ca8c87f6f6b0fc2df82be31b4f4792'


def pinned_fixture(repo,relative,digest,commit=QURAN_FIXTURE_COMMIT):
    path=repo/relative
    raw=path.read_bytes() if path.is_file() else None
    if raw is None or hashlib.sha256(raw).hexdigest()!=digest:
        result=subprocess.run(['git','show',commit+':'+relative],cwd=repo,capture_output=True,check=True)
        raw=result.stdout
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Historical test fixture does not match its review pin: '+relative)
    return raw


def copy_projection_fixture(repo,destination,inventory,extra_paths=()):
    pins={}
    for record in inventory['records']:
        for binding in record['sourceFiles']+record['sourceConditions']:
            if binding['path'] in pins and pins[binding['path']]!=binding['sha256']:raise ValueError('Conflicting fixture pins')
            pins[binding['path']]=binding['sha256']
    for relative in set(pins)|set(extra_paths):
        path=destination/relative;path.parent.mkdir(parents=True,exist_ok=True)
        if relative in pins:raw=pinned_fixture(repo,relative,pins[relative],inventory['sourceCommit'])
        elif relative=='materials/catalog.json':
            # Live approved successors must not change an historical fixture's
            # membership or add current-only reader bindings to that fixture.
            raw=subprocess.run(['git','show',inventory['sourceCommit']+':'+relative],cwd=repo,capture_output=True,check=True).stdout
        else:raw=(repo/relative).read_bytes()
        path.write_bytes(raw)
