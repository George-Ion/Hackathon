import unittest

from briefing import rank


class TestRankForListener(unittest.TestCase):
    def setUp(self):
        self.stories = [
            {"story_id": "a", "topics": ["fx"], "region": "US", "importance": 5, "n_sources": 3},
            {"story_id": "b", "topics": ["equities"], "region": "US", "importance": 7, "n_sources": 2},
            {"story_id": "c", "topics": ["fx", "eur/usd"], "region": "EU", "importance": 6, "n_sources": 1},
        ]

    def test_avoid_filters_out(self):
        profile = {"interests": ["fx"], "avoid": ["equities"], "max_stories": 3}
        ranked = rank.rank_for_listener(self.stories, profile)
        ids = [s["story_id"] for s in ranked]
        self.assertIn("a", ids)
        self.assertIn("c", ids)
        self.assertNotIn("b", ids)

    def test_max_stories_limit(self):
        profile = {"interests": ["fx"], "avoid": [], "max_stories": 1}
        ranked = rank.rank_for_listener(self.stories, profile)
        self.assertEqual(len(ranked), 1)


if __name__ == '__main__':
    unittest.main()
