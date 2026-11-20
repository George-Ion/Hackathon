import unittest
from unittest import mock

import briefing.llm as llm


class FakeUsage:
    def __init__(self, p=0, c=0):
        self.prompt_tokens = p
        self.completion_tokens = c


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content, p=0, c=0):
        self.choices = [FakeChoice(content)]
        self.usage = FakeUsage(p, c)


class FakeChatCreate:
    def __init__(self, contents):
        # contents: list of strings to return on successive calls
        self.contents = list(contents)
        self.calls = 0

    def create(self, **kwargs):
        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return FakeResponse(self.contents[idx], p=0, c=0)


class FakeClient:
    def __init__(self, contents):
        self.chat = mock.MagicMock()
        self.chat.completions = FakeChatCreate(contents)
        self.embeddings = mock.MagicMock()


class TestChatJsonRetries(unittest.TestCase):
    def setUp(self):
        # Patch ensure_budget to no-op for tests
        self._ensure = llm.ensure_budget
        llm.ensure_budget = lambda est, step, model: None
        # Patch client factory to return our fake client
        self._orig_client = llm.client

    def tearDown(self):
        llm.ensure_budget = self._ensure
        llm.client = self._orig_client

    def test_invalid_then_valid_json_succeeds(self):
        fake = FakeClient(["not-json", "{\"ok\": true}"])

        def fake_client():
            return fake

        llm.client = fake_client
        out = llm.chat_json("unit_step", "fake-model", "sys", "user")
        self.assertEqual(out, {"ok": True})
        # First attempt fails to parse, second succeeds -> two calls
        self.assertEqual(fake.chat.completions.calls, 2)

    def test_two_invalid_raises_valueerror_with_step_name(self):
        fake = FakeClient(["not-json", "still-not-json"])  # both invalid

        def fake_client():
            return fake

        llm.client = fake_client
        with self.assertRaises(ValueError) as cm:
            llm.chat_json("bad_step", "fake-model", "sys", "user")
        self.assertIn("bad_step", str(cm.exception))
        self.assertEqual(fake.chat.completions.calls, 2)


if __name__ == "__main__":
    unittest.main()
