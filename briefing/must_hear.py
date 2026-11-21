"""'I want to hear about X': find the story a listener names and give it a guaranteed slot.

Topic tags are broad ("ipo", "ai"), so a named company or event is searched in each prepared story's
headline, summary, topics, article titles and facts instead. All significant words of the request
must appear. No model calls.
"""
import re

from .cluster import DIGEST

STOP = set("""a an the and or of on in to for about with from news story stories article latest today
de het een en van over op in voor met nieuws verhaal artikel
der die das ein eine und von über zu im mit nachrichten artikel geschichte""".split())


def _words(text):
    return re.findall(r"[a-z0-9äöüß&/.+-]+", (text or "").lower())


def terms(phrase):
    return [w for w in _words(phrase) if w not in STOP and (len(w) >= 2)]


def _blob(story):
    parts = [story.get("headline"), story.get("summary"), " ".join(story.get("topics", []))]
    parts += [a.get("title") for a in story.get("articles", [])]
    parts += [f.get("text") for f in story.get("facts", [])]
    return set(_words(" ".join(p for p in parts if p)))


def _hit(words, blob):
    # "nvidia" matches "nvidia's" / "nvidias"; "ipo" matches "ipo"
    return all(any(b == w or b.startswith(w) for b in blob) for w in words)


def find(stories, phrase):
    """Best prepared story for a phrase, or None."""
    words = terms(phrase)
    if not words:
        return None
    hits = [s for s in stories if _hit(words, _blob(s))]

    def count(text):
        t = set(_words(text))
        return sum(any(b == w or b.startswith(w) for b in t) for w in words)

    def about(s):  # the story is ABOUT it: its own headline first, then its article titles
        titles = " ".join(a.get("title") or "" for a in s.get("articles", []))
        share = count(titles) / max(1, len(s.get("articles", [])))  # a passing mention in 1 of 10 titles counts little
        digest = any(DIGEST.search(a.get("title") or "") for a in s.get("articles", []))  # roundups name everything
        head = _words(s.get("headline"))
        first = min((i for i, b in enumerate(head) for w in words if b == w or b.startswith(w)), default=99)
        # most request words in the headline, not a roundup, named early in the headline ("Oil falls…"
        # beats "…but oil costs climb"), then how many article titles name it, then importance
        return (count(s.get("headline")), not digest, -first, round(share, 2), s.get("importance", 0))

    return max(hits, key=about, default=None)


def in_unprepared(prerank_rows, phrase):
    """Titles of today's story groups that match but were not prepared (pre-ranking left them out)."""
    words = terms(phrase)
    if not words:
        return []
    return [r["title"] for r in prerank_rows or []
            if not r.get("shortlisted") and _hit(words, set(_words(r.get("title"))))]


def check(stories, prerank_rows, phrases):
    """One result per phrase: found (with headline), not_prepared, or not_in_news."""
    out = []
    for p in phrases or []:
        s = find(stories, p)
        if s:
            out.append({"phrase": p, "status": "found", "story_id": s["story_id"], "headline": s.get("headline")})
        elif in_unprepared(prerank_rows, p):
            out.append({"phrase": p, "status": "not_prepared", "titles": in_unprepared(prerank_rows, p)[:2]})
        else:
            out.append({"phrase": p, "status": "not_in_news"})
    return out


def clean(value, limit=3):
    items = value if isinstance(value, list) else str(value or "").split(",")
    out = []
    for x in items:
        x = " ".join(str(x).split())[:60]
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out[:limit]
