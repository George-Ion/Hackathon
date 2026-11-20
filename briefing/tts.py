"""Briefing audio through ElevenLabs REST (reads ELEVENLABS_API_KEY from .env via config).

Each script segment is its own request, stitched with previous_text/next_text so the joins
sound natural. We also write a timeline: which story (and so which source articles) is
playing at which second, so every claim in the audio can be traced to its source.
"""
import json
import os
import requests
from pathlib import Path

# config loads .env before the API key is read.
from .config import API_BUDGET_USD, ELEVENLABS_VOICE_ID, TTS_MODEL, TTS_PER_1K_CHARS
from .cost import COST, ensure_budget

DISCLOSURES = {
    "en": "This briefing is read by an AI-generated voice and was assembled automatically from news sources.",
    "nl": "Deze briefing wordt voorgelezen door een AI-stem en is automatisch samengesteld uit nieuwsbronnen.",
    "fr": "Ce bulletin est lu par une voix produite par IA et assemble automatiquement a partir de sources d actualite.",
    "de": "Dieses Briefing wird von einer KI-Stimme gelesen und wurde automatisch aus Nachrichtenquellen erstellt.",
}

# "News / Professional" preset from the ElevenLabs docs: steady, consistent delivery
OUTPUT_FORMAT = "mp3_44100_128"
BYTES_PER_SEC = 128_000 / 8  # constant-bitrate mp3, good enough for timeline offsets


_BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
             2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def clean_mp3(data: bytes) -> bytes:
    """Keep only MPEG audio frames: drop ID3 tags and Xing/Info header frames.

    Each ElevenLabs clip starts with its own ID3 tag and an Info frame that states the clip's length
    and a seek table. Glued together, the first clip's table claims the whole file is a few seconds
    long, so browsers jump to the wrong place when you skip. Without them the file is plain
    constant-bitrate MP3, where every second maps to a fixed byte offset."""
    out, p, n = bytearray(), 0, len(data)
    while p + 4 <= n:
        if data[p:p + 3] == b"ID3" and p + 10 <= n:
            size = (data[p + 6] << 21) | (data[p + 7] << 14) | (data[p + 8] << 7) | data[p + 9]
            p += 10 + size + (10 if data[p + 5] & 0x10 else 0)
            continue
        if data[p:p + 3] == b"TAG" and p + 128 <= n:  # ID3v1 at a clip end
            p += 128
            continue
        b1, b2 = data[p + 1], data[p + 2]
        if data[p] == 0xFF and (b1 & 0xE0) == 0xE0 and ((b1 >> 1) & 3) == 1:  # frame sync, Layer III
            ver = (b1 >> 3) & 3
            br_i, sr_i = b2 >> 4, (b2 >> 2) & 3
            if ver != 1 and 0 < br_i < 15 and sr_i < 3:
                br = _BITRATES[1 if ver == 3 else 2][br_i] * 1000
                sr = _RATES[ver][sr_i]
                length = (144 if ver == 3 else 72) * br // sr + ((b2 >> 1) & 1)
                frame = data[p:p + length]
                if b"Xing" not in frame[:64] and b"Info" not in frame[:64]:
                    out += frame
                p += length
                continue
        p += 1  # not a frame boundary: resync
    return bytes(out)

def client():
    # Keep TTS independent of the generated SDK package. Its OpenAPI wheel has
    # very long file names that fail to install on some Windows setups.
    return os.environ.get("ELEVENLABS_API_KEY")


def segments_with_disclosure(script, language):
    disclosure = DISCLOSURES.get(language, DISCLOSURES["en"])
    return [{"story_id": None, "text": disclosure, "kind": "disclosure"}] + script["segments"]


def synthesize_briefing(segments, out_mp3, out_timeline, language="en", voice_id=None):
    voice_id = voice_id or ELEVENLABS_VOICE_ID
    api_key = client()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing; audio cannot be generated.")
    out_mp3 = Path(out_mp3)
    tmp_mp3 = out_mp3.with_suffix(out_mp3.suffix + ".partial")
    timeline, t = [], 0.0
    try:
        with open(tmp_mp3, "wb") as f:
            for i, seg in enumerate(segments):
                estimated_cost = len(seg["text"]) / 1000 * TTS_PER_1K_CHARS
                # Use cumulative ledger for budget enforcement across processes
                ensure_budget(estimated_cost, "tts", "elevenlabs")
                payload = {
                    "text": seg["text"],
                    "model_id": TTS_MODEL,
                    "language_code": language,
                    "voice_settings": {"stability": 0.8, "similarity_boost": 0.6},
                    "apply_text_normalization": "on",  # "3.5%" -> spoken number
                    "previous_text": segments[i - 1]["text"] if i > 0 else None,
                    "next_text": segments[i + 1]["text"] if i + 1 < len(segments) else None,
                }
                resp = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    params={"output_format": OUTPUT_FORMAT},
                    headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=120,
                )
                if not resp.ok:
                    raise RuntimeError(f"ElevenLabs TTS failed ({resp.status_code}): {resp.text[:500]}")
                audio = clean_mp3(resp.content)
                if not audio:
                    raise RuntimeError("ElevenLabs returned an empty audio response.")
                chars = int(resp.headers.get("x-character-count") or len(seg["text"]))
                COST.add_tts(chars)
                f.write(audio)
                dur = len(audio) / BYTES_PER_SEC
                timeline.append({"start_s": round(t, 2), "end_s": round(t + dur, 2),
                                 "story_id": seg.get("story_id"), "text": seg["text"]})
                t += dur
        tmp_mp3.replace(out_mp3)
    except Exception:
        tmp_mp3.unlink(missing_ok=True)
        raise
    with open(out_timeline, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=2, ensure_ascii=False)
    return timeline
