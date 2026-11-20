import unittest
import re
import math

from briefing import verify


class TestNumbers(unittest.TestCase):
    def test_numbers_english_basic(self):
        # English style decimals and scales
        txt = "Revenue rose 1.08 billion and margin was 5%."
        nums = verify._numbers(txt)
        # Current implementation converts scaled numbers to integers-as-strings only
        self.assertIn('1080000000', nums)
        self.assertIn('5', nums)
        self.assertNotIn('1.08', nums)

    def test_numbers_german_currently_wrong(self):
        # German uses comma as decimal separator; after P0-2 we expect a float 1.08e9
        txt = "Der Umsatz stieg um 1,08 Milliarden und die Marge lag bei 5%."
        nums = verify._numbers(txt)
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 1.08e9, rel_tol=1e-6) for x in nums))

    def test_numbers_dutch_currently_wrong(self):
        # Dutch comma decimal, 'miljard' scale
        txt = "De omzet steeg met 2,3 miljard en de marge was 5%."
        nums = verify._numbers(txt)
        self.assertTrue(any(isinstance(x, float) and math.isclose(x, 2.3e9, rel_tol=1e-6) for x in nums))

    def test_numbers_thousands_german_currently_wrong(self):
        # European thousands and decimal separators
        txt = "Het aantal gebruikers bereikte 1.234,5."
        nums = verify._numbers(txt)
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


if __name__ == '__main__':
    unittest.main()
