"""Pre-rank story groups with free signals, so only stories that can reach a briefing are extracted.

Extraction (one small-model call per story) is the only step whose cost grows with article volume.
Before any model call, every story group gets a score from signals that are free or nearly free:
  - coverage: how many outlets and articles reported it (and translations folded into it)
  - recency: how late in the edition window it was published
  - listener fit: cosine similarity between the story's embedding (already computed for clustering)
    and each listener's profile embedding, plus interest terms found in titles or publisher sections
Avoided topics remove a story for that listener. The shortlist is the top K per listener plus the top K
overall (a buffer for a wildcard listener). Only shortlisted stories are extracted, so extraction cost
depends on the number of listeners, not on the number of articles.
"""
import math
import re

import numpy as np

from .llm import embed

K_PER_LISTENER = 12   # each listener picks at most max_stories (4-7) from these
K_GLOBAL = 15         # widely covered, recent stories: buffer for the wildcard listener
SIM_WEIGHT = 10.0


def profile_text(p):
    return (f"News for: {p.get('description', '')}. Interests: {', '.join(p.get('interests', []))}. "
            f"Wants depth: {p.get('depth', '')}.")


def _terms(text):
    return set(re.findall(r"[a-z0-9/&.+-]+", (text or "").lower()))


def _matches(term, words, phrases):
    term = term.lower().strip()
    return term in words if " " not in term else any(term in p for p in phrases)


def coverage_score(story):
    outlets = len({a["source"].split(" - ")[0] for a in story["articles"]})
    translations = sum(len(a.get("translations", [])) for a in story["articles"])
    n = len(story["articles"]) + len(story.get("duplicate_ids", []))
    return 2.0 * math.log1p(outlets - 1) + 1.0 * math.log1p(n - 1) + 0.5 * math.log1p(translations)


def recency_score(story, window_end):
    latest = max(a["dt"] for a in story["articles"])
    hours = max(0.0, (window_end - latest).total_seconds() / 3600)
    return max(0.0, 1.0 - hours / 24.0)  # 1 for the newest, 0 for a day old


def shortlist(stories, vectors, profiles, k_listener=K_PER_LISTENER, k_global=K_GLOBAL, profile_vectors=None):
    """stories: clustered stories (articles with title/sections/dt). vectors: one unit vector per story.
    profiles: {name: profile}. Returns (set of story_ids to extract, list of per-story score rows)."""
    if not stories:
        return set(), []
    window_end = max(a["dt"] for s in stories for a in s["articles"])
    V = np.asarray(vectors, dtype=np.float32)
    names = list(profiles)
    if profile_vectors is None and names:
        profile_vectors = embed([profile_text(profiles[n]) for n in names])
    P = np.asarray(profile_vectors, dtype=np.float32).reshape(len(names), -1) if names else np.zeros((0, V.shape[1]))
    if len(P):
        P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
    sims = V @ P.T if len(P) else np.zeros((len(stories), 0))

    rows = []
    for i, s in enumerate(stories):
        titles = " ".join(a["title"] or "" for a in s["articles"])
        sections = " ".join(" ".join(a.get("sections") or []) for a in s["articles"])
        words, phrases = _terms(titles + " " + sections), [(titles + " " + sections).lower()]
        base = coverage_score(s) + recency_score(s, window_end)
        per = {}
        for j, n in enumerate(names):
            p = profiles[n]
            if any(_matches(t, words, phrases) for t in p.get("avoid", [])):
                continue
            hits = sum(_matches(t, words, phrases) for t in p.get("interests", []))
            per[n] = round(SIM_WEIGHT * float(sims[i, j]) + 1.5 * min(hits, 3) + 0.25 * base, 4)
        rows.append({"story_id": s["story_id"], "title": s["articles"][0]["title"],
                     "articles": len(s["articles"]), "outlets": sorted({a["source"] for a in s["articles"]}),
                     "global": round(base, 4), "listeners": per, "picked_for": []})

    keep = set()
    for n in names:
        ranked = sorted((r for r in rows if n in r["listeners"]), key=lambda r: -r["listeners"][n])
        for r in ranked[:k_listener]:
            keep.add(r["story_id"])
            r["picked_for"].append(n)
    for r in sorted(rows, key=lambda r: -r["global"])[:k_global]:
        keep.add(r["story_id"])
        r["picked_for"].append("overall")
    for r in rows:
        r["shortlisted"] = r["story_id"] in keep
    return keep, rows
