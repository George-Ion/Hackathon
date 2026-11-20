"""Write the spoken briefing for one listener. The only step that uses the large model."""
import json

from .config import LARGE_MODEL
from .llm import chat_json
from . import tts

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


def length_bounds(profile):
    target = int(profile.get("length_minutes", 5) * WORDS_PER_MINUTE)
    low, high = int(target * 0.85), int(target * 1.15)
    return low, high


def write_script(profile, stories):
    # Reserve room for the spoken AI disclosure added after script generation.
    target_total = max(1, int(profile.get("length_minutes", 5) * WORDS_PER_MINUTE))
    disclosure_words = len(tts.DISCLOSURES.get(profile.get("language", "en"), tts.DISCLOSURES["en"]).split())
    target_words = max(1, int(target_total * 0.95) - disclosure_words)
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
    # Enforce both sides of the total-length bound (including disclosure). Allow up to 2 revisions.
    low_total, high_total = length_bounds(profile)
    # Stricter internal band we try to hit to improve listening experience
    rev_low_total = int(target_total * 0.90)
    rev_high_total = int(target_total * 1.10)
    for attempt in range(2):
        words_body = sum(len(segment.get("text", "").split()) for segment in result.get("segments", []))
        total = words_body + disclosure_words
        # Accept immediately if we're comfortably within the internal band
        if rev_low_total <= total <= rev_high_total:
            return validate_script(result, stories)
        # Otherwise, if we're outside the hard band, or just outside the internal one, revise
        need = "expand" if total < rev_low_total else "shorten"
        delta = (rev_low_total - total) if need == "expand" else (total - rev_high_total)
        # Ask the model to stretch or cut while keeping the same story order and fact-id discipline.
        # Be explicit about not introducing new numbers or any investment advice in any language.
        instruction = (
            "Expand this script by about {} words using unused provided facts where helpful. "
            "Do not invent facts; every claim must be supported by fact_ids from the same story. "
            "Avoid introducing any new numeric figures not present verbatim in those facts. "
            "No investment advice (no directives like buy/sell/kopen/verkaufen). "
            "Keep the same story order and return the same JSON schema."
            if need == "expand" else
            "Rewrite this script to reduce by about {} words while preserving only claims supported by the same fact ids. "
            "Prefer cutting less important details or whole segments to fit. "
            "Do not add or paraphrase numbers; keep only figures that appear verbatim in the cited facts. "
            "No investment advice (no directives like buy/sell/kopen/verkaufen). "
            "Return the same JSON schema."
        ).format(int(delta))
        revision = {
            "listener": profile,
            "target_words": target_words,
            "current_word_count": words_body,
            "available_stories_and_facts": payload["stories"],
            "script": result,
            "instruction": instruction,
        }
        result = validate_script(chat_json("script_revision", LARGE_MODEL, SYSTEM, json.dumps(revision, ensure_ascii=False)), stories)
    # Final check: hard band. We still prefer the internal band but won't fail if inside hard limits.
    words_body = sum(len(segment.get("text", "").split()) for segment in result.get("segments", []))
    total = words_body + disclosure_words
    if not (low_total <= total <= high_total):
        raise ValueError(
            f"Generated script is {total} words including disclosure; allowed range is {low_total}-{high_total}. No briefing was saved.")
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
