import sys
import unittest
from pathlib import Path
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'books'))
from check_bracket_direction import validate_part, q
from book_typography import SYMBOL_LTR, SYMBOL_RTL

LANGUAGES = ['ar','en','ur','id','ms','bn','tr','fr','pt-BR','hi','ru','es',
             'fa','de','zh-CN','uz','th','vi','ja','fil']


def paragraph(pieces):
    root = etree.Element(q('document'))
    p = etree.SubElement(root, q('p'))
    for text, family in pieces:
        r = etree.SubElement(p, q('r'))
        pr = etree.SubElement(r, q('rPr'))
        etree.SubElement(pr, q('rFonts'), {q(slot): family
                                        for slot in ('ascii','hAnsi','eastAsia','cs')})
        etree.SubElement(r, q('t')).text = text
    return root


class BracketDirection(unittest.TestCase):
    def test_all_20_languages_keep_ltr_translations_and_arabic_quotes_distinct(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                # Physical shape is determined by the enclosed passage,
                # including an Arabic quotation inside a Latin-language book.
                root = paragraph([('﴿', SYMBOL_LTR), ('Translated passage', 'Body'),
                                  ('﴾', SYMBOL_LTR), (' then ', 'Body'),
                                  ('﴿', SYMBOL_RTL), ('قُلْ هُوَ اللَّهُ أَحَدٌ', 'Arabic'),
                                  ('﴾', SYMBOL_RTL)])
                before = etree.tostring(root)
                self.assertEqual(validate_part(root, language)['pairedMarkers'], 4)
                self.assertEqual(etree.tostring(root), before)

    def test_screenshot_regression_is_rejected(self):
        root = paragraph([('﴿', SYMBOL_RTL), ('Sabihin mo', 'Body'), ('﴾', SYMBOL_RTL)])
        with self.assertRaisesRegex(ValueError, 'Reversed ornate-bracket'):
            validate_part(root, 'fil')

    def test_rtl_source_delimiters_in_opposite_order_are_supported(self):
        root = paragraph([('﴾', SYMBOL_LTR), ('قُلْ هُوَ اللَّهُ أَحَدٌ', 'Arabic'),
                          ('﴿', SYMBOL_LTR)])
        self.assertEqual(validate_part(root, 'ar')['pairedMarkers'], 2)

    def test_rendered_runs_must_keep_all_four_pinned_font_slots(self):
        root = paragraph([('﴿', SYMBOL_LTR), ('Sabihin mo', 'Body'), ('﴾', SYMBOL_LTR)])
        root.find('.//' + q('rFonts')).set(q('cs'), 'Cambria')
        with self.assertRaisesRegex(ValueError, 'Unpinned ornate-bracket'):
            validate_part(root, 'fil')

    def test_semantic_spans_and_hyperlinks_do_not_hide_direction_errors(self):
        root = paragraph([('﴿', SYMBOL_LTR), ('Sabihin ', 'Body'), ('mo', 'Body'), ('﴾', SYMBOL_LTR)])
        p = root.find(q('p'))
        link = etree.Element(q('hyperlink'))
        run = p[2]; p.remove(run); link.append(run); p.insert(2, link)
        self.assertEqual(validate_part(root, 'fil')['pairedMarkers'], 2)

    def test_ordinary_parentheses_and_square_citations_are_unchanged(self):
        root = paragraph([('(Surah 112:1) [12]', 'Body')])
        before = etree.tostring(root)
        self.assertEqual(validate_part(root, 'fil')['ornateBrackets'], 0)
        self.assertEqual(etree.tostring(root), before)

    def test_cross_paragraph_source_pairs_are_reported_without_guessing(self):
        root = paragraph([('﴿', SYMBOL_LTR), ('first paragraph', 'Body')])
        self.assertEqual(validate_part(root, 'fil')['crossParagraphOrUnpairedMarkers'], 1)


if __name__ == '__main__':
    unittest.main()
