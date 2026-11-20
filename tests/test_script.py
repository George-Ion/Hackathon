import unittest

from briefing import script


class TestValidateScript(unittest.TestCase):
    def setUp(self):
        self.stories = [
            {
                "story_id": "s1",
                "facts": [
                    {"id": "s1.f0"},
                    {"id": "s1.f1"},
                ],
            },
            {
                "story_id": "s2",
                "facts": [
                    {"id": "s2.f0"},
                ],
            },
        ]

    def test_unknown_story_rejected(self):
        result = {
            "language": "en",
            "segments": [
                {"story_id": "s3", "fact_ids": ["s3.f0"], "text": "Test"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "unknown story s3"):
            script.validate_script(result, self.stories)

    def test_unknown_fact_rejected(self):
        result = {
            "language": "en",
            "segments": [
                {"story_id": "s1", "fact_ids": ["s1.f9"], "text": "Test"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "unknown facts"):
            script.validate_script(result, self.stories)


if __name__ == '__main__':
    unittest.main()
