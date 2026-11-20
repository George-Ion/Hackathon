import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run


class TestExtractionRetry(unittest.TestCase):
    def make_story(self, sid):
        return {
            "story_id": sid,
            "n_sources": 1,
            "articles": [
                {
                    "id": f"{sid}.a1",
                    "source": "Test Outlet",
                    "title": "Title",
                    "url": "http://example.com",
                    "published": "2026-11-18T00:00:00Z",
                    "language": "en",
                    "translations": [],
                    "sections": [],
                    "text": "",
                    "excerpt": "",
                }
            ],
            "duplicate_ids": [],
        }

    def test_retry_and_log_errors(self):
        calls = {}

        def fake_extract(story, max_chars=4000):
            sid = story["story_id"]
            n = calls.get(sid, 0)
            calls[sid] = n + 1
            if sid == "s_fail_twice":
                raise RuntimeError("boom twice")
            if sid == "s_fail_once" and n == 0:
                raise RuntimeError("boom once")
            # success path returns minimal structure
            return {"story_id": sid, "facts": [], "articles": story["articles"]}

        stories = [
            self.make_story("s_ok"),
            self.make_story("s_fail_once"),
            self.make_story("s_fail_twice"),
        ]

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with patch("briefing.extract.extract_story", side_effect=fake_extract):
                facts, errors = run.extract_stories_with_retry(stories, out)
            # s_ok and s_fail_once should succeed; s_fail_twice should be logged as error
            got_ids = sorted(f["story_id"] for f in facts)
            self.assertEqual(got_ids, ["s_fail_once", "s_ok"])  # order not guaranteed; sort
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["story_id"], "s_fail_twice")
            # error file should exist and contain the same info
            ef = out / "extract_errors.json"
            self.assertTrue(ef.exists())
            loaded = json.loads(ef.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["story_id"], "s_fail_twice")


if __name__ == "__main__":
    unittest.main()
