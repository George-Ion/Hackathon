"""Group articles about the same event into stories and merge duplicates.
Cheap step: embeddings + cosine similarity, no LLM calls."""
import numpy as np

from .config import CLUSTER_THRESHOLD
from .llm import embed


def cluster(articles, threshold=CLUSTER_THRESHOLD):
    if not articles:
        return []
    texts = [f"{a['title']}\n{(a['text'] or a['excerpt'] or '')[:1500]}" for a in articles]
    v = np.array(embed(texts), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    sim = v @ v.T

    # Average-linkage merging, strongest pairs first. Two clusters only merge if their articles
    # are similar ON AVERAGE, which stops chaining (Nvidia earnings -> CoreWeave -> AMD -> ...)
    # that plain single-link union-find causes on a busy topic.
    members = {i: [i] for i in range(len(articles))}
    owner = list(range(len(articles)))
    ii, jj = np.where(np.triu(sim, 1) >= threshold)
    for k in np.argsort(-sim[ii, jj]):
        a, b = owner[ii[k]], owner[jj[k]]
        if a == b:
            continue
        if sim[np.ix_(members[a], members[b])].mean() < threshold:
            continue
        for m in members[b]:
            owner[m] = a
        members[a] += members.pop(b)

    groups = members

    stories = []
    for idx in groups.values():
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
        })
    return stories
