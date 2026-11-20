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

    timeline = None
    if audio:
        timeline = tts.synthesize_briefing(segments, out / f"{name}.mp3", out / f"{name}.timeline.json", lang)
    elif (out / f"{name}.mp3").exists():
        (out / f"{name}.mp3").unlink()  # don't leave stale audio next to a new script
    rows = sources.build(segments, picked, lang, timeline)
    sources.write(rows, profile.get("name", name), out / f"{name}.sources.json", out / f"{name}.sources.md")

    words = len(text.split())
    summary = {
        "name": name, "language": lang, "stories": len(picked), "words": words,
        "minutes": round(words / script.WORDS_PER_MINUTE, 1), "flagged": len(bad),
        # Approximate when several briefings run at once: the cost tracker is shared
        "usd": round(COST.total() - usd_before, 4),
        "first": picked[0]["headline"] if picked else None,
    }
    (out / f"{name}.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
