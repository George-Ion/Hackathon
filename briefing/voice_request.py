"""Turn a listener's spoken request ("what do you want to hear today?") into a listener profile.

  audio memo -> speech to text (gpt-4o-mini-transcribe) -> small model -> profile -> normal briefing

The profile uses the same fields as listeners/*.json, so the rest of the pipeline (rank, script,
verify, voice) is unchanged. The model is given the topic tags that exist in today's edition, so
the interests it writes actually match stories. The audio itself is never stored.
"""
import json
import os
from collections import Counter

from .config import CHEAP_MODEL
from .cost import COST, ensure_budget
from .llm import chat_json, client

TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
TRANSCRIBE_PER_MIN = float(os.getenv("TRANSCRIBE_PER_MIN", 0.003))
LANGS = {"en", "nl", "de"}

SYSTEM = """You turn a listener's spoken request for today's news briefing into a listener profile.
Use ONLY what they said; never invent personal facts.
- interests: 3 to 10 short lowercase topic tags, always in English whatever language they spoke. Always
  include every topic they named (e.g. "ecb", "gold"), then add closely matching tags from
  available_topics (they match today's stories).
- avoid: also English tags.
- avoid: lowercase tags for anything they said they do not want (may be empty).
- language: "en", "nl" or "de". The language they ask the briefing to be in; if they do not say, the
  language they spoke in; if that is none of the three, "en".
- length_minutes: integer 2 to 8 (default 4). "short"/"quick" means 2-3, "detailed" 6.
- max_stories: integer 3 to 7: fewer if they want depth, more if they want quick headlines.
- depth: one short English phrase describing the level of detail they want.
- tone: one short English phrase (default "calm and direct").
- name: their first name if they said it, otherwise "You".
- description: one English sentence about what they want today, from what they said.
- understood: one short sentence, in the briefing language, telling them what they will get.
Return JSON with exactly these keys: name, description, language, interests, avoid, depth,
length_minutes, max_stories, tone, understood."""


def transcribe(path, seconds):
    """Speech to text for a recorded memo. Cost is per minute of audio."""
    usd = max(seconds, 1) / 60 * TRANSCRIBE_PER_MIN
    ensure_budget(usd, "transcribe", TRANSCRIBE_MODEL)
    with open(path, "rb") as f:
        r = client().audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=f)
    COST.add_usd("transcribe", TRANSCRIBE_MODEL, usd, units=round(seconds))
    return (r.text or "").strip()


def available_topics(stories, n=80):
    counts = Counter(t.lower() for s in stories for t in s.get("topics", []))
    return [t for t, _ in counts.most_common(n)]


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _tags(v, limit):
    items = v if isinstance(v, list) else str(v or "").split(",")
    out = []
    for t in items:
        t = " ".join(str(t).lower().split())[:40]
        if t and t not in out:
            out.append(t)
    return out[:limit]


def normalize(raw, transcript=""):
    """Make the model's profile safe for the pipeline: known language, sane length and story count,
    clean tag lists. Raises ValueError if nothing usable was asked for."""
    raw = raw if isinstance(raw, dict) else {}
    lang = str(raw.get("language") or "en").lower()[:2]
    length = _clamp(raw.get("length_minutes"), 2, 8, 4)
    profile = {
        "name": (str(raw.get("name") or "You").strip() or "You")[:40],
        "description": str(raw.get("description") or transcript)[:300],
        "language": lang if lang in LANGS else "en",
        "interests": _tags(raw.get("interests"), 10),
        "avoid": _tags(raw.get("avoid"), 10),
        "depth": str(raw.get("depth") or "clear and concise: what happened and why it matters")[:120],
        "length_minutes": length,
        "max_stories": _clamp(raw.get("max_stories"), 3, 7, min(7, max(3, round(length * 1.1)))),
        "tone": str(raw.get("tone") or "calm and direct")[:80],
        "source": "voice request",
    }
    if not profile["interests"]:
        raise ValueError("I couldn't hear any topics in that request. Try saying what you want to hear about.")
    return profile, str(raw.get("understood") or "")[:240]


def profile_from_request(transcript, stories):
    if len(transcript.split()) < 2:
        raise ValueError("The recording was empty or too short. Try again and say what you want to hear today.")
    raw = chat_json("voice_profile", CHEAP_MODEL, SYSTEM, json.dumps(
        {"request": transcript, "available_topics": available_topics(stories)}, ensure_ascii=False))
    return normalize(raw, transcript)
