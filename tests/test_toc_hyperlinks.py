"""Strict renderer-format tests; no fabricated Word or PDF link acceptance."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'books'))
from toc_hyperlinks import (CONTENT_INDEX, LINK_END, LINK_START, TOKEN_SEQUENCE,
                            ensure_contents_hyperlinks, linked_format)


def prop(name, value):
    return SimpleNamespace(Name=name, Value=value)


def token(kind, **properties):
    return (prop('TokenType', kind),) + tuple(prop(k, v) for k, v in properties.items())


def entry():
    return (token('TokenEntryNumber', CharacterStyleName='Number', ChapterLevel=2),
            token('TokenEntryText', CharacterStyleName='Index Link'),
            token('TokenTabStop', TabStopRightAligned=True, TabStopFillCharacter='.',
                  TabStopPosition=16700),
            token('TokenPageNumber', CharacterStyleName='Page digits'))


class Levels:
    def __init__(self, values):
        self.values = list(values)
        self.writes = []

    def getCount(self):
        return len(self.values)

    def getByIndex(self, i):
        return self.values[i]

    def replaceByIndex(self, i, value):
        self.writes.append(i)
        self.values[i] = value


class Index:
    def __init__(self, levels, service=CONTENT_INDEX):
        self.LevelFormat = levels
        self.service = service

    def getServiceName(self):
        return self.service


class Indexes:
    def __init__(self, *values):
        self.values = values

    def getCount(self):
        return len(self.values)

    def getByIndex(self, i):
        return self.values[i]


class Uno:
    def __init__(self):
        self.calls = []

    def Any(self, type_name, value):
        return SimpleNamespace(type_name=type_name, value=value)

    def invoke(self, target, method, args):
        level, typed = args
        assert method == 'replaceByIndex'
        assert typed.type_name == TOKEN_SEQUENCE
        self.calls.append((target, method, level, typed.type_name))
        target.replaceByIndex(level, typed.value)


class ContentsHyperlinks(unittest.TestCase):
    def test_missing_links_wrap_every_existing_token_without_mutation(self):
        before = entry()
        after = linked_format(before, prop)
        self.assertEqual([p.Value for p in after[0] if p.Name == 'TokenType'], [LINK_START])
        self.assertEqual([p.Value for p in after[-1] if p.Name == 'TokenType'], [LINK_END])
        self.assertEqual(after[1:-1], before)
        for original, retained in zip(before, after[1:-1]):
            self.assertIs(original, retained)

    def test_whole_entry_links_are_idempotent_and_preserve_link_properties(self):
        before = (token(LINK_START, CharacterStyleName='Existing start'),) + entry() + (
            token(LINK_END, CharacterStyleName='Existing end'),)
        self.assertEqual(linked_format(before, prop), before)
        self.assertIs(linked_format(before, prop)[0], before[0])
        self.assertIs(linked_format(before, prop)[-1], before[-1])

    def test_partial_link_expands_only_delimiters_and_preserves_all_properties(self):
        content = entry()
        start, end = token(LINK_START, CharacterStyleName='Existing'), token(LINK_END)
        before = (content[0], start, content[1], end) + content[2:]
        after = linked_format(before, prop)
        self.assertEqual(after, (start,) + content + (end,))
        self.assertIs(after[0], start)

    def test_unbalanced_reversed_or_multiple_links_are_rejected(self):
        cases = ((token(LINK_START),) + entry(),
                 entry() + (token(LINK_END),),
                 (token(LINK_END),) + entry() + (token(LINK_START),),
                 (token(LINK_START), token(LINK_START)) + entry() +
                 (token(LINK_END), token(LINK_END)))
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'ambiguous'):
                linked_format(value, prop)

    def test_missing_or_repeated_content_tokens_are_rejected(self):
        for value in (entry()[:-1], entry()[2:], entry() + (token('TokenPageNumber'),),
                      entry() + (token('TokenEntryText'),)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'one entry'):
                linked_format(value, prop)

    def test_malformed_token_type_is_rejected(self):
        for malformed in ((prop('Other', 'x'),),
                          (prop('TokenType', 'TokenText'), prop('TokenType', 'TokenEntryText'))):
            with self.subTest(value=malformed), self.assertRaisesRegex(ValueError, 'unique type'):
                linked_format(entry() + (malformed,), prop)

    def test_only_content_levels_after_header_change_and_second_call_is_noop(self):
        header = (token('TokenText', Text='Contents'),)
        levels = Levels([header, entry(), entry()])
        other = Levels([header, ()])
        uno = Uno()
        indexes = Indexes(Index(levels), Index(other, 'com.sun.star.text.Bibliography'))
        self.assertEqual(ensure_contents_hyperlinks(indexes, uno, prop), 2)
        self.assertIs(levels.values[0], header)
        self.assertEqual(levels.writes, [1, 2])
        self.assertEqual(other.writes, [])
        self.assertEqual(ensure_contents_hyperlinks(indexes, uno, prop), 0)
        self.assertEqual(len(uno.calls), 2)

    def test_later_invalid_index_prevents_all_mutation(self):
        valid = Levels([(), entry()])
        invalid = Levels([(), (token('TokenEntryText'),)])
        uno = Uno()
        with self.assertRaises(ValueError):
            ensure_contents_hyperlinks(Indexes(Index(valid), Index(invalid)), uno, prop)
        self.assertEqual(uno.calls, [])
        self.assertEqual(valid.writes, [])


if __name__ == '__main__':
    unittest.main()
