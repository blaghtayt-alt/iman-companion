"""Exact historical inputs for code regressions, never current approval.

CI explicitly fetches this existing commit. Production selection always reads
the live checkout; only temporary test roots receive these historical bytes.
"""
from pathlib import Path
import hashlib,subprocess

QURAN_FIXTURE_COMMIT='80c666acc4ca8c87f6f6b0fc2df82be31b4f4792'


def pinned_fixture(repo,relative,digest,commit=QURAN_FIXTURE_COMMIT):
    raw=(repo/relative).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:
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
        raw=pinned_fixture(repo,relative,pins[relative],inventory['sourceCommit']) if relative in pins else (repo/relative).read_bytes()
        path.write_bytes(raw)
