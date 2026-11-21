import unittest

from briefing import voice_request as vr


class TestNormalize(unittest.TestCase):
    def test_clamps_and_cleans(self):
        p, understood = vr.normalize({"name": "", "language": "DE", "interests": ["Gold", "ECB", "gold", " oil "],
                                      "avoid": "crypto, Sports", "length_minutes": 30, "max_stories": 1,
                                      "understood": "Fünf Minuten zu Gold."})
        self.assertEqual(p["name"], "You")
        self.assertEqual(p["language"], "de")
        self.assertEqual(p["interests"], ["gold", "ecb", "oil"])
        self.assertEqual(p["avoid"], ["crypto", "sports"])
        self.assertEqual((p["length_minutes"], p["max_stories"]), (8, 3))
        self.assertEqual(understood, "Fünf Minuten zu Gold.")

    def test_unknown_language_falls_back_to_english(self):
        p, _ = vr.normalize({"language": "fr", "interests": ["ai"]})
        self.assertEqual(p["language"], "en")
        self.assertEqual(p["length_minutes"], 4)

    def test_no_topics_is_an_error(self):
        with self.assertRaises(ValueError):
            vr.normalize({"language": "en", "interests": []})

    def test_too_short_request_is_rejected_without_api_call(self):
        with self.assertRaises(ValueError):
            vr.profile_from_request("hi", [])


if __name__ == "__main__":
    unittest.main()


class TestNamedTopics(unittest.TestCase):
    def test_named_topic_is_kept_but_avoided_one_is_not(self):
        p = {"interests": ["gold", "eurozone"], "avoid": ["crypto"]}
        out = vr.keep_named_topics(p, "Give me gold, the ECB and inflation. Nothing about crypto.",
                                   ["ecb", "crypto", "inflation", "oil"])
        self.assertIn("ecb", out["interests"])
        self.assertIn("inflation", out["interests"])
        self.assertNotIn("crypto", out["interests"])
        self.assertNotIn("oil", out["interests"])
