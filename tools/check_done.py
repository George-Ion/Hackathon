"""Deterministic DONE.md checker. No API calls, no cost.

  python tools/check_done.py              # all items, audio required
  python tools/check_done.py --text-only  # skip MP3/timeline checks (items 2 audio part, 7, 9)
  python tools/check_done.py --json       # machine-readable

Exit code 0 when every checked item passes, 1 otherwise.
Items 1 (the run itself), 9 (preview page) and 11-13 need a human or a live run and are not checked here.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from briefing import ingest, verify  # noqa: E402
from briefing.tts import DISCLOSURES  # noqa: E402

OUT = ROOT / "out"
LISTENERS = ROOT / "listeners"
FX_TAGS = {"forex", "fx", "fed", "ecb", "boj", "rba", "rbnz", "boe", "interest rates", "inflation", "usd",
           "eur/usd", "gbp/usd", "usd/jpy", "central banks", "macro", "currencies", "yen", "euro", "dollar"}
STOPWORDS = {
    "nl": {"de", "het", "een", "en", "van", "is", "dat", "op", "voor", "niet"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "auf", "den"},
    "en": {"the", "and", "is", "of", "to", "in", "that", "for", "on", "with"},
}
WORDS_PER_MINUTE = 150


def load(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def guess_language(text):
    words = [w.strip(".,!?;:'\"()").lower() for w in text.split()]
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    return max(scores, key=scores.get)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--data", default=str(ROOT / "data" / "raw"))
    args = ap.parse_args()

    results = {}

    def item(key, ok, details):
        results[key] = {"pass": bool(ok), "details": details}

    names = sorted(p.stem for p in LISTENERS.glob("*.json"))
    stories = load(OUT / "stories.json", [])
    by_story = {s["story_id"]: s for s in stories}

    # 2. deliverables
    needed = ["txt", "sources.md", "sources.json", "verify.json", "script.json"] + ([] if args.text_only else ["mp3", "timeline.json"])
    missing = [f"{n}.{ext}" for n in names for ext in needed if not (OUT / f"{n}.{ext}").exists()]
    complete = [n for n in names if all((OUT / f"{n}.{ext}").exists() for ext in needed)]
    item("2_deliverables", len(complete) >= 2 and not missing,
         {"listeners": names, "complete": complete, "missing": missing})

    # 3. traceability
    urls = {}
    try:
        for a in ingest.load_articles(args.data)[0]:
            urls[a["id"]] = a["url"]
            for t in a["translations"]:
                urls[t["id"]] = t["url"]
    except Exception as e:  # data folder missing
        urls = None
        data_error = f"{type(e).__name__}: {e}"
    trace = []
    for n in names:
        sc = load(OUT / f"{n}.script.json")
        if not sc:
            trace.append(f"{n}: no script.json")
            continue
        for i, seg in enumerate(sc.get("segments", [])):
            sid = seg.get("story_id")
            if sid is None:
                continue
            story = by_story.get(sid)
            if not story:
                trace.append(f"{n} seg {i}: unknown story {sid}")
                continue
            facts = {f["id"]: f for f in story.get("facts", [])}
            arts = {a["id"]: a for a in story.get("articles", [])}
            if not seg.get("fact_ids"):
                trace.append(f"{n} seg {i}: story segment without fact ids")
            for fid in seg.get("fact_ids", []):
                f = facts.get(fid)
                if not f:
                    trace.append(f"{n} seg {i}: unknown fact {fid}")
                    continue
                srcs = f.get("sources", [])
                if not srcs:
                    trace.append(f"{n} seg {i}: fact {fid} has no sources")
                for aid in srcs:
                    if aid not in arts:
                        trace.append(f"{n} seg {i}: fact {fid} cites {aid}, not an article of story {sid}")
                    elif urls is not None and urls.get(aid) != arts[aid].get("url"):
                        trace.append(f"{n} seg {i}: article {aid} url does not match input permalink")
        rows = load(OUT / f"{n}.sources.json", [])
        warn = [r.get("warning") for r in rows if r.get("warning")]
        if warn:
            trace.append(f"{n}: sources.json warnings: {warn[:3]}")
    if urls is None:
        trace.append(f"could not load input data to check permalinks ({data_error})")
    item("3_traceability", not trace, trace[:40])

    # 4. verification
    ver = {}
    for n in names:
        rep = load(OUT / f"{n}.verify.json")
        if rep is None:
            ver[n] = "missing"
            continue
        segs = rep["segments"] if isinstance(rep, dict) and "segments" in rep else rep
        bad = verify.problems(segs)
        if bad:
            ver[n] = [{k: v for k, v in b.items() if v and k != "claims"} for b in bad][:5]
    item("4_verification", not ver, ver or "0 flags for every listener")

    # 5. personalization
    pers, order = [], {}
    for n in names:
        prof = load(LISTENERS / f"{n}.json", {})
        sc = load(OUT / f"{n}.script.json")
        txt_p = OUT / f"{n}.txt"
        if not sc or not txt_p.exists():
            pers.append(f"{n}: missing script")
            continue
        lang = prof.get("language", "en")
        guessed = guess_language(txt_p.read_text(encoding="utf-8"))
        if guessed != lang:
            pers.append(f"{n}: expected language {lang}, text looks like {guessed}")
        seen = []
        for seg in sc.get("segments", []):
            if seg.get("story_id") and seg["story_id"] not in seen:
                seen.append(seg["story_id"])
        order[n] = seen
        if n == "fx_trader":
            top5 = seen[:5]
            fx = [s for s in top5 if FX_TAGS & {t.lower() for t in by_story.get(s, {}).get("topics", [])}]
            if len(fx) < 3:
                pers.append(f"fx_trader: only {len(fx)} of top 5 stories are FX/macro ({top5})")
    top3 = {}
    for n, seq in order.items():
        top3.setdefault(tuple(seq[:3]), []).append(n)
    for k, v in top3.items():
        if len(v) > 1:
            pers.append(f"same top 3 {list(k)} for {v}")
    item("5_personalization", not pers, pers or {n: s[:5] for n, s in order.items()})

    # 6. length
    lengths, length_fail = {}, []
    for n in names:
        prof = load(LISTENERS / f"{n}.json", {})
        p = OUT / f"{n}.txt"
        if not p.exists():
            length_fail.append(f"{n}: no txt")
            continue
        words = len(p.read_text(encoding="utf-8").split())
        target = prof.get("length_minutes", 5) * WORDS_PER_MINUTE
        ratio = round(words / target, 3)
        lengths[n] = {"words": words, "target": target, "ratio": ratio}
        if not 0.85 <= ratio <= 1.15:
            length_fail.append(f"{n}: ratio {ratio}")
    item("6_length", not length_fail, length_fail or lengths)

    # 7. disclosure
    if not args.text_only:
        disc = []
        for n in names:
            prof = load(LISTENERS / f"{n}.json", {})
            tl = load(OUT / f"{n}.timeline.json")
            want = DISCLOSURES.get(prof.get("language", "en"), DISCLOSURES["en"])
            if not tl:
                disc.append(f"{n}: no timeline")
            elif tl[0].get("story_id") is not None or tl[0].get("text") != want:
                disc.append(f"{n}: first timeline entry is not the {prof.get('language')} disclosure")
        item("7_disclosure", not disc, disc or "disclosure first for every listener")

    # 8. costs
    cost_issues = []
    c = load(OUT / "cost.json")
    if not c:
        cost_issues.append("no cost.json")
    else:
        steps = c.get("measured", {}).get("steps", c.get("steps", {}))
        for name, s in steps.items():
            if not name.startswith("tts") and s.get("calls") and not s.get("in"):
                cost_issues.append(f"{name}: calls recorded but 0 input tokens (not a measured value)")
        proj = c.get("projections", {})
        if proj.get("status") != "estimated" or not proj.get("full_dataset") or not proj.get("ten_x_volume"):
            cost_issues.append("projections for full dataset and 10x missing")
    ledger = OUT / "spend.log"
    spent = None
    if ledger.exists():
        spent = round(sum(json.loads(l).get("usd", 0) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()), 4)
        try:
            from briefing.config import API_BUDGET_USD
            if spent > API_BUDGET_USD:
                cost_issues.append(f"spend.log total ${spent} exceeds budget ${API_BUDGET_USD}")
        except Exception:
            pass
    else:
        cost_issues.append("no out/spend.log ledger")
    item("8_costs", not cost_issues, cost_issues or {"total_usd": c.get("total_usd"), "ledger_usd": spent,
                                                      "full_dataset_usd": c["projections"]["full_dataset"]["estimated_usd"],
                                                      "ten_x_usd": c["projections"]["ten_x_volume"]["estimated_usd"]})

    # 10. git safety
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    bad = [f for f in tracked + staged if f == ".env" or f.startswith(("data/", "liquid-briefing-data/", "out/", "resources/"))]
    item("10_git_safety", not bad, bad or "no secrets or licensed data tracked")

    ok = all(r["pass"] for r in results.values())
    if args.json:
        print(json.dumps({"pass": ok, "items": results}, indent=2, ensure_ascii=False))
    else:
        for k, r in results.items():
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {k}")
            if not r["pass"]:
                d = r["details"]
                for line in (d if isinstance(d, list) else [d]):
                    print(f"      - {line}")
        print("ALL PASS" if ok else "SOME ITEMS FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
