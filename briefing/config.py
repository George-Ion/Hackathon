"""Settings read from .env: models, prices, budget, voices and grouping thresholds."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the project's .env no matter where the script is started from
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CHEAP_MODEL = os.getenv("CHEAP_MODEL", "gpt-5-mini")
LARGE_MODEL = os.getenv("LARGE_MODEL", "gpt-5")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

# USD per 1M tokens
PRICES = {
    CHEAP_MODEL: (float(os.getenv("CHEAP_IN", 0.25)), float(os.getenv("CHEAP_OUT", 2.0))),
    LARGE_MODEL: (float(os.getenv("LARGE_IN", 1.25)), float(os.getenv("LARGE_OUT", 10.0))),
    EMBED_MODEL: (float(os.getenv("EMBED_IN", 0.02)), 0.0),
}
# Reasoning models think before answering; the bulk steps don't need much of it.
# Set to "" in .env to send no reasoning_effort (for non-reasoning models like gpt-4.1-mini).
REASONING = {m: e for m, e in {
    CHEAP_MODEL: os.getenv("CHEAP_REASONING", "low"),
    LARGE_MODEL: os.getenv("LARGE_REASONING", "medium"),
}.items() if e}
TTS_PER_1K_CHARS =float(os.getenv("TTS_PER_1K_CHARS", 0.18))
API_BUDGET_USD = float(os.getenv("API_BUDGET_USD", 5.0))

# The ElevenLabs SDK reads ELEVENLABS_API_KEY from the environment itself
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # George, pre-made
# ElevenLabs pre-made voices a listener can pick (all speak English, Dutch and German with the
# multilingual model). Checked against this account's key on 21 Nov.
VOICES = [
    {"id": "JBFqnCBsd6RMkjVDRZzb", "name": "George", "about": "British, male, warm"},
    {"id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel", "about": "British, male, news presenter"},
    {"id": "Xb7hH8MSUJpSbSDYk0k2", "name": "Alice", "about": "British, female, clear"},
    {"id": "pFZP5JQG7iQjIQuC4Bku", "name": "Lily", "about": "British, female, warm"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "about": "American, female, calm"},
    {"id": "nPczCjzI2devNBz1zQrb", "name": "Brian", "about": "American, male, deep"},
]


def voice_for(profile):
    """The listener's chosen voice if it is one of VOICES, else the default."""
    wanted = (profile or {}).get("voice_id")
    return wanted if any(v["id"] == wanted for v in VOICES) else ELEVENLABS_VOICE_ID
TTS_MODEL = os.getenv("TTS_MODEL", "eleven_v4")

# Articles whose embeddings are at least this similar are treated as the same event
# 0.78 tuned by eye on 16-18 Nov: >=0.80 is nearly always the same event, <0.75 is "related topic"
CLUSTER_THRESHOLD = float(os.getenv("CLUSTER_THRESHOLD", 0.78))
# Borderline pairs (similarity between CLUSTER_CONFIRM_LOW and CLUSTER_THRESHOLD) are checked by the
# small model ("same specific event?") before merging. Set CLUSTER_CONFIRM=0 to switch this off.
CLUSTER_CONFIRM = os.getenv("CLUSTER_CONFIRM", "1") not in ("0", "false", "no", "")
CLUSTER_CONFIRM_LOW = float(os.getenv("CLUSTER_CONFIRM_LOW", 0.62))
