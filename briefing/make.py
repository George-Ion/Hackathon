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
    report = verify.verify(sc, picked)
    bad = verify.problems(report)
    segments = tts.segments_with_disclosure(sc, lang)
    text = "\n\n".join(s["text"] for s in segments)

    (out / f"{name}.profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{name}.script.json").write_text(json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{name}.txt").write_text(text, encoding="utf-8")
    (out / f"{name}.verify.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

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
        "minutes": round(words / script.WORDS_PER_MINUTE, 1), "flagged": len(bad) + source_issues,
        # Approximate when several briefings run at once: the cost tracker is shared
        "usd": round(COST.total() - usd_before, 4),
        "first": picked[0]["headline"] if picked else None,
    }
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    if audio and (bad or source_issues):
        raise ValueError(
            f"Audio was not generated: {len(bad)} verification flag(s) and "
            f"{source_issues} unresolved source(s). Fix the text before requesting audio."
        )
    if audio:
        timeline = tts.synthesize_briefing(segments, mp3_path, timeline_path, lang)
        rows = sources.build(segments, picked, lang, timeline)
        sources.write(rows, profile.get("name", name), out / f"{name}.sources.json", out / f"{name}.sources.md")
        source_issues = sum(1 for row in rows if row.get("warning"))
        summary["flagged"] = len(bad) + source_issues
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
    target = int(profile.get("length_minutes", 5) * script.WORDS_PER_MINUTE)
    if not target * 0.85 <= words <= target * 1.15:
        raise ValueError(f"{name}: {words} words fall outside the ±15% target range.")
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
