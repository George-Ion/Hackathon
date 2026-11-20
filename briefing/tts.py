"""Briefing audio with the ElevenLabs SDK (reads ELEVENLABS_API_KEY from .env via config).

Each script segment is its own request, stitched with previous_text/next_text so the joins
sound natural. We also write a timeline: which story (and so which source articles) is
playing at which second, so every claim in the audio can be traced to its source.
"""
import json
import os

# config must load .env before the SDK is imported: it reads ELEVENLABS_API_KEY at import time
from .config import ELEVENLABS_VOICE_ID, TTS_MODEL
from .cost import COST

from elevenlabs import ElevenLabs, VoiceSettings  # noqa: E402

DISCLOSURES = {
    "en": "This briefing is read by an AI-generated voice and was assembled automatically from news sources.",
    "nl": "Deze briefing wordt voorgelezen door een AI-stem en is automatisch samengesteld uit nieuwsbronnen.",
    "fr": "Ce bulletin est lu par une voix générée par IA et a été composé automatiquement à partir de sources d'actualité.",
    "de": "Dieses Briefing wird von einer KI-Stimme gelesen und wurde automatisch aus Nachrichtenquellen erstellt.",
}

# "News / Professional" preset from the ElevenLabs docs: steady, consistent delivery
NEWS_VOICE = VoiceSettings(stability=0.8, similarity_boost=0.6)
OUTPUT_FORMAT = "mp3_44100_128"
BYTES_PER_SEC = 128_000 / 8  # constant-bitrate mp3, good enough for timeline offsets

_client = None


def client():
    global _client
    if _client is None:
        _client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
    return _client


def segments_with_disclosure(script, language):
    disclosure = DISCLOSURES.get(language, DISCLOSURES["en"])
    return [{"story_id": None, "text": disclosure, "kind": "disclosure"}] + script["segments"]


def synthesize_briefing(segments, out_mp3, out_timeline, language="en", voice_id=None):
    voice_id = voice_id or ELEVENLABS_VOICE_ID
    timeline, t = [], 0.0
    with open(out_mp3, "wb") as f:
        for i, seg in enumerate(segments):
            resp = client().text_to_speech.with_raw_response.convert(
                text=seg["text"],
                voice_id=voice_id,
                model_id=TTS_MODEL,
                language_code=language,
                voice_settings=NEWS_VOICE,
                apply_text_normalization="on",  # "3.5%" -> "three point five percent"
                output_format=OUTPUT_FORMAT,
                previous_text=segments[i - 1]["text"] if i > 0 else None,
                next_text=segments[i + 1]["text"] if i + 1 < len(segments) else None,
            )
            with resp as r:
                audio = b"".join(r.data)
                chars = int(r.headers.get("x-character-count") or len(seg["text"]))
            COST.add_tts(chars)
            f.write(audio)
            dur = len(audio) / BYTES_PER_SEC
            timeline.append({"start_s": round(t, 2), "end_s": round(t + dur, 2),
                             "story_id": seg.get("story_id"), "text": seg["text"]})
            t += dur
    with open(out_timeline, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=2, ensure_ascii=False)
    return timeline
