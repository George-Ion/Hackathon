import json
import unittest
from types import SimpleNamespace

from briefing import script, verify


class RepairLoopTest(unittest.TestCase):
    def setUp(self):
        # Monkeypatch chat_json in module namespace
        self._orig_chat = script.chat_json
        import briefing.llm as llm
        self._orig_llm_chat = llm.chat_json

        def fake_chat_json(step, model, system, user):
            payload = json.loads(user)
            if step == "script_repair":
                # Return a cleaned segment: same ids, no advice
                return {
                    "story_id": payload.get("story_id"),
                    "fact_ids": list(payload.get("allowed_fact_ids") or []),
                    "text": "According to {}: {}".format(
                        (payload.get("facts") or [{}])[0].get("outlets", ["an outlet"])[0],
                        (payload.get("facts") or [{}])[0].get("text", ""),
                    ),
                }
            elif step == "verify":
                # Always return supported claim(s) with a source article id
                facts = payload.get("facts") or []
                sources = []
                for f in facts:
                    # The verify step will resolve fact ids to their article ids
                    sources.append(f.get("id"))
                return {
                    "claims": [{
                        "claim": (facts[0].get("text") if facts else ""),
                        "verdict": "supported",
                        "sources": sources or [],
                    }],
                    "investment_advice": False,
                }
            else:
                return {}

        # Apply monkeypatch
        script.chat_json = fake_chat_json
        llm.chat_json = fake_chat_json

    def tearDown(self):
        # Restore
        script.chat_json = self._orig_chat
        import briefing.llm as llm
        llm.chat_json = self._orig_llm_chat

    def test_repair_rewrites_and_recheck_clears_flags(self):
        profile = {"language": "en", "length_minutes": 0.2}
        stories = [{
            "story_id": "s1",
            "facts": [{
                "id": "s1.f1",
                "text": "Apple revenue rose 10%",
                "sources": ["a1"],
            }],
            "articles": [{
                "id": "a1",
                "outlet": "Invezz",
                "permalink": "http://example.com/a1",
                "published": "2026-11-18T09:00:00Z",
            }],
            "conflicts": [],
        }]
        # Initial script has advice, which should be flagged by regex
        sc = {"language": "en", "segments": [
            {"story_id": "s1", "fact_ids": ["s1.f1"], "text": "You should buy Apple. Apple revenue rose 10%."}
        ]}
        # Simulate a flagged report entry with its index
        bad = [{
            "_index": 0,
            "story_id": "s1",
            "advice_regex": True,
        }]
        new_sc, changed, logs = script.revise_segments(profile, stories, sc, bad)
        self.assertEqual(changed, [0])
        self.assertEqual(len(logs), 1)
        # The repaired segment should keep the same ids and drop advice
        seg = new_sc["segments"][0]
        self.assertEqual(seg.get("fact_ids"), ["s1.f1"])  # must keep at least one id
        self.assertNotIn("buy", seg.get("text", "").lower())

        # Re-verify only this segment; problems should be empty now (with mocked verifier)
        by_id = {s["story_id"]: s for s in stories}
        entry = verify._check(seg, by_id, language="en")
        problems = verify.problems([entry])
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()