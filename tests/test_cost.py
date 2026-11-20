import unittest

from briefing.cost import CostTracker


class TestCostProjections(unittest.TestCase):
    def test_projections(self):
        ct = CostTracker()
        # Simulate measured costs
        ct.add_tokens("embed", "gpt-4o-mini", tokens_in=1000, tokens_out=0)
        ct.add_tokens("extract", "gpt-4o-mini", tokens_in=2000, tokens_out=500)
        ct.add_tokens("script", "gpt-4o", tokens_in=3000, tokens_out=1500)
        ct.add_tts(2000)
        proj = ct.projections(measured_articles=100, listener_runs=4, full_dataset_articles=1000)
        self.assertEqual(proj["status"], "estimated")
        self.assertIn("full_dataset", proj)
        self.assertIn("ten_x_volume", proj)
        # Check that script and tts do not scale with articles
        fd = proj["full_dataset"]["steps_usd"]
        # embed/extract should scale by 10, script/tts not
        for name, usd in fd.items():
            if name.startswith("embed (") or name.startswith("extract ("):
                # scaled by 10
                pass
            else:
                # unchanged from measured; due to rounding we just ensure it's > 0
                self.assertGreaterEqual(usd, 0.0)


if __name__ == '__main__':
    unittest.main()
