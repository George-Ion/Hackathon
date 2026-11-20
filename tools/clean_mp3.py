"""Clean existing briefing MP3s in place (no API calls): drop per-clip ID3 tags and Xing/Info frames,
so skipping in the browser lands at the right second. Timelines are rescaled to the cleaned length.

  python tools/clean_mp3.py            # every out/*.mp3
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from briefing.tts import BYTES_PER_SEC, clean_mp3  # noqa: E402

for mp3 in sorted(Path("out").glob("*.mp3")):
    raw = mp3.read_bytes()
    clean = clean_mp3(raw)
    if len(clean) == len(raw):
        print(f"{mp3.name}: already clean")
        continue
    mp3.write_bytes(clean)
    tl = mp3.with_suffix(".timeline.json")
    if tl.exists():  # segment times were computed from the raw byte counts
        rows = json.loads(tl.read_text(encoding="utf-8"))
        k = (len(clean) / BYTES_PER_SEC) / max(rows[-1]["end_s"], 1e-9)
        for r in rows:
            r["start_s"], r["end_s"] = round(r["start_s"] * k, 2), round(r["end_s"] * k, 2)
        tl.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{mp3.name}: {len(raw):,} -> {len(clean):,} bytes ({(len(raw)-len(clean))/1024:.1f} KB of headers removed)")
