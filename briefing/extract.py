"""Per story: headline, key facts with source ids, disagreements, importance. Cheap model."""
import json

from .config import CHEAP_MODEL
from .llm import chat_json

SYSTEM = """You extract facts from news articles about ONE event. Rules:
- Only state facts that appear in the articles. Never invent or round numbers; copy figures exactly.
- Every fact lists the article ids that support it.
- If articles disagree (numbers, causes, claims), record it in "conflicts".
- topics: short lowercase tags, e.g. "fed", "forex", "eur/usd", "crypto", "bitcoin", "stocks", "earnings",
  "ai", "commodities", "oil", "gold", "politics", "world", "uk", "crime", "entertainment", "sports".
- importance: 1-10 for a general business audience (market impact, novelty, people affected).
- Keep the briefing usable: return at most 6 distinct, high-value facts for the event. Prefer facts with
  exact figures, consequences, or useful context; do not restate the headline as a fact.
Return JSON: {"headline": str, "summary": str, "topics": [str], "region": str,
"facts": [{"text": str, "sources": [id]}], "conflicts": [{"issue": str, "positions": [{"claim": str, "sources": [id]}]}],
"importance": int}"""


def article_ref(a):
    """What we keep about a source article: enough to cite and link it, never its full text (licence)."""
    return {"id": a["id"], "outlet": a["source"], "title": a["title"], "url": a["url"],
            "published": a["published"], "language": a["language"], "translations": a["translations"]}


def _map_translation_id(source_id, articles_by_id):
    """Map a translation article id to its English original id if it belongs to this story.
    If the id is already an English article in this story, keep it. If it is an id of a
    translation listed under an English article in this story, return that English id.
    Otherwise return None.
    """
    if source_id in articles_by_id:
        return source_id
    # check if source_id matches any translation id in this story
    for eng_id, a in articles_by_id.items():
        for tr in a.get("translations", []):
            if tr.get("id") == source_id:
                return eng_id
    return None


def _filter_sources_list(sources, articles_by_id):
    kept = []
    dropped = 0
    for s in sources or []:
        mapped = _map_translation_id(s, articles_by_id)
        if mapped is not None:
            kept.append(mapped)
        else:
            dropped += 1
    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for s in kept:
        if s not in seen:
            deduped.append(s)
            seen.add(s)
    return deduped, dropped


def _apply_source_filter(extracted_story, articles):
    """Validate and normalize source ids inside an extracted story structure.
    - Keep only sources that are articles in this story (mapping translation ids to their English parent id).
    - Drop any fact (or conflict position) left without valid sources.
    - Record counts under extracted_story["dropped_sources"] and ["dropped_facts"].
    Mutates extracted_story in place.
    """
    articles_by_id = {a["id"]: a for a in extracted_story.get("articles") or [article_ref(x) for x in articles]}
    dropped_sources = 0
    dropped_facts = 0

    # Facts
    facts = []
    for f in extracted_story.get("facts", []) or []:
        new_sources, d = _filter_sources_list(f.get("sources"), articles_by_id)
        dropped_sources += d
        if new_sources:
            f["sources"] = new_sources
            facts.append(f)
        else:
            dropped_facts += 1
    extracted_story["facts"] = facts

    # Conflicts positions
    new_conflicts = []
    for c in extracted_story.get("conflicts", []) or []:
        new_positions = []
        for p in c.get("positions", []) or []:
            new_sources, d = _filter_sources_list(p.get("sources"), articles_by_id)
            dropped_sources += d
            if new_sources:
                p["sources"] = new_sources
                new_positions.append(p)
        if new_positions:
            c["positions"] = new_positions
            new_conflicts.append(c)
    extracted_story["conflicts"] = new_conflicts

    extracted_story["dropped_sources"] = dropped_sources
    extracted_story["dropped_facts"] = dropped_facts


def _diverse(articles, n):
    """Up to n articles, one per outlet first: other outlets add facts, a second article from the
    same outlet mostly repeats them."""
    first, rest, seen = [], [], set()
    for a in articles:
        (rest if a["source"] in seen else first).append(a)
        seen.add(a["source"])
    return (first + rest)[:n]


def extract_story(story, max_chars=3000, max_articles=5):
    docs = [
        {"id": a["id"], "outlet": a["source"], "published": a["published"], "sections": a["sections"],
         "title": a["title"], "text": (a["text"] or a["excerpt"] or "")[:max_chars]}
        for a in _diverse(story["articles"], max_articles)
    ]
    out = chat_json("extract", CHEAP_MODEL, SYSTEM, json.dumps(docs, ensure_ascii=False))
    sid = story["story_id"]
    out["story_id"] = sid
    out["n_sources"] = story["n_sources"]
    out["published"] = max(a["published"] for a in story["articles"])
    out["articles"] = [article_ref(a) for a in story["articles"]]
    out["duplicate_ids"] = story["duplicate_ids"]
    # Publisher sections are free, reliable topic labels: add them to the model's tags
    sections = {s.lower() for a in story["articles"] for s in a["sections"]}
    out["topics"] = sorted({t.lower() for t in out.get("topics", [])} | sections)
    for i, f in enumerate(out.get("facts", [])):
        f["id"] = f"{sid}.f{i}"
    # Validate source IDs and drop facts left without valid sources
    _apply_source_filter(out, story["articles"])  # counts in out["dropped_sources"], out["dropped_facts"]
    return out


def clean_story(story):
    """Repair an already-extracted story in-place by validating source ids against its own article list.
    - Translate translation ids to their English original id.
    - Drop facts/positions that end up with no valid sources.
    Returns the mutated story (convenience for callers).
    """
    # Work on a shallow copy of articles already present in the story structure
    _apply_source_filter(story, [])
    return story
