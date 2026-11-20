"""Trust check (25% of the score): every story segment is checked against its extracted facts.
Cheap deterministic number check first, then a cheap-model claim check."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .config import CHEAP_MODEL
from .llm import chat_json

NUM = re.compile(r"\d[\d,.]*")
ADVICE = re.compile(r"\b(you should (buy|sell|invest)|buy now|sell now|good time to (buy|invest)|we recommend)\b", re.I)

SYSTEM = """You check a spoken news segment against its source facts.
For each factual claim in the segment, decide: supported, unsupported (not in facts), or contradicted.
Also flag any investment advice. Return JSON:
{"claims": [{"claim": str, "verdict": "supported|unsupported|contradicted", "sources": [id]}], "investment_advice": bool}"""


def _numbers(text):
    return {n.strip(".,").replace(",", "") for n in NUM.findall(text)}


def verify(script, stories):
    by_id = {s["story_id"]: s for s in stories}
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(lambda seg: _check(seg, by_id), script["segments"]))


def _check(seg, by_id):
    sid = seg.get("story_id")
    entry = {"story_id": sid, "advice_regex": bool(ADVICE.search(seg["text"]))}
    if sid in by_id:
        facts = by_id[sid]
        src_nums = _numbers(json.dumps([facts.get("facts", []), facts.get("conflicts", [])], ensure_ascii=False))
        # Numbers spoken as words won't match; this catches the obvious digit cases
        entry["numbers_not_in_sources"] = sorted(_numbers(seg["text"]) - src_nums)
        entry.update(chat_json("verify", CHEAP_MODEL, SYSTEM, json.dumps(
            {"segment": seg["text"], "facts": facts["facts"], "conflicts": facts.get("conflicts", [])},
            ensure_ascii=False)))
    return entry


def problems(report):
    bad = []
    for r in report:
        if r.get("advice_regex") or r.get("investment_advice") or r.get("numbers_not_in_sources"):
            bad.append(r)
        elif any(c["verdict"] != "supported" for c in r.get("claims", [])):
            bad.append(r)
    return bad
