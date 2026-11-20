"""Load Newstex/Sourcera JSONL articles, keep a date window, and fold Invezz translations
into their English original (cheap rules, no model calls)."""
import json
from datetime import datetime, timedelta
from pathlib import Path

# Our field -> dotted paths in the Newstex record (first non-empty wins)
FIELDS = {
    "id": ["$id", "id"],
    "title": ["headline", "title"],
    "text": ["text_content", "text"],
    "excerpt": ["excerpt"],
    "source": ["publication.name"],  # the outlet. Note: Newstex "source" is the AUTHOR
    "author": ["source"],
    "published": ["date"],
    "url": ["permalink", "external_id"],
    "language": ["language"],
    "sections": ["provider_categories"],  # publisher's own sections: "Fed", "Crypto", "World"...
    "tickers": ["company_tickers"],
}
TRANSLATION_WINDOW = timedelta(minutes=15)


def _get(row, path):
    for part in path.split("."):
        if not isinstance(row, dict):
            return None
        row = row.get(part)
    return row


def _norm(row, feed):
    a = {k: next((v for p in paths if (v := _get(row, p)) not in (None, "", [])), None) for k, paths in FIELDS.items()}
    a["source"] = a["source"] or feed
    a["sections"] = a["sections"] or []
    a["tickers"] = a["tickers"] or []
    a["language"] = a["language"] or "en"
    a["feed"] = feed
    a["dt"] = datetime.fromisoformat(a["published"])
    a["translations"] = []
    return a


def merge_translations(articles):
    """German/Dutch Invezz articles are translations of an English one by the same author,
    published within 15 minutes. Keep the English article and list the others under it,
    so a story isn't counted as three sources and Dutch/German listeners can get a link in their language."""
    english = [a for a in articles if a["language"] == "en"]
    kept, merged = [], 0
    for a in articles:
        if a["language"] == "en":
            kept.append(a)
            continue
        # outlet names differ per edition ("Invezz - German" vs "Invezz"), so compare the base name
        base = a["source"].split(" - ")[0]
        cands = [e for e in english if e["author"] == a["author"] and e["source"].split(" - ")[0] == base
                 and abs(e["dt"] - a["dt"]) <= TRANSLATION_WINDOW]
        if cands:
            twin = min(cands, key=lambda e: abs(e["dt"] - a["dt"]))
            twin["translations"].append({"id": a["id"], "language": a["language"], "url": a["url"], "title": a["title"]})
            merged += 1
        else:
            kept.append(a)
    return kept, merged


def load_articles(folder="data/raw", since=None, until=None):
    """since/until are ISO dates (until is inclusive of that whole day)."""
    lo = datetime.fromisoformat(since + "T00:00:00+00:00") if since else None
    hi = datetime.fromisoformat(until + "T00:00:00+00:00") + timedelta(days=1) if until else None
    articles = []
    for p in sorted(Path(folder).rglob("*.jsonl")):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    a = _norm(json.loads(line), p.stem)
                    if (lo is None or a["dt"] >= lo) and (hi is None or a["dt"] < hi) and (a["text"] or a["title"]):
                        articles.append(a)
    articles, merged = merge_translations(articles)
    articles.sort(key=lambda a: a["dt"])
    return articles, merged
