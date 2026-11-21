import unittest

from briefing import must_hear, rank


def s(sid, headline, imp=5, titles=None, topics=()):
    return {"story_id": sid, "headline": headline, "importance": imp, "topics": list(topics), "n_sources": 1,
            "articles": [{"title": t} for t in (titles or [headline])], "facts": []}


STORIES = [
    s("ipo", "Anthropic prices IPO at $83 a share", 9),
    s("nv", "Nvidia posts blowout quarter", 9, ["Nvidia beats", "Nasdaq rises as Nvidia lifts stocks; Anthropic IPO in focus"]),
    s("dig", "Evening digest: Anthropic IPO demand surges as oil falls", 6, ["Evening digest: Anthropic IPO demand surges"]),
    s("oil", "Oil falls after API build", 6),
    s("jp", "Japan trade deficit narrows but oil costs climb", 6),
    s("fed", "Fed signals December hike", 8, topics=["fed"]),
]


class TestMustHear(unittest.TestCase):
    def test_finds_the_story_that_is_about_it(self):
        self.assertEqual(must_hear.find(STORIES, "the Anthropic IPO")["story_id"], "ipo")  # not Nvidia, not the digest
        self.assertEqual(must_hear.find(STORIES, "oil")["story_id"], "oil")              # not "...but oil costs climb"

    def test_reports_missing_and_unprepared(self):
        rows = [{"title": "GTA VI launch week", "shortlisted": False}]
        out = must_hear.check(STORIES, rows, ["Tesla", "GTA VI"])
        self.assertEqual([r["status"] for r in out], ["not_in_news", "not_prepared"])

    def test_named_story_goes_first_and_counts_toward_the_limit(self):
        p = {"interests": ["fed"], "avoid": [], "max_stories": 2, "must_hear": ["Anthropic IPO"]}
        picked = [x["story_id"] for x in rank.rank_for_listener(STORIES, p)]
        self.assertEqual(picked[0], "ipo")
        self.assertEqual(len(picked), 2)
        self.assertIn("fed", picked)

    def test_clean(self):
        self.assertEqual(must_hear.clean("Anthropic IPO, anthropic ipo,  Nvidia  "), ["Anthropic IPO", "Nvidia"])


if __name__ == "__main__":
    unittest.main()
