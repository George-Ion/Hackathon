# The Liquid Briefing (Sourcera track)

Team **IT WORKS LOCALLY** (Georgios, Simon). Submission deadline: **Sat 21 Nov, 10:30 (GMT+1)**.

**Deliverables (from the brief):** 1) a working prototype that makes audio briefings from the dataset for at
least two listener profiles, with every claim linked to its source article; 2) a presentation covering the problem,
who pays, and the cost for the full dataset and at 10x the volume.

## Pipeline

```
data/raw/**/*.jsonl
 -> ingest    rules: Newstex fields, date window, fold DE/NL Invezz translations into the EN original   (free)
 -> cluster   text-embedding-3-small + average-linkage merging (threshold 0.78), near-copies -> duplicates (~$0.001)
 -> extract   gpt-5-mini per story: facts + figures, each with source article ids; conflicts; importance
 -> rank      rules per listener: importance + number of outlets + match on topics/publisher sections   (free)
 -> script    gpt-5 per listener: written for the ear, only the extracted facts, no investment advice, word limit
 -> verify    regex number/advice check + gpt-5-mini claim check per segment
 -> tts       ElevenLabs eleven_v4, AI-voice disclosure first, a timeline showing which story plays when
 -> sources   every claim -> outlet, title, permalink (in the listener's language when a translation exists)
```

| Judging criterion (weight) | Where it lives |
|---|---|
| Trust and accuracy (25%) | Fact ids carry article ids (`extract.py`); script uses only those facts and flags conflicts (`script.py`); `verify.py`; `out/<name>.sources.md` |
| Fit to the listener (20%) | `listeners/*.json` (language, interests, depth, length, tone); `rank.py`; the test page's wildcard editor |
| Making sense of the news (20%) | `ingest.merge_translations`, `cluster.py`, `extract.py`, global ranking |
| Scalability and cost (15%) | `cost.py` -> `out/cost.json`; the large model is used only for the script step |
| Listening experience (10%) | Script prompt: greeting, overview, stories, sign-off; hard word limit |
| Path to product (10%) | Spoken disclosure + show notes with sources; pitch TBD |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # OpenAI key; for ElevenLabs run: npx -y @elevenlabs/cli@latest onboard init
```

Unzip the Sourcera data into `data/raw/` (it's gitignored; the licence says delete it after the event).

## Run

```powershell
python run.py --since 2026-11-18 --until 2026-11-18 --no-audio   # one day, text only (~124 articles)
python run.py --since 2026-11-13                                 # the whole week, all listeners, with audio
python run.py --reuse --listener listeners/fx_trader.json        # reuse out/stories.json, skip extraction
python server.py                                                 # test page on http://localhost:8000
```

The **test page** (`server.py` + `web/index.html`) reuses `out/stories.json`. It lets you pick or edit a
listener (including the live wildcard), generate a briefing with or without audio, compare two briefings
side by side, click a timestamp to jump in the audio, and expand every claim to see its source links and
verification flags. The Stories tab shows the clustered and ranked stories.

## First results (18 Nov, 124 articles, 4 listeners, text only)
117 stories, $1.35 in total: extraction $0.73, scripts $0.52, verification $0.10, embeddings $0.001.
That was with default reasoning effort; cheap steps now use `low`, which should cut extraction cost and time.

## Open TODOs
- [ ] Get the 4 official listener profiles, the answer key and the official releases from Sourcera
- [ ] Tune `CLUSTER_THRESHOLD` against the answer key
- [ ] Briefings ran ~70% over target length -> a hard word limit was added; re-check
- [ ] Re-write segments that verify flags (loop verify -> script fix)
- [ ] Measure cost/time with low reasoning, try gpt-5-nano for extraction; write the 10x estimate
- [ ] Pitch: who pays, how it fits a newsroom's day, how the synthetic voice is disclosed
