import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

from briefing import ingest, cluster


class TestMergeTranslationsAuthor(unittest.TestCase):
    def test_no_author_does_not_merge(self):
        now = datetime.now(timezone.utc)
        en = {
            "id": "e1",
            "title": "EN title",
            "text": "body",
            "excerpt": "",
            "source": "Invezz",
            "author": "",  # empty author should prevent matching
            "published": now.isoformat(),
            "url": "http://en/1",
            "language": "en",
            "sections": [],
            "tickers": [],
            "feed": "test",
            "dt": now,
            "translations": [],
        }
        nl = {
            "id": "n1",
            "title": "NL title",
            "text": "lichaam",
            "excerpt": "",
            "source": "Invezz - Dutch",
            "author": "",  # also empty
            "published": (now + timedelta(minutes=5)).isoformat(),
            "url": "http://nl/1",
            "language": "nl",
            "sections": [],
            "tickers": [],
            "feed": "test",
            "dt": now + timedelta(minutes=5),
            "translations": [],
        }
        kept, merged = ingest.merge_translations([en, nl])
        # Should keep both, and not count a merge
        self.assertEqual(merged, 0)
        self.assertEqual(len(kept), 2)


class TestClusterExcerptFallback(unittest.TestCase):
    def test_uses_excerpt_when_no_text(self):
        art = {
            "id": "a1",
            "title": "Title A",
            "text": None,  # missing text
            "excerpt": "This is the excerpt that should be used.",
            "source": "Src",
            "author": "Auth",
            "published": datetime.now(timezone.utc).isoformat(),
            "url": "http://x",
            "language": "en",
            "sections": [],
            "tickers": [],
        }
        captured = {}

        def fake_embed(texts):
            # Capture the input for assertion and return a unit-length vector
            captured["texts"] = list(texts)
            return [[1.0, 0.0]]

        with mock.patch.object(cluster, "embed", side_effect=fake_embed):
            stories = cluster.cluster([art])
        self.assertEqual(len(stories), 1)
        self.assertIn("This is the excerpt that should be used.", captured["texts"][0])


class TestLoadArticlesBadDate(unittest.TestCase):
    def test_bad_date_row_is_counted_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmpd:
            p = Path(tmpd) / "feed.jsonl"
            good = {
                "id": "1",
                "headline": "Good title",
                "text": "Good body",
                "publication": {"name": "X"},
                "source": "Auth",
                "date": "2026-11-18T12:34:56+00:00",
                "permalink": "http://good",
                "language": "en",
            }
            bad = {
                "id": "2",
                "headline": "Bad title",
                "text": "Bad body",
                "publication": {"name": "Y"},
                "source": "Auth",
                "date": "not-a-date",
                "permalink": "http://bad",
                "language": "en",
            }
            with open(p, "w", encoding="utf-8") as f:
                import json
                f.write(json.dumps(good) + "\n")
                f.write(json.dumps(bad) + "\n")
            arts, merged, bad_dates = ingest.load_articles(folder=tmpd)
            self.assertEqual(bad_dates, 1)
            self.assertEqual(len(arts), 1)
            self.assertEqual(merged, 0)


if __name__ == "__main__":
    unittest.main()
