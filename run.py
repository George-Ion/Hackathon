"""End-to-end: ingest -> cluster -> extract -> rank -> script -> verify -> TTS -> sources.

  python run.py --since 2026-11-18 --until 2026-11-18 --no-audio    # one day, text only
  python run.py --since 2026-11-13                                  # the whole week, with audio
  python run.py --reuse --listener listeners/wildcard.json          # live wildcard: skip clustering/extraction
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from briefing import cluster, cost, extract, ingest, make, rank


def build_stories(args, out):
    articles, merged = ingest.load_articles(args.data, args.since, args.until)
    articles = articles[: args.limit]
    print(f"{len(articles)} articles ({merged} translations folded into their English original)")

    stories = cluster.cluster(articles)
    print(f"{len(stories)} stories after clustering")

    with ThreadPoolExecutor(8) as pool:
        facts = list(pool.map(extract.extract_story, stories))
    facts.sort(key=rank.global_score, reverse=True)
    (out / "stories.json").write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    return facts, len(articles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--since", default="2026-11-13", help="first day, ISO date (UTC)")
    ap.add_argument("--until", help="last day, ISO date, inclusive")
    ap.add_argument("--listener", action="append")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reuse", action="store_true", help="reuse out/stories.json instead of re-extracting")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)

    if args.reuse and (out / "stories.json").exists():
        facts = json.loads((out / "stories.json").read_text(encoding="utf-8"))
        n_articles = sum(len(s["articles"]) for s in facts)
        print(f"Reusing {len(facts)} stories from {out / 'stories.json'}")
    else:
        facts, n_articles = build_stories(args, out)

    listener_files = args.listener or sorted(str(p) for p in Path("listeners").glob("*.json"))

    def one_listener(lf):
        profile = json.loads(Path(lf).read_text(encoding="utf-8"))
        s = make.make_briefing(profile, Path(lf).stem, facts, out, audio=not args.no_audio)
        return (f"[{s['name']}] {s['language']} | {s['stories']} stories | {s['words']} words (~{s['minutes']} min) | "
                f"{s['flagged']} segments flagged | first: {s['first'] or '-'}")

    with ThreadPoolExecutor(4) as pool:
        for line in pool.map(one_listener, listener_files):
            print(line)

    print(cost.COST.report(n_articles, len(listener_files)))
    cost.COST.to_json(out / "cost.json")


if __name__ == "__main__":
    main()
