"""Use one verified Ubuntu renderer for every canonical book preparation.

LibreOffice 24.2 can break a native numeric citation at a bidi boundary
(upstream tdf#56408). The fixed engine and matching Python UNO bridge come
from Ubuntu's signed noble-backports archive. This Python file is included in
preparation_queue's code fingerprint, so changing the pin invalidates old
preparations instead of relabelling their existing PDF bytes.
"""
import argparse
import json
import re
import subprocess

APT_VERSION='4:26.2.5.2-0ubuntu0.26.04.1~bpo24.04.1'
SOFFICE_VERSION='26.2.5.2'
PACKAGES=('libreoffice-writer','libreoffice-core','libreoffice-common','python3-uno','ure','uno-libs-private')
BACKPORTS='''Types: deb
URIs: https://archive.ubuntu.com/ubuntu/
Suites: noble-backports
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
'''


def verify_renderer():
    version=subprocess.check_output(['soffice','--version'],text=True,timeout=20).strip()
    if not re.match(r'^LibreOffice '+re.escape(SOFFICE_VERSION)+r'(?:\s|$)',version):
        raise ValueError('Book rendering requires pinned LibreOffice '+SOFFICE_VERSION+'; found '+version)
    return version


def verify_packages():
    installed={name:subprocess.check_output(['dpkg-query','-W','-f=${Version}',name],text=True).strip()for name in PACKAGES}
    if any(version!=APT_VERSION for version in installed.values()):raise ValueError('Installed book renderer packages do not match the pin: '+json.dumps(installed,sort_keys=True))
    subprocess.run(['/usr/bin/python3','-c','import uno; assert uno.getComponentContext() is not None'],check=True)
    return {'renderer':verify_renderer(),'packages':installed}


def install():
    # These are the existing official Ubuntu signing keys; no third-party PPA
    # or unauthenticated package source is added.
    subprocess.run(['sudo','tee','/etc/apt/sources.list.d/iman-book-renderer.sources'],input=BACKPORTS,text=True,stdout=subprocess.DEVNULL,check=True)
    subprocess.run(['sudo','apt-get','update'],check=True)
    subprocess.run(['sudo','apt-get','install','-y','-t','noble-backports',
                    *(name+'='+APT_VERSION for name in PACKAGES),'fontconfig'],check=True)
    return verify_packages()


def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--install',action='store_true');group.add_argument('--apt-version',action='store_true')
    group.add_argument('--verify-packages',action='store_true');args=parser.parse_args()
    if args.apt_version:print(APT_VERSION)
    else:print(json.dumps(install()if args.install else verify_packages()if args.verify_packages else {'renderer':verify_renderer()},sort_keys=True))


if __name__=='__main__':main()
