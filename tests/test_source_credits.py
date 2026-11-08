"""Required supplied source credits remain exact without allowing stray English."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'books'))
from bibliography import native_text,ARABIC_SOURCE_CREDITS

class SourceCreditTests(unittest.TestCase):
    def test_exact_supplied_license_paragraphs_are_preserved_in_arabic_reader(self):
        for credit in ARABIC_SOURCE_CREDITS:
            with self.subTest(credit=credit):
                self.assertEqual(native_text(credit,'ar'),credit)
                reader='المصادر\n'+credit+'\nنهاية المصدر'
                self.assertEqual(native_text(reader,'ar'),reader)

    def test_credit_does_not_hide_untranslated_reader_text_or_changed_attribution(self):
        for text in (ARABIC_SOURCE_CREDITS[0]+' Untranslated body',
                     ARABIC_SOURCE_CREDITS[0].replace('CC BY 3.0','CC BY 4.0'),
                     'Tanzil Quran Text — CC BY 3.0','tanzil.net',
                     ARABIC_SOURCE_CREDITS[0]+' https://example.test'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):native_text(text,'ar')

    def test_arabic_credit_exception_does_not_apply_to_other_locales(self):
        with self.assertRaises(ValueError):native_text(ARABIC_SOURCE_CREDITS[0],'ja')

if __name__=='__main__':unittest.main()
