"""Claim -> source article links for one briefing (the "every claim linked to its source" deliverable).

Writes <name>.sources.json (machine-readable) and <name>.sources.md (show notes a listener or juror
can open next to the audio). Links point to the article in the listener's language when a
translation exists. No article text is copied, only titles and links (licence)."""
import json


def _link(article, language):
    for t in article.get("translations", []):
        if t["language"] == language and t.get("url"):
            return t["url"], t.get("title") or article["title"]
    return article["url"], article["title"]


def build(segments, stories, language, timeline=None):
    by_story = {s["story_id"]: s for s in stories}
    times = {i: t for i, t in enumerate(timeline or [])}
    rows = []
    for i, seg in enumerate(segments):
        story = by_story.get(seg.get("story_id"))
        row = {"segment": i, "story_id": seg.get("story_id"), "text": seg["text"],
               "start_s": times.get(i, {}).get("start_s"), "end_s": times.get(i, {}).get("end_s"), "claims": []}
        if story:
            facts = {f["id"]: f for f in story.get("facts", [])}
            arts = {a["id"]: a for a in story["articles"]}
            fact_ids = seg.get("fact_ids") or list(facts)  # fall back to all story facts if the writer skipped ids
            for fid in fact_ids:
                f = facts.get(fid)
                if not f:
                    row["claims"].append({"fact_id": fid, "fact": None, "sources": [], "warning": "unknown fact id"})
                    continue
                srcs = []
                for aid in f.get("sources", []):
                    if aid in arts:
                        url, title = _link(arts[aid], language)
                        srcs.append({"outlet": arts[aid]["outlet"], "title": title, "url": url,
                                     "published": arts[aid]["published"]})
                row["claims"].append({"fact_id": fid, "fact": f["text"], "sources": srcs})
            row["conflicts"] = story.get("conflicts", [])
        rows.append(row)
    return rows


def _ts(s):
    return "--:--" if s is None else f"{int(s // 60):02d}:{int(s % 60):02d}"


def to_markdown(rows, listener_name):
    out = [f"# Sources for {listener_name}'s briefing", "",
           "Read by an AI-generated voice. Every claim below links to the article it came from.", ""]
    for r in rows:
        if not r["claims"]:
            continue
        out.append(f"## {_ts(r['start_s'])} · {r['text'][:90]}…")
        for c in r["claims"]:
            out.append(f"- {c['fact'] or c['fact_id']}")
            for s in c["sources"]:
                out.append(f"  - [{s['outlet']}: {s['title']}]({s['url']}) ({s['published'][:10]})")
        for k in r.get("conflicts", []):
            out.append(f"- **Sources disagree:** {k.get('issue')}")
        out.append("")
    return "\n".join(out)


def write(rows, listener_name, json_path, md_path):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(rows, listener_name))
