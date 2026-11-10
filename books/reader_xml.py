"""Read literal Word body text, including explicit line breaks and tabs."""
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
def body_text(element):
    chunks=[]
    for node in element.iter():
        if node.tag=='{'+W+'}t':chunks.append(node.text or '')
        # Word may serialize a source U+00AD as an explicit run element.
        elif node.tag=='{'+W+'}softHyphen':chunks.append('\u00ad')
        # Preserve a source U+2011 when Word uses its dedicated run element.
        elif node.tag=='{'+W+'}noBreakHyphen':chunks.append('\u2011')
        elif node.tag=='{'+W+'}tab':chunks.append('\t')
        elif node.tag in {'{'+W+'}br','{'+W+'}cr'} and node.get('{'+W+'}type') not in {'page','column'}:chunks.append('\n')
    return ''.join(chunks)
