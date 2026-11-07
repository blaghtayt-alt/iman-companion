"""Read literal Word body text, including explicit line breaks and tabs."""
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
def body_text(element):
    chunks=[]
    for node in element.iter():
        if node.tag=='{'+W+'}t':chunks.append(node.text or '')
        elif node.tag=='{'+W+'}tab':chunks.append('\t')
        elif node.tag in {'{'+W+'}br','{'+W+'}cr'} and node.get('{'+W+'}type') not in {'page','column'}:chunks.append('\n')
    return ''.join(chunks)
