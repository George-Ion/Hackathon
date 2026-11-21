import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np

from briefing import ondemand

T0 = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)


def group(sid, title, vec, sections=()):
    arts = [{"id": f"{sid}a", "title": title, "source": "A", "sections": list(sections),
             "dt": T0 - timedelta(hours=1), "translations": []}]
    v = np.asarray(vec, dtype=np.float32)
    return {"story_id": sid, "articles": arts, "duplicate_ids": [], "n_sources": 1, "_vec": v / np.linalg.norm(v)}


class TestOnDemand(unittest.TestCase):
    def setUp(self):
        self.groups = [group("fed", "Fed signals December hike", [1, 0, 0]),
                       group("football", "Arsenal beat Chelsea", [0, 0, 1], sections=["Sports"]),
                       group("gold", "Gold falls", [0, 1, 0])]
        self.extracted = [{"story_id": "fed", "importance": 8, "n_sources": 1, "facts": []}]
        self.sport_fan = {"name": "Sam", "interests": ["sports"], "avoid": []}

    def test_new_listener_gets_its_unextracted_top_stories(self):
        todo = ondemand.missing_for(self.sport_fan, self.extracted, self.groups, k=1,
                                    profile_vectors=[[0, 0, 1]])
        self.assertEqual([g["story_id"] for g in todo], ["football"])

    def test_nothing_to_do_when_top_stories_are_already_extracted(self):
        todo = ondemand.missing_for({"interests": ["fed"]}, self.extracted, self.groups, k=1,
                                    profile_vectors=[[1, 0, 0]])
        self.assertEqual(todo, [])

    def test_ensure_extracts_saves_and_never_stores_article_text(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            ondemand.save_groups(out / "groups.json", self.groups, "data/raw", "2026-11-18", "2026-11-18")
            saved = (out / "groups.json").read_text(encoding="utf-8")
            self.assertNotIn("Arsenal", saved)  # ids and vectors only
            fake = lambda g: {"story_id": g["story_id"], "importance": 5, "n_sources": 1, "facts": []}
            with mock.patch.object(ondemand, "_load_groups", return_value=self.groups), \
                 mock.patch.object(ondemand.prerank, "embed", return_value=[[0, 0, 1]]), \
                 mock.patch.object(ondemand.extract, "extract_story", side_effect=fake) as ex:
                stories = ondemand.ensure_stories(self.sport_fan, self.extracted, out)
            self.assertIn("football", {s["story_id"] for s in stories})
            self.assertEqual(ex.call_count, len(stories) - 1)
            on_disk = json.loads((out / "stories.json").read_text(encoding="utf-8"))
            self.assertEqual({s["story_id"] for s in on_disk}, {s["story_id"] for s in stories})

    def test_older_runs_without_groups_are_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIs(ondemand.ensure_stories(self.sport_fan, self.extracted, Path(d)), self.extracted)


if __name__ == "__main__":
    unittest.main()
