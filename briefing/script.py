"""Write the spoken briefing for one listener. The only step that uses the large model."""
import json

from .config import LARGE_MODEL
from .llm import chat_json

WORDS_PER_MINUTE = 150

SYSTEM = """You write a spoken morning news briefing for one listener. It will be read by a synthetic voice.
Write for the ear: short sentences, no lists, no URLs, no brackets, no abbreviations a voice would stumble on.
Structure: one-line greeting, a quick overview of what's coming, then the stories in the given order, then a short sign-off.
The greeting, overview, and sign-off are transitions only; do not put news claims or figures in them. Every news claim belongs in a story segment with fact ids.
Hard rules:
- Use ONLY the facts provided. Never add numbers, names or causes that are not in the facts. Copy figures exactly.
- Summarise in your own words. Never read out article text; at most a short quote, attributed.
- When a story has conflicts, say plainly that sources disagree and give both versions with their outlets.
- Attribute key claims to their outlet ("according to Invezz...").
- No investment advice: never tell the listener to buy, sell or hold anything, and never predict prices.
- Write in the listener's language, at their depth and tone.
- LENGTH IS A HARD LIMIT: the whole briefing must be at most target_words words. Drop facts or whole stories
  rather than run over; the listener has a fixed amount of time. Lead each story with what matters most.
Return JSON: {"language": str, "segments": [{"story_id": str|null, "fact_ids": [str], "text": str}]}
fact_ids lists every fact id the segment states. Use story_id null and empty fact_ids for greeting/overview/sign-off."""


def write_script(profile, stories):
    # Reserve room for the spoken AI disclosure added after script generation.
    target_words = max(1, int(profile.get("length_minutes", 5) * WORDS_PER_MINUTE) - 25)
    payload = {
        "listener": profile,
        "target_words": target_words,
        "stories": [
            {
                "story_id": s["story_id"],
                "headline": s.get("headline"),
                "summary": s.get("summary"),
                "facts": [{"id": f["id"], "text": f["text"],
                           "outlets": sorted({a["outlet"] for a in s["articles"] if a["id"] in f.get("sources", [])})}
                          for f in s.get("facts", [])],
                "conflicts": s.get("conflicts", []),
            }
            for s in stories
        ],
    }
    result = validate_script(chat_json("script", LARGE_MODEL, SYSTEM, json.dumps(payload, ensure_ascii=False)), stories)
    # Treat the requested runtime as a hard acceptance rule. Ask the model to shorten
    # its own draft while preserving fact ids, then fail closed if it still overshoots.
    for attempt in range(2):
        words = sum(len(segment.get("text", "").split()) for segment in result.get("segments", []))
        if words <= target_words:
            return validate_script(result, stories)
        revision = {
            "listener": profile,
            "target_words": target_words,
            "current_word_count": words,
            "available_stories_and_facts": payload["stories"],
            "script": result,
            "instruction": "Rewrite this script to fit the word limit. Preserve only claims supported by the same fact ids. Return the same JSON schema.",
        }
        result = validate_script(chat_json("script_revision", LARGE_MODEL, SYSTEM, json.dumps(revision, ensure_ascii=False)), stories)
    words = sum(len(segment.get("text", "").split()) for segment in result.get("segments", []))
    if words > target_words:
        raise ValueError(f"Generated script is {words} words; limit is {target_words}. No briefing was saved.")
    return validate_script(result, stories)


def validate_script(result, stories):
    if not isinstance(result, dict) or not isinstance(result.get("segments"), list):
        raise ValueError("Script model returned invalid JSON: expected a segments array.")
    if not isinstance(result.get("language"), str) or not result["language"].strip():
        raise ValueError("Script model returned invalid JSON: language must be a non-empty string.")
    by_id = {s["story_id"]: {f["id"] for f in s.get("facts", [])} for s in stories}
    for i, seg in enumerate(result["segments"]):
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            raise ValueError(f"Script segment {i} is missing text.")
        sid = seg.get("story_id")
        ids = seg.get("fact_ids")
        if not seg["text"].strip():
            raise ValueError(f"Script segment {i} is empty.")
        if not isinstance(ids, list):
            raise ValueError(f"Script segment {i} has no fact_ids array.")
        if any(not isinstance(fid, str) or not fid for fid in ids):
            raise ValueError(f"Script segment {i} contains an invalid fact id.")
        if sid is not None and not isinstance(sid, str):
            raise ValueError(f"Script segment {i} has an invalid story id.")
        if sid is None and ids:
            raise ValueError(f"Non-story segment {i} must not cite story facts.")
        if sid is not None:
            if sid not in by_id:
                raise ValueError(f"Script segment {i} references unknown story {sid}.")
            if not ids:
                raise ValueError(f"Story segment {i} has no fact ids.")
            unknown = set(ids) - by_id[sid]
            if unknown:
                raise ValueError(f"Script segment {i} references unknown facts: {sorted(unknown)}")
    return result
