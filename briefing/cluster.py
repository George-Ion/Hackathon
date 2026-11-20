"""Group articles about the same event into stories and merge duplicates.

Two cheap stages:
1. Embeddings + average-linkage merging at CLUSTER_THRESHOLD: pairs this similar are nearly always
   the same event.
2. Borderline pairs (CLUSTER_CONFIRM_LOW <= similarity < threshold) between different groups are sent,
   in batches, to the small model with one question: is this the same specific event? Only confirmed
   pairs merge. This catches same-event coverage written from a different angle (an IPO pricing and an
   analyst warning about that IPO) without merging articles that merely share a topic.
"""
import json
import re

import numpy as np

from .config import CHEAP_MODEL, CLUSTER_CONFIRM, CLUSTER_CONFIRM_LOW, CLUSTER_THRESHOLD
from .llm import chat_json, embed

CONFIRM_BATCH = 20
# Roundups cover several events, so they never join a story through the borderline check
DIGEST = re.compile(r"\b(digest|roundup|round-up|wrap|recap|things to know|what to watch|week ahead|morning brief|"
                    r"evening brief|market overview|markets? (today|update)|live (blog|updates)|briefing)\b", re.I)
CONFIRM_MAX_PAIRS = 200

CONFIRM_SYSTEM = """You decide whether pairs of news articles report the SAME SPECIFIC NEWS EVENT.
Same event: the same announcement, deal, data release, decision, speech, incident or market move,
including follow-ups, reactions and analysis of that one event (for example "X prices its IPO at $83"
and "investor warns X may not be profitable despite its IPO" are the same event: X's IPO).
NOT the same event: articles that only share a company, sector, country or broad topic
(two different Fed speeches; Nvidia earnings vs. an AMD product launch), and market roundups or
daily digests that cover several events at once (a digest is never the same event as one of its items).
When unsure, answer not the same.
Return JSON: {"same": [pair ids that are the same event]}"""


def _lead(a, n=320):
    return " ".join(((a.get("text") or a.get("excerpt") or "")[:n]).split())


def _merge(members, owner, a, b):
    for m in members[b]:
        owner[m] = a
    members[a] += members.pop(b)


def confirm_pairs(articles, pairs):
    """pairs: list of (i, j). Returns the set of (i, j) the small model confirms as the same event."""
    confirmed = set()
    for start in range(0, len(pairs), CONFIRM_BATCH):
        batch = pairs[start:start + CONFIRM_BATCH]
        payload = [{"pair": f"p{start + k}",
                    "a": {"outlet": articles[i]["source"], "title": articles[i]["title"], "lead": _lead(articles[i])},
                    "b": {"outlet": articles[j]["source"], "title": articles[j]["title"], "lead": _lead(articles[j])}}
                   for k, (i, j) in enumerate(batch)]
        try:
            out = chat_json("cluster_confirm", CHEAP_MODEL, CONFIRM_SYSTEM, json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # a failed batch only means fewer merges, never a failed run
            print(f"cluster confirm batch failed ({type(e).__name__}: {e}); keeping those pairs apart")
            continue
        same = {str(x) for x in (out.get("same") or [])} if isinstance(out, dict) else set()
        for k, pair in enumerate(batch):
            if f"p{start + k}" in same:
                confirmed.add(pair)
    return confirmed


def cluster(articles, threshold=CLUSTER_THRESHOLD, confirm=CLUSTER_CONFIRM, confirm_low=CLUSTER_CONFIRM_LOW):
    if not articles:
        return []
    texts = [f"{a['title']}\n{(a['text'] or a['excerpt'] or '')[:1500]}" for a in articles]
    v = np.array(embed(texts), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    sim = v @ v.T

    # Stage 1. Average-linkage merging, strongest pairs first. Two clusters only merge if their articles
    # are similar ON AVERAGE, which stops chaining (Nvidia earnings -> CoreWeave -> AMD -> ...)
    # that plain single-link union-find causes on a busy topic.
    members = {i: [i] for i in range(len(articles))}
    owner = list(range(len(articles)))
    ii, jj = np.where(np.triu(sim, 1) >= threshold)
    for k in np.argsort(-sim[ii, jj]):
        a, b = owner[ii[k]], owner[jj[k]]
        if a != b and sim[np.ix_(members[a], members[b])].mean() >= threshold:
            _merge(members, owner, a, b)

    # Stage 2. Borderline pairs between different groups: the strongest article pair per group pair,
    # confirmed by the small model. Merges still need the groups to be similar on average.
    if confirm and len(members) > 1:
        best = {}
        ii, jj = np.where((np.triu(sim, 1) >= confirm_low) & (np.triu(sim, 1) < threshold))
        for i, j in zip(ii.tolist(), jj.tolist()):
            if DIGEST.search(articles[i]["title"] or "") or DIGEST.search(articles[j]["title"] or ""):
                continue
            ga, gb = sorted((owner[i], owner[j]))
            if ga != gb and sim[i, j] > best.get((ga, gb), (None, -1))[1]:
                best[(ga, gb)] = ((i, j), sim[i, j])
        candidates = [p for p, _ in sorted(best.values(), key=lambda x: -x[1])][:CONFIRM_MAX_PAIRS]
        confirmed = confirm_pairs(articles, candidates) if candidates else set()
        for i, j in candidates:  # strongest first
            if (i, j) not in confirmed:
                continue
            a, b = owner[i], owner[j]
            if a != b and sim[np.ix_(members[a], members[b])].mean() >= confirm_low:
                _merge(members, owner, a, b)

    stories = []
    for idx in members.values():
        idx = sorted(idx, key=lambda i: str(articles[i].get("dt") or articles[i].get("published") or ""))
        # Near-identical texts (wire copies) are duplicates: keep one, remember the rest
        kept, dupes = [], []
        for i in idx:
            if any(sim[i, k] > 0.97 for k in kept):
                dupes.append(articles[i]["id"])
            else:
                kept.append(i)
        stories.append({
            "story_id": f"s{len(stories)}",
            "articles": [articles[i] for i in kept],
            "duplicate_ids": dupes,
            "n_sources": len({articles[i]["source"] for i in idx}),
            # unit centroid of the story's articles, reused by prerank (never saved to stories.json)
            "_vec": (lambda c: c / (np.linalg.norm(c) + 1e-9))(v[idx].mean(axis=0)),
        })
    return stories
