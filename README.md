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
| Path to product (10%) | Spoken disclosure + show notes with sources; `docs/pitch.md` |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env   # add API keys; ElevenLabs key needs Text to Speech permission
```

Use only `.venv` (Python 3.14). Running `server.py` with another Python (for example Anaconda's) starts a page
that can't find the OpenAI package and greys out "Generate edition".

Place the Sourcera JSONL feed files in `data/raw/` (it's gitignored; delete licensed article data after the event).

## Run

```powershell
python run.py --since 2026-11-18 --until 2026-11-18              # one day, scripts and audio
python run.py --since 2026-07-28 --until 2026-11-20              # supplied feeds, including the Zacks sample
python run.py --reuse --listener listeners/fx_trader.json        # reuse out/stories.json, skip extraction
python run.py --audio-only                                       # make MP3s from saved, verified scripts
python server.py                                                 # test page on http://localhost:8000
```

With no `--since` argument, the runner includes all dates in the supplied feed files. Use an explicit window for
daily editions; the Zacks sample has July dates while the other feeds cover the hackathon week.

Audio is synthesized through the ElevenLabs REST API using `requests`; no ElevenLabs SDK install is required.
Every paid call (OpenAI and ElevenLabs) is appended to `out/spend.log`; `API_BUDGET_USD` in `.env` (default $5)
caps the ledger total. Text-only runs delete a listener's old MP3 on purpose, so stale audio never plays with a
new script: make audio last, with `--audio-only`.

## Checks and agents

```powershell
python -m unittest discover -s tests                # unit tests, no API calls
python tools/check_done.py                          # DONE.md checklist, no API calls (--text-only before audio)
python agents/run_agents.py --tasks P1-1 --budget 3 # GPT-5 worker + critic for a task in AGENT_PLAN.md
```

The agent runner commits each task the critic passes on the current branch (never pushes), and logs every call and
its cost to `agents/logs/`.

The **test page** (`server.py` + `web/index.html`) reuses `out/stories.json`. It lets you pick or edit a
listener (including the live wildcard), generate a briefing with or without audio, compare two briefings
side by side, click a timestamp to jump in the audio, and expand every claim to see its source links and
verification flags. The Stories tab shows the clustered and ranked stories.

## Final run (21 Nov, data of 18 Nov: 124 articles, 4 listeners + 1 live wildcard)
Fresh run from an empty `out/`. `python tools/check_done.py` passes every item (2-8, 10).

**Making sense of the news.** Embedding grouping plus a small-model check of borderline pairs
(digests and roundups never merge that way) turns 124 articles into **99 stories**. Before, there were 117,
and 6 stories now combine several outlets instead of 1. Examples: the Anthropic IPO (7 articles), Nvidia
earnings with the market reaction (10), and the oil report in English, Dutch and German.

**Pre-ranking.** Free signals (coverage, recency, listener fit by embeddings and interest terms) shortlist
**36 of 99 stories**. Only those are extracted, so 64% of stories never reach a model.

| Listener | Language | Stories | Words | Script | Voice | Flags |
|---|---|---|---|---|---|---|
| fx_trader | en | 6 | 695 | $0.25 | $0.78 | 0 |
| world_listener | en | 4 | 409 | $0.23 | $0.48 | 0 |
| german_investor | de | 4 | 843 | $0.11 | $1.03 | 0 |
| dutch_investor | nl | 4 | 529 | $0.14 | $0.67 | 0 |
| live wildcard | en | 3 | 405 | $0.16 | $0.47 | 0 |

Per-listener costs are exact: every API call is tagged with the listener it belongs to.

**Cost for the whole edition: $4.42 measured.**
- Shared steps: embeddings $0.001, grouping check $0.008, extraction of 36 stories $0.09.
- Per listener: scripts $0.85 and verification $0.04, for all listeners together.
- Voice: $3.43.

**Estimates:** full dataset (1,502 articles) **$4.51**; 10x volume (15,020 articles) **$4.60**. The
article-dependent part grows from $0.10 to under $0.30, because extraction is capped by the listener count;
nearly all of the cost is the voice, which depends on listeners, not articles.

Voice is priced at `TTS_PER_1K_CHARS` ($0.18 per 1,000 characters, set in `.env`), and OpenAI token prices
come from `.env` too. Check both against your actual plans before quoting them.

## Remaining before submission
- [ ] Listen to one MP3 per listener and confirm sound quality in Chrome
- [ ] Get the official listener profiles, answer key, and official releases from Sourcera
- [ ] Tune `CLUSTER_THRESHOLD` against the answer key
- [x] Pitch notes: `docs/pitch.md` (problem, cost, who pays, newsroom day, voice disclosure); slides still to make
