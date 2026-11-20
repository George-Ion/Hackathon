"""End-to-end: ingest -> cluster -> extract -> rank -> script -> verify -> TTS -> sources.

  python run.py --since 2026-11-18 --until 2026-11-18 --no-audio    # one day, text only
  python run.py --since 2026-11-13                                  # the whole week, with audio
  python run.py --reuse --listener listeners/wildcard.json          # live wildcard: skip clustering/extraction
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from briefing import cluster, cost, extract, ingest, make, prerank, rank


def extract_stories_with_retry(stories, out_dir: Path):
    """Run extract.extract_story for each clustered story with up to two attempts.
    On final failure, record {story_id, error} under out/extract_errors.json and continue.
    Returns (facts, errors_list).
    """
    facts = []
    errors = []

    def do_one(story):
        sid = story.get("story_id")
        last_exc = None
        for _ in range(2):
            try:
                return ("ok", extract.extract_story(story))
            except Exception as e:  # noqa: BLE001 - we want to capture and log any failure
                last_exc = e
        # both attempts failed
        err_msg = f"{type(last_exc).__name__}: {last_exc}"
        return ("err", {"story_id": sid, "error": err_msg})

    with ThreadPoolExecutor(8) as pool:
        jobs = {pool.submit(do_one, s): s for s in stories}
        for job in as_completed(jobs):
            status, payload = job.result()
            if status == "ok":
                facts.append(payload)
            else:
                errors.append(payload)

    if errors:
        (out_dir / "extract_errors.json").write_text(
            json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return facts, errors


def build_stories(args, out):
    articles, merged, bad_dates = ingest.load_articles(args.data, args.since, args.until)
    articles = articles[: args.limit]
    print(f"{len(articles)} articles ({merged} translations folded into their English original, {bad_dates} rows with bad dates skipped)")

    stories = cluster.cluster(articles)
    print(f"{len(stories)} stories after clustering")

    # Pre-rank with free signals; extract only stories that can reach a briefing
    profiles = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path("listeners").glob("*.json"))}
    if args.extract_all or not profiles:
        selected = stories
    else:
        keep, rows = prerank.shortlist(stories, [s["_vec"] for s in stories], profiles)
        (out / "prerank.json").write_text(json.dumps({
            "groups": len(stories), "shortlisted": len(keep), "k_per_listener": prerank.K_PER_LISTENER,
            "k_global": prerank.K_GLOBAL, "listeners": list(profiles), "stories": rows}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        selected = [s for s in stories if s["story_id"] in keep]
        # Shortlist size is capped by listener count, not article volume: tell the cost projection
        cap = prerank.K_GLOBAL + prerank.K_PER_LISTENER * len(profiles)
        cost.COST.extract_cap_ratio = cap / max(1, len(selected))
    print(f"{len(selected)} of {len(stories)} stories shortlisted for extraction")

    facts, errors = extract_stories_with_retry(selected, out)
    facts.sort(key=rank.global_score, reverse=True)
    (out / "stories.json").write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    if errors:
        print(f"{len(errors)} storie(s) failed during extraction; see {out / 'extract_errors.json'}")
    return facts, len(articles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--since", help="first day, ISO date (UTC); default: include all supplied feed dates")
    ap.add_argument("--until", help="last day, ISO date, inclusive")
    ap.add_argument("--listener", action="append")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reuse", action="store_true", help="reuse out/stories.json instead of re-extracting")
    ap.add_argument("--extract-all", action="store_true", help="skip pre-ranking and extract every story group")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--audio-only", action="store_true", help="synthesize audio from existing verified scripts without model calls")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)

    if args.audio_only:
        if args.no_audio:
            ap.error("--audio-only cannot be combined with --no-audio")
        if not (out / "stories.json").exists():
            raise SystemExit(f"No {out / 'stories.json'} found; generate a text run first.")
        facts = json.loads((out / "stories.json").read_text(encoding="utf-8"))
        prior_cost = json.loads((out / "cost.json").read_text(encoding="utf-8")) if (out / "cost.json").exists() else {}
        cost.COST.restore(prior_cost)
        measured = prior_cost.get("measured", {})
        n_articles = measured.get("articles") or sum(
            len(s.get("articles", [])) + len(s.get("duplicate_ids", [])) for s in facts
        )
        listener_runs = measured.get("listeners") or len(list(Path("listeners").glob("*.json")))
        listener_files = args.listener or sorted(str(p) for p in Path("listeners").glob("*.json"))

        def one_audio(lf):
            profile = json.loads(Path(lf).read_text(encoding="utf-8"))
            s = make.synthesize_saved_briefing(profile, Path(lf).stem, facts, out)
            return f"[{s['name']}] audio ready | {s['words']} words | {s['minutes']} min"

        failures = []
        for lf in listener_files:
            try:
                profile = json.loads(Path(lf).read_text(encoding="utf-8"))
                make.validate_saved_briefing(profile, Path(lf).stem, facts, out)
            except Exception as e:
                failures.append((lf, e))
                print(f"[{Path(lf).stem}] PREFLIGHT ERROR: {type(e).__name__}: {e}")
        if not failures:
            for lf in listener_files:
                try:
                    print(one_audio(lf))
                except Exception as e:
                    failures.append((lf, e))
                    print(f"[{Path(lf).stem}] ERROR: {type(e).__name__}: {e}")
                    break

        full_articles, _, _ = ingest.load_articles(args.data)
        full_dataset_articles = len(full_articles)
        print(cost.COST.report(n_articles, listener_runs, full_dataset_articles))
        cost.COST.to_json(out / "cost.json", n_articles, listener_runs, full_dataset_articles)
        if failures:
            failed = ", ".join(Path(path).stem for path, _ in failures)
            raise RuntimeError(f"{len(failures)} audio briefing(s) failed: {failed}. Cost report saved to {out / 'cost.json'}.")
        return

    if args.reuse and (out / "stories.json").exists():
        facts = json.loads((out / "stories.json").read_text(encoding="utf-8"))
        # Repair invalid source ids in-place so --reuse runs have clean data without API calls
        total_dropped_sources = 0
        total_dropped_facts = 0
        for s in facts:
            before_ds = s.get("dropped_sources", 0)
            before_df = s.get("dropped_facts", 0)
            extract.clean_story(s)
            total_dropped_sources += s.get("dropped_sources", 0) - before_ds
            total_dropped_facts += s.get("dropped_facts", 0) - before_df
        if total_dropped_sources or total_dropped_facts:
            (out / "stories.json").write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Repaired sources in reused stories: -{total_dropped_sources} source refs, -{total_dropped_facts} empty facts")
        prior_cost = json.loads((out / "cost.json").read_text(encoding="utf-8")) if (out / "cost.json").exists() else {}
        cost.COST.restore(prior_cost)
        measured = prior_cost.get("measured", {})
        n_articles = measured.get("articles") or sum(
            len(s.get("articles", [])) + len(s.get("duplicate_ids", [])) for s in facts
        )
        prior_listener_runs = measured.get("listeners")
        if prior_listener_runs is None:
            prior_listener_runs = sum(
                values.get("calls", 0) for step, values in prior_cost.get("steps", {}).items()
                if step.startswith("script (")
            )
        print(f"Reusing {len(facts)} stories from {out / 'stories.json'}")
    else:
        facts, n_articles = build_stories(args, out)
        prior_listener_runs = 0

    listener_files = args.listener or sorted(str(p) for p in Path("listeners").glob("*.json"))

    def one_listener(lf):
        profile = json.loads(Path(lf).read_text(encoding="utf-8"))
        s = make.make_briefing(profile, Path(lf).stem, facts, out, audio=False)
        return (f"[{s['name']}] {s['language']} | {s['stories']} stories | {s['words']} words (~{s['minutes']} min) | "
                f"{s['flagged']} segments flagged | first: {s['first'] or '-'}")

    failures = []
    with ThreadPoolExecutor(4) as pool:
        jobs = {pool.submit(one_listener, lf): lf for lf in listener_files}
        for job in as_completed(jobs):
            try:
                print(job.result())
            except Exception as e:
                failures.append((jobs[job], e))
                print(f"[{Path(jobs[job]).stem}] ERROR: {type(e).__name__}: {e}")

    listener_runs = prior_listener_runs + len(listener_files)
    full_articles, _, _ = ingest.load_articles(args.data)
    full_dataset_articles = len(full_articles)

    if not args.no_audio:
        # Validate every listener before any TTS request, then synthesize serially so the shared
        # budget check cannot race. A listener that fails its text or preflight check gets no audio,
        # but no longer blocks audio for the listeners that passed.
        failed = {lf for lf, _ in failures}
        ready = []
        for lf in listener_files:
            if lf in failed:
                continue
            try:
                profile = json.loads(Path(lf).read_text(encoding="utf-8"))
                make.validate_saved_briefing(profile, Path(lf).stem, facts, out)
                ready.append(lf)
            except Exception as e:
                failures.append((lf, e))
                print(f"[{Path(lf).stem}] PREFLIGHT ERROR: {type(e).__name__}: {e}")
        if ready:
            for lf in ready:
                try:
                    profile = json.loads(Path(lf).read_text(encoding="utf-8"))
                    s = make.synthesize_saved_briefing(profile, Path(lf).stem, facts, out)
                    print(f"[{s['name']}] audio ready | {s['words']} words | {s['minutes']} min")
                except Exception as e:
                    failures.append((lf, e))
                    print(f"[{Path(lf).stem}] AUDIO ERROR: {type(e).__name__}: {e}")
                    break

    # Print session spend (this process only) and the cumulative report
    print(f"Session spend this run: ${cost.COST.session_usd():.4f}")
    print(cost.COST.report(n_articles, listener_runs, full_dataset_articles))
    cost.COST.to_json(out / "cost.json", n_articles, listener_runs, full_dataset_articles)
    if failures:
        failed = ", ".join(Path(path).stem for path, _ in failures)
        raise RuntimeError(f"{len(failures)} listener briefing(s) failed: {failed}. Cost report saved to {out / 'cost.json'}.")


if __name__ == "__main__":
    main()
