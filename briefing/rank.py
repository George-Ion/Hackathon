"""Order stories globally (importance + coverage) and per listener (interest match). No LLM calls."""
import math


def global_score(s):
    # n_sources counts distinct outlets, so a story covered by Invezz, IBTimes and Zacks ranks higher
    return s.get("importance", 5) + 2 * math.log1p(s.get("n_sources", 1))


def _tags(s):
    return {t.lower() for t in s.get("topics", [])} | {s.get("region", "").lower()}


def _hits(tags, wanted):
    # "fed" matches "fed" and "fed speakers"; keeps profiles short
    return sum(1 for w in wanted if any(w == t or w in t.split() for t in tags))


def rank_for_listener(stories, profile):
    likes = [t.lower() for t in profile.get("interests", [])]
    avoid = [t.lower() for t in profile.get("avoid", [])]
    weight = profile.get("interest_weight", 4)
    limit = profile.get("max_stories", 6)

    # Stories the listener named ("I want to hear about the Anthropic IPO") come first, guaranteed
    from .must_hear import find
    pinned = []
    for phrase in profile.get("must_hear", []) or []:
        s = find(stories, phrase)
        if s and s not in pinned:
            pinned.append(s)

    scored = []
    for s in stories:
        tags = _tags(s)
        if s in pinned or _hits(tags, avoid):
            continue
        scored.append((global_score(s) + weight * _hits(tags, likes), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return pinned + [s for _, s in scored[: max(0, limit - len(pinned))]]
