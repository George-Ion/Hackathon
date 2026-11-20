import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from briefing import prerank

T0 = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)


def story(sid, title, vec, outlets=("A",), hours_ago=1, sections=()):
    arts = [{"id": f"{sid}{k}", "title": title, "source": o, "sections": list(sections),
             "dt": T0 - timedelta(hours=hours_ago), "translations": []} for k, o in enumerate(outlets)]
    v = np.asarray(vec, dtype=np.float32)
    return {"story_id": sid, "articles": arts, "duplicate_ids": [], "_vec": v / np.linalg.norm(v)}


class TestPrerank(unittest.TestCase):
    def setUp(self):
        self.stories = [
            story("fed", "Fed signals December hike", [1, 0, 0], sections=["Fed"]),
            story("gold", "Gold falls to one-year low", [0, 1, 0]),
            story("gta", "GTA VI launch week", [0, 0, 1]),
            story("big", "Nvidia earnings lift chip stocks", [0.6, 0.6, 0.2], outlets=("A", "B", "C")),
            story("old", "Fed minutes recap", [0.9, 0.1, 0], hours_ago=30),
        ]
        self.profiles = {"fx": {"interests": ["fed"], "avoid": ["gaming"]},
                         "gamer": {"interests": ["gta"], "avoid": ["fed"]}}
        self.pv = [[1, 0, 0], [0, 0, 1]]

    def test_each_listener_gets_its_best_matches(self):
        keep, rows = prerank.shortlist(self.stories, [s["_vec"] for s in self.stories], self.profiles,
                                       k_listener=1, k_global=0, profile_vectors=self.pv)
        self.assertEqual(keep, {"fed", "gta"})

    def test_avoided_topic_is_never_picked_for_that_listener(self):
        _, rows = prerank.shortlist(self.stories, [s["_vec"] for s in self.stories], self.profiles,
                                    k_listener=5, k_global=0, profile_vectors=self.pv)
        fed = next(r for r in rows if r["story_id"] == "fed")
        self.assertNotIn("gamer", fed["listeners"])
        self.assertIn("fx", fed["listeners"])

    def test_global_buffer_prefers_wide_recent_coverage(self):
        keep, _ = prerank.shortlist(self.stories, [s["_vec"] for s in self.stories], self.profiles,
                                    k_listener=0, k_global=1, profile_vectors=self.pv)
        self.assertEqual(keep, {"big"})

    def test_shortlist_size_does_not_grow_with_volume(self):
        many = self.stories + [story(f"x{i}", f"Filler {i}", [0.1, 0.1, 1]) for i in range(200)]
        keep, _ = prerank.shortlist(many, [s["_vec"] for s in many], self.profiles,
                                    k_listener=3, k_global=4, profile_vectors=self.pv)
        self.assertLessEqual(len(keep), 3 * 2 + 4)


if __name__ == "__main__":
    unittest.main()
