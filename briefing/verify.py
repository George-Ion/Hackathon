"""Trust check (25% of the score): every story segment is checked against its extracted facts.
Cheap deterministic number check first, then a cheap-model claim check."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .config import CHEAP_MODEL
from .llm import chat_json

NUM = re.compile(
    # Scale words and the abbreviations sources use ("JPY 556.5B", "$1.2bn", "3,5 Mrd.", "2 mln").
    # Longest alternatives first; the scale must not run on into another word ("5 more", "2 Monate").
    r"(?<![\w])(\d[\d,.]*)(?:\s*(thousand|millions|million|billions|billion|trillion|tausend|millionen|"
    r"milliarden|milliarde|duizend|miljoen|miljard|bn|mrd|mio|mln|mld|tn|b|m|k)(?![a-zà-ÿ]))?",
    re.I,
)
SCALES = {
    "thousand": 1_000, "tausend": 1_000, "duizend": 1_000, "k": 1_000,
    "million": 1_000_000, "millions": 1_000_000, "millionen": 1_000_000,
    "miljoen": 1_000_000, "m": 1_000_000, "mio": 1_000_000, "mln": 1_000_000,
    "billion": 1_000_000_000, "billions": 1_000_000_000, "bn": 1_000_000_000, "b": 1_000_000_000,
    "milliarde": 1_000_000_000, "milliarden": 1_000_000_000, "mrd": 1_000_000_000,
    "miljard": 1_000_000_000, "mld": 1_000_000_000,
    "trillion": 1_000_000_000_000, "tn": 1_000_000_000_000,
}
ADVICE = re.compile(
    r"\b("
    r"you should (?:buy|sell|invest)"  # EN
    r"|buy now|sell now|good time to (?:buy|invest)|we recommend"
    r"|kaufen sie|verkaufen sie|jetzt kaufen|jetzt verkaufen"  # DE
    r"|wir empfehlen|sie sollten (?:kaufen|verkaufen|investieren)"
    r"|koop nu|verkoop nu|wij raden aan"  # NL
    r"|je moet (?:kopen|verkopen|beleggen)"
    r"|goed moment om (?:te )?(?:kopen|beleggen)"
    r")\b",
    re.I,
)

SYSTEM = """You check a spoken news segment against its source facts.
For each factual claim in the segment, decide: supported, unsupported (not in facts), or contradicted.
Also flag any investment advice. Return JSON:
{"claims": [{"claim": str, "verdict": "supported|unsupported|contradicted", "sources": [id]}], "investment_advice": bool}
For transition segments (greetings, brief overviews, thanks, and sign-offs), courtesy phrases and
statements about the structure of this briefing are not factual news claims. Return an empty claims
array for those phrases. Still report any actual news fact stated in a transition as unsupported."""


def _parse(token, decimal):
    """Read a digit token with the given decimal mark ('.' or ','); the other mark is a thousands separator."""
    thousands = "," if decimal == "." else "."
    try:
        return float(token.replace(thousands, "").replace(decimal, "."))
    except ValueError:
        return None


def _tokens(text):
    for match in NUM.finditer(text or ""):
        token = match.group(1).strip(".,")
        if token:
            yield token, SCALES.get((match.group(2) or "").lower(), 1)


def _round(value, scale):
    # 6 significant figures, so 1.5 billion and "1,5 miljard" compare as equal
    return float(f"{value * scale:.6g}")


def _numbers(text, language: str = "en"):
    """Numbers in `text`, read the way the language writes them (de/nl: 1.234,5; en: 1,234.5).
    When a token has both marks, the last one is the decimal mark whatever the language."""
    default = "," if (language or "en").lower() in {"de", "nl"} else "."
    values = set()
    for token, scale in _tokens(text):
        if "," in token and "." in token:
            decimal = "." if token.rfind(".") > token.rfind(",") else ","
        else:
            decimal = default
        value = _parse(token, decimal)
        if value is not None:
            values.add(_round(value, scale))
    return values


def _unmatched_numbers(text, language, source_numbers):
    """Numbers in a spoken segment that match no source number under ANY plausible reading.
    Scripts in German or Dutch sometimes keep the English figure format ("$3,770", "2.3%"), so a single
    language-based reading would flag correct figures; a real mismatch fails every reading."""
    default = "," if (language or "en").lower() in {"de", "nl"} else "."
    missing = set()
    for token, scale in _tokens(text):
        if "," in token and "." in token:
            preferred = "." if token.rfind(".") > token.rfind(",") else ","
            marks = [preferred]
        else:
            preferred, marks = default, [".", ","]
        readings = {_round(v, scale) for v in (_parse(token, m) for m in marks) if v is not None}
        if readings and not readings & source_numbers:
            value = _parse(token, preferred)
            missing.add(_round(value, scale) if value is not None else min(readings))
    return missing


def verify(script, stories, language: str = "en"):
    by_id = {s["story_id"]: s for s in stories}
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(lambda seg: _check(seg, by_id, language), script["segments"]))


def _check(seg, by_id, language: str = "en"):
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
        # Build source numbers only from fact texts and conflict claims (facts are in English)
        src_texts = []
        for f in selected:
            t = f.get("text")
            if isinstance(t, str):
                src_texts.append(t)
        for c in facts.get("conflicts", []) or []:
            for p in c.get("positions", []) or []:
                cl = p.get("claim")
                if isinstance(cl, str):
                    src_texts.append(cl)
        src_text = "\n".join(src_texts)
        src_nums = _numbers(src_text, language="en")
        # Years in the articles' publish dates are fine to say ("this year, 2026"); other years must be in the facts
        published_years = set()
        for a in facts.get("articles", []) or []:
            m = re.search(r"\b(19\d{2}|20\d{2}|2100)\b", str(a.get("published") or ""))
            if m:
                published_years.add(float(m.group(1)))
        # Numbers spoken as words won't match; this catches the obvious digit cases
        entry["numbers_not_in_sources"] = sorted(
            _unmatched_numbers(seg.get("text", ""), language, src_nums | published_years))
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
