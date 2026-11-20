"""Trust check (25% of the score): every story segment is checked against its extracted facts.
Cheap deterministic number check first, then a cheap-model claim check."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .config import CHEAP_MODEL
from .llm import chat_json

NUM = re.compile(
    r"(?<![\w])(\d[\d,.]*)(?:\s*(thousand|million|billion|trillion|tausend|millionen?|"
    r"milliarden?|duizend|miljoen|miljard))?",
    re.I,
)
SCALES = {
    "thousand": 1_000, "tausend": 1_000, "duizend": 1_000,
    "million": 1_000_000, "millions": 1_000_000, "millionen": 1_000_000,
    "miljoen": 1_000_000,
    "billion": 1_000_000_000, "billions": 1_000_000_000,
    "milliarde": 1_000_000_000, "milliarden": 1_000_000_000,
    "miljard": 1_000_000_000,
    "trillion": 1_000_000_000_000,
}
ADVICE = re.compile(r"\b(you should (buy|sell|invest)|buy now|sell now|good time to (buy|invest)|we recommend)\b", re.I)

SYSTEM = """You check a spoken news segment against its source facts.
For each factual claim in the segment, decide: supported, unsupported (not in facts), or contradicted.
Also flag any investment advice. Return JSON:
{"claims": [{"claim": str, "verdict": "supported|unsupported|contradicted", "sources": [id]}], "investment_advice": bool}
For transition segments (greetings, brief overviews, thanks, and sign-offs), courtesy phrases and
statements about the structure of this briefing are not factual news claims. Return an empty claims
array for those phrases. Still report any actual news fact stated in a transition as unsupported."""


def _numbers(text):
    values = set()
    for match in NUM.finditer(text):
        token = match.group(1).strip(".,").replace(",", "")
        scale = SCALES.get((match.group(2) or "").lower())
        if scale:
            number = float(token) * scale
            token = str(int(number)) if number.is_integer() else f"{number:g}"
        values.add(token)
    return values


def verify(script, stories):
    by_id = {s["story_id"]: s for s in stories}
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(lambda seg: _check(seg, by_id), script["segments"]))


def _check(seg, by_id):
    sid = seg.get("story_id")
    entry = {"story_id": sid, "advice_regex": bool(ADVICE.search(seg["text"]))}
    if sid is not None and sid not in by_id:
        entry["unknown_story_id"] = True
        return entry
    facts = by_id.get(sid, {})
    if sid is not None or seg.get("text", "").strip():
        ids = set(seg.get("fact_ids") or [])
        selected = [f for f in facts.get("facts", []) if f.get("id") in ids]
        if sid is not None:
            entry["missing_fact_ids"] = not bool(ids)
            entry["unknown_fact_ids"] = sorted(ids - {f.get("id") for f in facts.get("facts", [])})
            entry["facts_without_sources"] = [f.get("id") for f in selected if not f.get("sources")]
        src_nums = _numbers(json.dumps([selected, facts.get("conflicts", [])], ensure_ascii=False))
        # Numbers spoken as words won't match; this catches the obvious digit cases
        entry["numbers_not_in_sources"] = sorted(_numbers(seg["text"]) - src_nums)
        checked = chat_json("verify", CHEAP_MODEL, SYSTEM, json.dumps(
            {"segment": seg["text"], "segment_type": "transition" if sid is None else "news story",
             "facts": selected, "conflicts": facts.get("conflicts", [])},
            ensure_ascii=False))
        claims = checked.get("claims") if isinstance(checked, dict) else None
        # Non-story transitions may legitimately contain no factual claims.
        # Story segments require an audit entry; transition claims are rejected below.
        entry["missing_claim_audit"] = not isinstance(claims, list) or (
            sid is not None and bool(seg["text"].strip()) and not claims
        )
        article_ids = {a.get("id") for a in facts.get("articles", [])}
        fact_sources = {
            f.get("id"): [source for source in f.get("sources", []) if isinstance(source, str)]
            for f in facts.get("facts", [])
        }
        clean_claims, invalid_claims = [], []
        for claim in claims if isinstance(claims, list) else []:
            verdict = claim.get("verdict") if isinstance(claim, dict) else None
            if not isinstance(verdict, str) or verdict not in {"supported", "unsupported", "contradicted"}:
                invalid_claims.append("invalid claim verdict")
                continue
            claim_sources = claim.get("sources")
            if not isinstance(claim_sources, list) or any(not isinstance(source, str) for source in claim_sources):
                invalid_claims.append("invalid source article ids")
                claim_sources = []
            resolved_sources = []
            for source in claim_sources:
                if source in article_ids:
                    resolved_sources.append(source)
                elif source in fact_sources:
                    resolved_sources.extend(fact_sources[source])
                else:
                    invalid_claims.append("claim references unknown source article or fact")
            resolved_sources = sorted(set(resolved_sources))
            if not resolved_sources:
                invalid_claims.append("claim has no source article")
            claim["sources"] = resolved_sources
            clean_claims.append(claim)
        entry["claims"] = clean_claims
        entry["invalid_claim_audit"] = invalid_claims
        # Non-story segments (greeting/overview/sign-off) have no evidence bundle.
        # Any factual claim the verifier detects there is therefore ungrounded.
        if sid is None:
            entry["claims_without_evidence"] = bool(clean_claims)
        entry["investment_advice"] = bool(checked.get("investment_advice")) if isinstance(checked, dict) else False
    return entry


def problems(report):
    bad = []
    for r in report:
        if (r.get("advice_regex") or r.get("investment_advice") or r.get("numbers_not_in_sources")
                or r.get("missing_fact_ids") or r.get("unknown_fact_ids") or r.get("facts_without_sources")):
            bad.append(r)
        elif (r.get("missing_claim_audit") or r.get("invalid_claim_audit") or r.get("unknown_story_id")
              or r.get("claims_without_evidence")):
            bad.append(r)
        elif any(not isinstance(c, dict) or c.get("verdict") != "supported" for c in (r.get("claims") or [])):
            bad.append(r)
    return bad
