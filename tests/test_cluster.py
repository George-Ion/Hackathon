import unittest
from datetime import datetime, timezone
from unittest import mock

from briefing import cluster


def art(i, title):
    return {"id": f"a{i}", "title": title, "text": f"text {i}", "excerpt": "", "source": f"Outlet{i}",
            "dt": datetime(2026, 11, 18, 8, i, tzinfo=timezone.utc)}


# cos(a,b)=0.90 (stage 1); c and d are ~0.70 from both a and b (borderline); d is a digest
VECS = [[1, 0, 0], [0.9, 0.436, 0], [0.7, 0.2, 0.686], [0.7, 0.2, -0.686]]


class TestCluster(unittest.TestCase):
    def setUp(self):
        self.articles = [art(0, "X prices IPO at $83"), art(1, "X IPO set to price tonight"),
                         art(2, "Investor warns X may not be profitable despite IPO"),
                         art(3, "Evening digest: X IPO demand surges as gold falls")]

    def groups(self, stories):
        return sorted(sorted(a["id"] for a in s["articles"]) for s in stories)

    def test_stage_one_only(self):
        with mock.patch.object(cluster, "embed", return_value=VECS):
            out = cluster.cluster(self.articles, threshold=0.78, confirm=False)
        self.assertEqual(self.groups(out), [["a0", "a1"], ["a2"], ["a3"]])

    def test_confirmed_borderline_pair_merges_but_digest_never_does(self):
        said_same = lambda step, model, system, user: {"same": [f"p{k}" for k in range(50)]}
        with mock.patch.object(cluster, "embed", return_value=VECS), \
             mock.patch.object(cluster, "chat_json", side_effect=said_same) as chat:
            out = cluster.cluster(self.articles, threshold=0.78, confirm=True, confirm_low=0.62)
        self.assertEqual(self.groups(out), [["a0", "a1", "a2"], ["a3"]])
        self.assertNotIn("digest", chat.call_args.args[3].lower())  # the digest was never even asked about

    def test_rejected_pair_stays_apart(self):
        with mock.patch.object(cluster, "embed", return_value=VECS), \
             mock.patch.object(cluster, "chat_json", return_value={"same": []}):
            out = cluster.cluster(self.articles, threshold=0.78, confirm=True, confirm_low=0.62)
        self.assertEqual(self.groups(out), [["a0", "a1"], ["a2"], ["a3"]])

    def test_failed_confirm_batch_does_not_fail_the_run(self):
        with mock.patch.object(cluster, "embed", return_value=VECS), \
             mock.patch.object(cluster, "chat_json", side_effect=RuntimeError("api down")):
            out = cluster.cluster(self.articles, threshold=0.78, confirm=True, confirm_low=0.62)
        self.assertEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
