"""Reproduce two source-specific honorific glyphs without replacing source text.

Use the existing pinned OFL Naskh outlines. The original PDF's AGAArabesque
program is evidence for its private-use mappings, not a redistributed font.
"""
from pathlib import Path
import argparse
import hashlib
import json


def build(root):
    import fontTools
    from fontTools import subset
    from fontTools.ttLib import TTFont
    if fontTools.__version__!='4.51.0':
        raise ValueError('Reproduce with pinned fontTools 4.51.0')
    root=Path(root).resolve()
    conf=json.loads((root/'books/config.json').read_bytes())
    base=conf['fonts']['Arabic']
    family='Iman Book Fiqh Symbols'
    entry={'family':family,'files':{},'sha256':{}}
    aliases={0xF065:0xFDFA,0xF074:0xFD41}
    output=root/'books/assets/ornaments'
    output.mkdir(exist_ok=True)
    for style in ('Regular','Bold'):
        source=root/base['files'][style]
        if hashlib.sha256(source.read_bytes()).hexdigest()!=base['sha256'][style]:
            raise ValueError('Pinned source font changed')
        font=TTFont(source,recalcTimestamp=False)
        options=subset.Options()
        options.name_IDs=['*'];options.name_legacy=True;options.name_languages=['*']
        options.recalc_timestamp=False
        sub=subset.Subsetter(options=options)
        sub.populate(unicodes=[0x20,*aliases.values()])
        sub.subset(font)
        for cmap in font['cmap'].tables:
            if cmap.isUnicode():
                for private,canonical in aliases.items():
                    if canonical not in cmap.cmap:
                        raise ValueError('Pinned outline missing')
                    cmap.cmap[private]=cmap.cmap[canonical]
        for record in list(font['name'].names):
            names={1:family,2:style,3:family+' '+style+' 1.0',4:family+' '+style,
                   6:'ImanBookFiqhSymbols-'+style,16:family,17:style}
            if record.nameID in names:
                font['name'].setName(names[record.nameID],record.nameID,
                                     record.platformID,record.platEncID,record.langID)
        # Match the compact existing honorific face; all retained outlines fit.
        font['hhea'].ascent=905;font['hhea'].descent=-300;font['hhea'].lineGap=0
        os2=font['OS/2'];os2.sTypoAscender=905;os2.sTypoDescender=-300
        os2.sTypoLineGap=0;os2.usWinAscent=905;os2.usWinDescent=300
        target=output/f'FiqhSymbols-{style}.ttf'
        font.save(target);font.close()
        entry['files'][style]=target.relative_to(root).as_posix()
        entry['sha256'][style]=hashlib.sha256(target.read_bytes()).hexdigest()
    proof={
        'schema':'iman-source-symbol-font-derivation-v1',
        'fontTools':'4.51.0','sourceFonts':base,'fonts':{'FiqhSymbols':entry},
        'sourceEvidence':{
            'url':'https://d1.islamhouse.com/data/en/ih_books/single2/en-the-summarized-islamic-fiqh.pdf',
            'pdfSHA256':'20a8a3e14b7b1e3c71d34d39acc0795e3ae2d1fe3dbeba4dcd0cd168617fae9b',
            'symbolLegendPhysicalPage':9,'quotationPhysicalPage':344,
            'originalFace':'AGAArabesque',
            'acceptedTextSHA256':'1dc04f17def1ab8a735bc44fcb520bff61b6912835da527351fe26496badc6ef',
            'acceptedSourcePath':'materials/hadith/essential-en/001.txt',
            'acceptedSourceCommit':'3d52ed51a73ecb3497d7813d2d0b584dbf53df2a',
            'acceptedSourceSHA256':'5e04c584947edb161102d1819214e29e2d08f898bc849bd34abfb7f3a6a3d914'},
        'glyphAliases':[
            {'sourceCharacter':'U+F065','outline':'U+FDFA','meaning':'Salla Allahu alayhi wa sallam'},
            {'sourceCharacter':'U+F074','outline':'U+FD41','meaning':'Radiya Allahu anhu'}],
        'scope':'Only the exact hash-bound accepted English paragraph selects this face. No general private-use substitution.',
        'textPreservation':'No Unicode character, reader, source, review or qualification is changed.',
        'license':'Existing Noto SIL Open Font License copyright and license records retained; family renamed. Original AGAArabesque font is not redistributed.'}
    (output/'fiqh-symbol-derivation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return entry


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().root),indent=2))
