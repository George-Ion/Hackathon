import unittest

from briefing import extract


class TestExtractHelpers(unittest.TestCase):
    def test_article_ref_fields(self):
        a = {
            "id": "art1",
            "source": "Invezz",
            "title": "Title",
            "url": "http://example.com",
            "published": "2026-11-18T12:00:00Z",
            "language": "en",
            "translations": {"de": "art1_de"},
            "text": "body",
            "excerpt": "exc",
            "sections": ["Markets"],
        }
        ref = extract.article_ref(a)
        self.assertEqual(ref["id"], "art1")
        self.assertEqual(ref["outlet"], "Invezz")
        self.assertEqual(ref["title"], "Title")
        self.assertEqual(ref["url"], "http://example.com")
        self.assertEqual(ref["published"], "2026-11-18T12:00:00Z")
        self.assertEqual(ref["language"], "en")
        self.assertEqual(ref["translations"], {"de": "art1_de"})


if __name__ == '__main__':
    unittest.main()
