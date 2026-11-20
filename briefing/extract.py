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
Return JSON: {"headline": str, "summary": str, "topics": [str], "region": str,
"facts": [{"text": str, "sources": [id]}], "conflicts": [{"issue": str, "positions": [{"claim": str, "sources": [id]}]}],
"importance": int}"""


def article_ref(a):
    """What we keep about a source article: enough to cite and link it, never its full text (licence)."""
    return {"id": a["id"], "outlet": a["source"], "title": a["title"], "url": a["url"],
            "published": a["published"], "language": a["language"], "translations": a["translations"]}


def extract_story(story, max_chars=4000):
    docs = [
        {"id": a["id"], "outlet": a["source"], "published": a["published"], "sections": a["sections"],
         "title": a["title"], "text": (a["text"] or a["excerpt"] or "")[:max_chars]}
        for a in story["articles"][:8]
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
    return out
