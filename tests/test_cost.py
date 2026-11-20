import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from briefing import cost


class CostLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.tmpdir.name) / "spend.log"
        # Patch the module-level ledger path
        self.orig_ledger = cost.LEDGER_PATH
        cost.LEDGER_PATH = self.ledger_path

    def tearDown(self):
        cost.LEDGER_PATH = self.orig_ledger
        self.tmpdir.cleanup()

    def test_ledger_sum_basic(self):
        cost.log_spend("step1", "modelA", 0.1)
        cost.log_spend("step2", "modelB", 0.2)
        self.assertTrue(self.ledger_path.exists())
        self.assertAlmostEqual(cost.spent_to_date(), 0.3, places=6)

    def test_add_tokens_thread_safe(self):
        # Set a predictable price for a test model
        cost.PRICES["test-model"] = (1.0, 2.0)  # USD per 1M tokens
        tracker = cost.CostTracker()

        def worker(n):
            for _ in range(n):
                tracker.add_tokens("stepX", "test-model", 1000, 500)

        threads = [threading.Thread(target=worker, args=(10,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 5*10 calls; each adds 0.002 USD (1000/1e6*1 + 500/1e6*2)
        expected_calls = 50
        expected_usd = 0.002 * expected_calls
        # Give filesystem a moment to flush
        time.sleep(0.05)

        # Check counters were updated without races
        self.assertAlmostEqual(tracker.session_usd(), expected_usd, places=6)
        # Find the step row and verify calls and USD
        rows = {k: v for k, v in tracker.by_step.items()}
        key = next(k for k in rows if k.startswith("stepX (test-model)"))
        self.assertEqual(rows[key]["calls"], expected_calls)
        self.assertAlmostEqual(rows[key]["usd"], expected_usd, places=6)

        # Ledger should contain the same total for this tracker
        total_ledger = cost.spent_to_date()
        self.assertAlmostEqual(total_ledger, expected_usd, places=6)


if __name__ == "__main__":
    unittest.main()
