"""Reproduce native PAGE-field glyphs without changing Word's global options."""
from pathlib import Path
import argparse,json,hashlib
def build(root):
    import fontTools
    from fontTools.ttLib import TTFont
    from fontTools import subset
    if fontTools.__version__!='4.51.0':raise ValueError('Reproduce with pinned fontTools 4.51.0')
    conf=json.loads((root/'books/config.json').read_bytes());result={};out=root/'books/assets/ornaments';out.mkdir(exist_ok=True)
    for key,base_key,start in[('DigitsArabic','Arabic',0x660),('DigitsPersian','Arabic',0x6f0)]:
        base=conf['fonts'][base_key];family='Iman Book '+key;entry={'family':family,'files':{},'sha256':{}}
        for style in['Regular','Bold']:
            source=root/base['files'][style]
            if hashlib.sha256(source.read_bytes()).hexdigest()!=base['sha256'][style]:raise ValueError('Pinned source digit font changed')
            font=TTFont(source,recalcTimestamp=False);opts=subset.Options();opts.name_IDs=['*'];opts.name_legacy=True;opts.name_languages=['*'];opts.recalc_timestamp=False
            s=subset.Subsetter(options=opts);s.populate(unicodes=[0x20,*range(0x30,0x3a),*range(start,start+10)]);s.subset(font)
            for table in font['cmap'].tables:
                if table.isUnicode():
                    for n in range(10):
                        if start+n not in table.cmap:raise ValueError('Source font lacks its native numeral')
                        table.cmap[0x30+n]=table.cmap[start+n]
            for record in list(font['name'].names):
                names={1:family,2:style,3:family+' '+style+' 1.0',4:family+' '+style,6:'ImanBook'+key+'-'+style,16:family,17:style}
                if record.nameID in names:font['name'].setName(names[record.nameID],record.nameID,record.platformID,record.platEncID,record.langID)
            target=out/(key+'-'+style+'.ttf');font.save(target);font.close();entry['files'][style]=target.relative_to(root).as_posix();entry['sha256'][style]=hashlib.sha256(target.read_bytes()).hexdigest()
        result[key]=entry
    (out/'digit-derivation.json').write_text(json.dumps({'schema':'iman-native-page-glyphs-v1','fontTools':'4.51.0','fonts':result,'semanticValueUnchanged':True,'purpose':'Normal PAGE results keep their numeric value; glyphs use the book language independently of Word numeral preferences. Original copyright/license name records retained.'},ensure_ascii=False,indent=2)+'\n',encoding='utf8');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.root.resolve()),indent=2))
