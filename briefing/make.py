"""One listener's briefing from already-extracted stories: rank -> script -> verify -> TTS -> sources.
Shared by run.py (CLI) and server.py (test page)."""
import json
from pathlib import Path

from . import rank, script, sources, tts, verify
from .cost import COST


def make_briefing(profile, name, stories, out, audio=True):
    out = Path(out)
    usd_before = COST.total()
    lang = profile.get("language", "en")
    picked = rank.rank_for_listener(stories, profile)
    sc = script.write_script(profile, picked)
    report = verify.verify(sc, picked, lang)
    bad = verify.problems(report)

    # Repair loop: at most 2 rounds rewriting ONLY flagged segments
    revisions = {"initial": [], "rounds": []}
    if bad:
        # add indices for flagged segments
        def index_of_entry(rpt, entry):
            for j, item in enumerate(rpt):
                if item is entry:
                    return j
            # fallback: structural equality
            for j, item in enumerate(rpt):
                if item == entry:
                    return j
            return None
        initial = []
        for r in bad:
            i = index_of_entry(report, r)
            entry = {"index": i, "report": r}
            initial.append(entry)
        revisions["initial"] = initial
        for _round in range(2):
            # Build entries with index for the repair helper
            bad_with_index = []
            for r in bad:
                i = index_of_entry(report, r)
                if i is not None:
                    e = dict(r)
                    e["_index"] = i
                    bad_with_index.append(e)
            new_sc, changed, logs = script.revise_segments(profile, picked, sc, bad_with_index)
            # If nothing changed, stop trying further
            if not changed:
                break
            sc = new_sc
            # Re-verify ONLY the changed segments and update the report in place
            by_id = {s["story_id"]: s for s in picked}
            for i in changed:
                new_entry = verify._check(sc["segments"][i], by_id, lang)
                report[i] = new_entry
            # Recompute the problem set
            bad = verify.problems(report)
            revisions["rounds"].append({
                "changed_indices": changed,
                "logs": logs,
                "remaining": [{"index": index_of_entry(report, r), "report": r} for r in bad],
            })
            if not bad:
                break

    # Build segments and write outputs after any repairs
    segments = tts.segments_with_disclosure(sc, lang)
    text = "\n\n".join(s["text"] for s in segments)

    (out / f"{name}.profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{name}.script.json").write_text(json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")

    # Attach revision history to the verification report and save
    if revisions["initial"] or revisions["rounds"]:
        try:
            # Ensure JSON-serialisable (reports may contain sets etc., but our entries are dict/list/str/int)
            report_with_revisions = json.loads(json.dumps({"segments": report, "revisions": revisions}, ensure_ascii=False))
        except Exception:
            report_with_revisions = {"segments": report, "revisions": revisions}
    else:
        report_with_revisions = report

    (out / f"{name}.txt").write_text(text, encoding="utf-8")
    (out / f"{name}.verify.json").write_text(json.dumps(report_with_revisions, indent=2, ensure_ascii=False), encoding="utf-8")

    mp3_path = out / f"{name}.mp3"
    timeline_path = out / f"{name}.timeline.json"
    if mp3_path.exists():
        mp3_path.unlink()  # never leave audio from an older script beside this one
    if timeline_path.exists():
        timeline_path.unlink()

    # Save the text edition and source notes before TTS. A voice/API failure should
    # leave a useful text briefing, not a stale or missing edition in the preview.
    rows = sources.build(segments, picked, lang)
    sources.write(rows, profile.get("name", name), out / f"{name}.sources.json", out / f"{name}.sources.md")
    source_issues = sum(1 for row in rows if row.get("warning"))

    words = len(text.split())
    spoken_story_ids = {s.get("story_id") for s in sc.get("segments", []) if s.get("story_id")}
    summary = {
        "name": name, "language": lang, "stories": len(spoken_story_ids), "words": words,
        "minutes": round(words / script.WORDS_PER_MINUTE, 1), "flagged": len(verify.problems(report)) + source_issues,
        # Approximate when several briefings run at once: the cost tracker is shared
        "usd": round(COST.total() - usd_before, 4),
        "first": picked[0]["headline"] if picked else None,
    }
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Enforce the same length bounds before generating audio (browser path uses this).
    low, high = script.length_bounds(profile)
    if audio and not (low <= words <= high):
        raise ValueError(f"{name}: {words} words fall outside the ±15% target range ({low}-{high}).")

    unresolved = verify.problems(report)
    if audio and (unresolved or source_issues):
        raise ValueError(
            f"Audio was not generated: {len(unresolved)} verification flag(s) and "
            f"{source_issues} unresolved source(s). Fix the text before requesting audio."
        )
    if audio:
        timeline = tts.synthesize_briefing(segments, mp3_path, timeline_path, lang)
        rows = sources.build(segments, picked, lang, timeline)
        sources.write(rows, profile.get("name", name), out / f"{name}.sources.json", out / f"{name}.sources.md")
        source_issues = sum(1 for row in rows if row.get("warning"))
        summary["flagged"] = len(verify.problems(report)) + source_issues
        summary["usd"] = round(COST.total() - usd_before, 4)
        (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def validate_saved_briefing(profile, name, stories, out):
    """Check a saved text edition without making API calls."""
    out = Path(out)
    lang = profile.get("language", "en")
    script_path = out / f"{name}.script.json"
    verify_path = out / f"{name}.verify.json"
    if not script_path.exists() or not verify_path.exists():
        raise ValueError(f"{name}: saved script and verification report are required for audio-only mode.")
    sc = json.loads(script_path.read_text(encoding="utf-8"))
    report = json.loads(verify_path.read_text(encoding="utf-8"))
    bad = verify.problems(report)
    if bad:
        raise ValueError(f"{name}: refusing audio because {len(bad)} verification flag(s) remain.")
    segments = tts.segments_with_disclosure(sc, lang)
    text = "\n\n".join(s["text"] for s in segments)
    words = len(text.split())
    low, high = script.length_bounds(profile)
    if not (low <= words <= high):
        raise ValueError(f"{name}: {words} words fall outside the ±15% target range ({low}-{high}).")
    picked = rank.rank_for_listener(stories, profile)
    rows = sources.build(segments, picked, lang)
    source_issues = sum(1 for row in rows if row.get("warning"))
    if source_issues:
        raise ValueError(f"{name}: refusing audio because {source_issues} source link(s) are unresolved.")
    return {"script": sc, "report": report, "segments": segments, "words": words, "picked": picked}


def synthesize_saved_briefing(profile, name, stories, out):
    """Create audio and source timings from an existing, verified text edition."""
    out = Path(out)
    usd_before = COST.total()
    checked = validate_saved_briefing(profile, name, stories, out)
    sc, report = checked["script"], checked["report"]
    segments, words, picked = checked["segments"], checked["words"], checked["picked"]
    lang = profile.get("language", "en")

    mp3_path = out / f"{name}.mp3"
    timeline_path = out / f"{name}.timeline.json"
    if mp3_path.exists():
        mp3_path.unlink()
    if timeline_path.exists():
        timeline_path.unlink()
    timeline = tts.synthesize_briefing(segments, mp3_path, timeline_path, lang)
    rows = sources.build(segments, picked, lang, timeline)
    sources.write(rows, profile.get("name", name), out / f"{name}.sources.json", out / f"{name}.sources.md")
    summary = {
        "name": name, "language": lang,
        "stories": len({s.get("story_id") for s in sc.get("segments", []) if s.get("story_id")}),
        "words": words, "minutes": round(words / script.WORDS_PER_MINUTE, 1),
        "flagged": 0, "usd": round(COST.total() - usd_before, 4),
        "first": picked[0]["headline"] if picked else None,
    }
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
