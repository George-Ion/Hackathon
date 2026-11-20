"""Write the spoken briefing for one listener. The only step that uses the large model."""
import json

from .config import LARGE_MODEL
from .llm import chat_json

WORDS_PER_MINUTE = 150

SYSTEM = """You write a spoken morning news briefing for one listener. It will be read by a synthetic voice.
Write for the ear: short sentences, no lists, no URLs, no brackets, no abbreviations a voice would stumble on.
Structure: one-line greeting, a quick overview of what's coming, then the stories in the given order, then a short sign-off.
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
    payload = {
        "listener": profile,
        "target_words": int(profile.get("length_minutes", 5) * WORDS_PER_MINUTE),
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
    return chat_json("script", LARGE_MODEL, SYSTEM, json.dumps(payload, ensure_ascii=False))
