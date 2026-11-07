"""Display-only ornate-parenthesis orientation; literal source text stays intact.

Unicode U+FD3E/U+FD3F are exceptional: they do not auto-mirror. We select the
matching pinned glyph face for each quotation, including split semantic spans.
"""
import unicodedata
RTL={'ar','ur','fa'}
LEFT='\ufd3e';RIGHT='\ufd3f';SALAWAT='\ufdfa'
SYMBOLS=LEFT+RIGHT+SALAWAT
SYMBOL_LTR='Iman Book Symbols LTR';SYMBOL_RTL='Iman Book Symbols RTL'

def quotation_mirrors(text,language):
    default=language not in RTL;result={i:default for i,c in enumerate(text)if c in{LEFT,RIGHT}};stack=[]
    for i,c in enumerate(text):
        if c not in{LEFT,RIGHT}:continue
        if stack and stack[-1][1]!=c:
            start,opening=stack.pop();inside=text[start+1:i]
            direction=next((unicodedata.bidirectional(x)for x in inside if unicodedata.category(x)!='Cf'and unicodedata.bidirectional(x)in{'L','R','AL'}),'R'if language in RTL else'L')
            desired=RIGHT if direction in{'R','AL'}else LEFT;result[start]=result[i]=opening!=desired
        else:stack.append((i,c))
    return result

def block_mirrors(unit,language):
    blocks=[b for s in unit['sections']for b in s['blocks']];text=''.join(b['text']for b in blocks);mapping=quotation_mirrors(text,language);result={};offset=0
    for block in blocks:
        length=len(block['text']);result[id(block)]={i-offset:value for i,value in mapping.items()if offset<=i<offset+length};offset+=length
    return result

def span_mirrors(spans,mapping):
    result=[];offset=0
    for span in spans:
        length=len(span['text']);result.append({i-offset:value for i,value in mapping.items()if offset<=i<offset+length});offset+=length
    return result
