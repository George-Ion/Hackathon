import unittest
from unittest import mock

from briefing import make


class TestScriptLengthRetry(unittest.TestCase):
    def test_length_miss_is_retried_once(self):
        err = ValueError("Generated script is 751 words including disclosure; allowed range is 765-1035.")
        with mock.patch.object(make.rank, "rank_for_listener", return_value=[]), \
             mock.patch.object(make.script, "write_script", side_effect=[err, RuntimeError("second call")]) as w:
            with self.assertRaises(RuntimeError):  # reached the second attempt
                make.make_briefing({"language": "en"}, "t", [], "out", audio=False)
        self.assertEqual(w.call_count, 2)

    def test_other_errors_are_not_retried(self):
        with mock.patch.object(make.rank, "rank_for_listener", return_value=[]), \
             mock.patch.object(make.script, "write_script", side_effect=ValueError("invalid JSON")) as w:
            with self.assertRaises(ValueError):
                make.make_briefing({"language": "en"}, "t", [], "out", audio=False)
        self.assertEqual(w.call_count, 1)


if __name__ == "__main__":
    unittest.main()
