import unittest
import re
import math

from briefing import verify


class TestNumbers(unittest.TestCase):
    def test_numbers_english_basic(self):
        # English style decimals and scales
        txt = "Revenue rose 1.08 billion and margin was 5%."
        nums = verify._numbers(txt, language="en")
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 1.08e9, rel_tol=1e-6) for x in nums))
        self.assertIn(5.0, nums)

    def test_numbers_german_currently_wrong(self):
        # German uses comma as decimal separator; after P0-2 we expect a float 1.08e9
        txt = "Der Umsatz stieg um 1,08 Milliarden und die Marge lag bei 5%."
        nums = verify._numbers(txt, language="de")
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 1.08e9, rel_tol=1e-6) for x in nums))

    def test_numbers_dutch_currently_wrong(self):
        # Dutch comma decimal, 'miljard' scale
        txt = "De omzet steeg met 2,3 miljard en de marge was 5%."
        nums = verify._numbers(txt, language="nl")
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 2.3e9, rel_tol=1e-6) for x in nums))

    def test_numbers_thousands_german_currently_wrong(self):
        # European thousands and decimal separators
        txt = "Het aantal gebruikers bereikte 1.234,5."
        nums = verify._numbers(txt, language="nl")
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 1234.5, rel_tol=1e-6) for x in nums))


class TestAdviceRegex(unittest.TestCase):
    def test_advice_positive_en(self):
        self.assertTrue(bool(verify.ADVICE.search("You should buy now")))
        self.assertTrue(bool(verify.ADVICE.search("we recommend selling")))

    def test_advice_negative_en(self):
        self.assertFalse(bool(verify.ADVICE.search("Analysts say investors bought shares yesterday")))

    def test_advice_positive_de_currently_fails(self):
        # These should be caught after P0-3, but currently they do NOT match
        self.assertTrue(bool(verify.ADVICE.search("Kaufen Sie jetzt")))
        self.assertTrue(bool(verify.ADVICE.search("Wir empfehlen zu verkaufen")))

    def test_advice_positive_nl_currently_fails(self):
        self.assertTrue(bool(verify.ADVICE.search("Koop nu")))
        self.assertTrue(bool(verify.ADVICE.search("Wij raden aan om te beleggen")))

    def test_advice_negative_de(self):
        # Reporting, not advice
        self.assertFalse(bool(verify.ADVICE.search("Anleger kauften Gold")))


class TestUnmatchedNumbers(unittest.TestCase):
    """German/Dutch scripts may keep English figure formats; only real mismatches are flagged."""
    def src(self, text):
        return verify._numbers(text, "en")

    def test_english_format_in_german_script_is_not_flagged(self):
        self.assertEqual(verify._unmatched_numbers("Spot-Gold fiel um 2.3% auf $3,770", "de", self.src("Spot gold fell 2.3% to $3,770")), set())

    def test_german_decimal_comma_matches(self):
        self.assertEqual(verify._unmatched_numbers("Der Euro stieg auf 1,08 Dollar", "de", self.src("The euro rose to $1.08")), set())

    def test_dutch_scale_word_matches(self):
        self.assertEqual(verify._unmatched_numbers("De omzet was 1,5 miljard", "nl", self.src("Revenue was 1.5 billion")), set())

    def test_real_mismatch_is_flagged(self):
        self.assertEqual(verify._unmatched_numbers("Gold fiel auf 3.880 Dollar", "de", self.src("Gold fell to $3,770")), {3880.0})


if __name__ == '__main__':
    unittest.main()
