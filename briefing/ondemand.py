"""Live wildcard: extract the stories a NEW listener needs that the batch run did not extract.

The batch run extracts only the pre-ranked shortlist (stories that can reach the known listeners). A new
profile with other interests (sports, UK crime...) would otherwise get a thin or off-topic briefing.
run.py saves every story group to out/groups.json: article ids and the story embedding, never article
text (licence). For a new profile we pre-rank all groups, then extract only its top stories that are
missing from stories.json, reading their text again from the data folder. Typically 0-12 small-model
calls (~$0.003 each) and well under a minute.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import extract, ingest, prerank, rank

LOCK = threading.Lock()  # one writer for stories.json


def save_groups(path, stories, data, since, until):
    """Everything needed to rebuild a story group later, without article text."""
    rows = [{"story_id": s["story_id"], "article_ids": [a["id"] for a in s["articles"]],
             "duplicate_ids": s["duplicate_ids"], "n_sources": s["n_sources"],
             "vec": [round(float(x), 5) for x in s["_vec"]]} for s in stories]
    Path(path).write_text(json.dumps({"data": str(data), "since": since, "until": until, "groups": rows}),
                          encoding="utf-8")


def _load_groups(path, data=None):
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    articles, _, _ = ingest.load_articles(data or saved["data"], saved.get("since"), saved.get("until"))
    by_id = {a["id"]: a for a in articles}
    groups = []
    for g in saved["groups"]:
        arts = [by_id[i] for i in g["article_ids"] if i in by_id]
        if arts:
            groups.append({"story_id": g["story_id"], "articles": arts, "duplicate_ids": g["duplicate_ids"],
                           "n_sources": g["n_sources"], "_vec": np.asarray(g["vec"], dtype=np.float32)})
    return groups


def missing_for(profile, stories, groups, k=prerank.K_PER_LISTENER, profile_vectors=None):
    """Story ids among this listener's top-k groups that have not been extracted yet."""
    keep, _ = prerank.shortlist(groups, [g["_vec"] for g in groups], {"new": profile},
                                k_listener=k, k_global=0, profile_vectors=profile_vectors)
    have = {s["story_id"] for s in stories}
    return [g for g in groups if g["story_id"] in keep and g["story_id"] not in have]


def ensure_stories(profile, stories, out, data=None, progress=None):
    """Return stories extended with this listener's missing top stories (and save them).
    Without out/groups.json (older runs) the stories are returned unchanged."""
    path = Path(out) / "groups.json"
    if not path.exists():
        return stories
    with LOCK:
        groups = _load_groups(path, data)
        todo = missing_for(profile, stories, groups)
        if not todo:
            return stories
        if progress:
            progress(f"extracting {len(todo)} more stories for this listener")
        with ThreadPoolExecutor(8) as pool:
            new = [r for r in pool.map(_try_extract, todo) if r]
        stories = sorted(stories + new, key=rank.global_score, reverse=True)
        (Path(out) / "stories.json").write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")
        return stories


def _try_extract(group):
    for _ in range(2):
        try:
            return extract.extract_story(group)
        except Exception:  # noqa: BLE001 - one failed story must not stop the briefing
            pass
    return None
