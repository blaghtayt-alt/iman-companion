"""Reproduce tiny direction-specific symbol faces from the pinned app font.

Run with fontTools 4.51.0. Font outlines, copyright and license come from the
existing Naskh faces. Source Unicode text is never changed. Compact metrics keep
inline symbols from expanding every translated quotation's line height.
"""
from pathlib import Path
import argparse,json,hashlib

def build(root):
    import fontTools
    from fontTools.ttLib import TTFont
    from fontTools import subset
    if fontTools.__version__!='4.51.0':raise ValueError('Reproduce with pinned fontTools 4.51.0')
    conf=json.loads((root/'books/config.json').read_bytes());base=conf['fonts']['Arabic'];result={};output=root/'books/assets/ornaments';output.mkdir(exist_ok=True)
    for direction in['LTR','RTL']:
        family='Iman Book Symbols '+direction;entry={'family':family,'files':{},'sha256':{}}
        for style in['Regular','Bold']:
            source=root/base['files'][style]
            if hashlib.sha256(source.read_bytes()).hexdigest()!=base['sha256'][style]:raise ValueError('Pinned source font changed')
            font=TTFont(source,recalcTimestamp=False);options=subset.Options();options.name_IDs=['*'];options.name_legacy=True;options.name_languages=['*'];options.recalc_timestamp=False
            s=subset.Subsetter(options=options);s.populate(unicodes=[0x20,0xFD3E,0xFD3F,0xFDFA]);s.subset(font)
            if direction=='LTR':
                for cmap in font['cmap'].tables:
                    if cmap.isUnicode()and 0xFD3E in cmap.cmap and 0xFD3F in cmap.cmap:cmap.cmap[0xFD3E],cmap.cmap[0xFD3F]=cmap.cmap[0xFD3F],cmap.cmap[0xFD3E]
            for record in list(font['name'].names):
                names={1:family,2:style,3:family+' '+style+' 1.0',4:family+' '+style,6:'ImanBookSymbols'+direction+'-'+style,16:family,17:style}
                if record.nameID in names:font['name'].setName(names[record.nameID],record.nameID,record.platformID,record.platEncID,record.langID)
            # All retained outlines fit within y=-286..885 at 1000 units/em.
            # Unlike full Arabic text, these inline symbols need no tall leading.
            font['hhea'].ascent=905;font['hhea'].descent=-300;font['hhea'].lineGap=0
            os2=font['OS/2'];os2.sTypoAscender=905;os2.sTypoDescender=-300;os2.sTypoLineGap=0;os2.usWinAscent=905;os2.usWinDescent=300
            target=output/f'Symbols-{direction}-{style}.ttf';font.save(target);font.close();entry['files'][style]=target.relative_to(root).as_posix();entry['sha256'][style]=hashlib.sha256(target.read_bytes()).hexdigest()
        result['Symbols'+direction]=entry
    proof={'schema':'iman-ornament-font-derivation-v1','fontTools':'4.51.0','sourceFonts':base,'fonts':result,'retainedUnicode':['U+0020','U+FD3E','U+FD3F','U+FDFA'],'directionProjection':'LTR face exchanges only the two ornate-parenthesis glyphs. RTL face retains them. Unicode characters and approved source strings remain unchanged.','license':'Original copyright and license name records are retained in every derived face.'}
    (output/'derivation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.root.resolve()),indent=2))
