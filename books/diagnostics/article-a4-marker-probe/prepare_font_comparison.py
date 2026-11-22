"""Prepare an isolated fontconfig universe for a diagnostic comparison."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess
from xml.sax.saxutils import escape

ap = argparse.ArgumentParser()
ap.add_argument('--root', type=Path, required=True)
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--mode', choices=['default', 'controlled'], required=True)
args = ap.parse_args()
root, out = args.root.resolve(), args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
config = json.loads((root / 'books/config.json').read_text())
keys = ['Arabic', 'Latin', 'Naskh', 'SymbolsLTR', 'SymbolsRTL', 'DigitsArabic']
families = {value['family']: value for value in config['fonts'].values()}
selected = [families[name] for name in ['Iman Book Arabic', 'Iman Book Inter', 'Iman Book Naskh',
                                      'Iman Book Symbols LTR', 'Iman Book Symbols RTL', 'Iman Book DigitsArabic']]
fonts = out / 'fonts'
fonts.mkdir()
manifest = []
for family in selected:
    for style, relative in family['files'].items():
        source = root / relative
        target = fonts / source.name
        assert not target.exists()
        shutil.copy2(source, target)
        manifest.append({'family': family['family'], 'style': style, 'source': relative,
                         'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
(out / 'approved-fonts.json').write_text(json.dumps(manifest, indent=2))
if args.mode == 'controlled':
    # No /etc/fonts/fonts.conf include: only these same twelve approved faces
    # participate in fontconfig's fallback. Naskh supplies brackets/parentheses.
    (out / 'fonts.conf').write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>FONT_DIRECTORY</dir>
  <cachedir>CACHE_DIRECTORY</cachedir>
  <match target="pattern">
    <test name="family" compare="eq"><string>Iman Book Arabic</string></test>
    <edit name="family" mode="append" binding="strong"><string>Iman Book Naskh</string></edit>
  </match>
  <alias binding="strong">
    <family>sans-serif</family>
    <prefer><family>Iman Book Arabic</family><family>Iman Book Naskh</family></prefer>
  </alias>
</fontconfig>
'''.replace('FONT_DIRECTORY', escape(str(fonts))).replace('CACHE_DIRECTORY', escape(str(out / 'cache'))))
print(json.dumps({'mode': args.mode, 'approvedFontFiles': len(manifest),
                  'fontManifestSHA256': hashlib.sha256((out / 'approved-fonts.json').read_bytes()).hexdigest()}))
