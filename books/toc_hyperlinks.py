"""Keep generated contents entries clickable through LibreOffice refreshes.

This configures the renderer's index, not cached Word text or invented anchors.
Every existing non-link token and property remains in the same order. The
unchanged Word/PDF validators still require one real destination per entry.
"""

CONTENT_INDEX = 'com.sun.star.text.ContentIndex'
LINK_START = 'TokenHyperlinkStart'
LINK_END = 'TokenHyperlinkEnd'
TOKEN_SEQUENCE = '[][]com.sun.star.beans.PropertyValue'


def token_type(token):
    values = [item.Value for item in token if item.Name == 'TokenType']
    if len(values) != 1:
        raise ValueError('Contents format token has no unique type')
    return values[0]


def linked_format(tokens, property_value):
    """Wrap one complete entry without replacing its text/tab/page formatting."""
    tokens = tuple(tokens)
    types = [token_type(token) for token in tokens]
    if types.count('TokenEntryText') != 1 or types.count('TokenPageNumber') != 1:
        raise ValueError('Contents format needs one entry and one page number')
    starts = [i for i, value in enumerate(types) if value == LINK_START]
    ends = [i for i, value in enumerate(types) if value == LINK_END]
    if not starts and not ends:
        first = (property_value('TokenType', LINK_START),)
        last = (property_value('TokenType', LINK_END),)
    elif len(starts) == len(ends) == 1 and starts[0] < ends[0]:
        if starts[0] == 0 and ends[0] == len(tokens) - 1:
            return tokens
        first, last = tokens[starts[0]], tokens[ends[0]]
    else:
        raise ValueError('Contents format has ambiguous hyperlink delimiters')
    inner = tuple(token for token, kind in zip(tokens, types)
                  if kind not in {LINK_START, LINK_END})
    return (first,) + inner + (last,)


def ensure_contents_hyperlinks(indexes, uno, property_value):
    """Set native ContentIndex link tokens before refresh, including save-only passes.

    Level zero is the index heading. Plan every level first so malformed input
    fails before changing any index. Typed Any/invoke is required for the
    nested PropertyValue sequences carried by XIndexReplace's Any argument.
    """
    changes = []
    for number in range(indexes.getCount()):
        index = indexes.getByIndex(number)
        if index.getServiceName() != CONTENT_INDEX:
            continue
        levels = index.LevelFormat
        for level in range(1, levels.getCount()):
            before = tuple(levels.getByIndex(level))
            after = linked_format(before, property_value)
            if before != after:
                changes.append((levels, level, after))
    for levels, level, tokens in changes:
        uno.invoke(levels, 'replaceByIndex',
                   (level, uno.Any(TOKEN_SEQUENCE, tokens)))
    return len(changes)
