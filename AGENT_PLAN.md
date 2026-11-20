# Liquid Briefing: final plan for the worker and critic agents

Deadline: **Sat 21 Nov, 10:30 (GMT+1)**. Feature freeze: **06:00**. After that, only bug fixes and the presentation.

## 0. Where the project stands (checked 20 Nov, evening)

The last run (18 Nov, 124 articles, 4 listeners) already meets most of the definition of done:

| Listener | Language | Words / target | Ratio | Verify flags | Disclosure first |
|---|---|---|---|---|---|
| dutch_investor | nl | 526 / 600 | 0.88 | 0 | yes |
| fx_trader | en | 666 / 750 | 0.89 | 0 | yes |
| german_investor | de | 792 / 900 | 0.88 | 0 | yes |
| world_listener | en | 408 / 450 | 0.91 | 0 | yes |

All four MP3s exist, `.env` and the licensed data are gitignored, and the test page starts.

**This is not a rebuild.** The work below fixes real bugs that hurt trust in the German and Dutch briefings, makes runs robust, and makes the cost numbers truthful. Do not rewrite working modules.

Known risks found in the code review:

1. **One fact cites an article that isn't in its story.** `extract.py` never checks the model's source IDs, and `verify.py` only checks that sources are non-empty.
2. **Number checks are wrong for German and Dutch.** `verify._numbers` reads `1,08` as `108` and `1,5 miljard` as 15 billion. Fact IDs like `s12.f3` and dates also leak into the source numbers, which hides real errors.
3. **The advice check is English-only.** The `ADVICE` regex in `verify.py:24` has no German or Dutch phrases.
4. **Nothing repairs flagged segments.** Flags block audio, but nothing fixes them.
5. **Length only has an upper limit.** `script.py` enforces only the maximum, and all four briefings sit at 0.88–0.91, just above the 0.85 floor.
6. **`out/cost.json` doesn't look measured.** Token counts are all `0` and the dollar figures match the README exactly. It needs a fresh measured run.
7. **The budget check blocks the final audio run.** `tts.py:50` checks `COST.total()`, which includes costs restored from earlier runs ($4.11 of $5 already). Any `--reuse` audio run will stop.
8. **One failed story aborts extraction.** `run.py:24` uses `pool.map`, so a single error kills the whole run after paying for the rest.
9. **API calls have no timeout or retry, and JSON parsing is unguarded** (`llm.py`).
10. **The cost tracker isn't thread-safe.** It is shared by 8–12 threads without a lock (`cost.py`).
11. **The MP3 route has no HTTP Range support** (`server.py:136`). Clicking a timestamp to jump in the audio may not work in Chrome.
12. **There are no tests.**

## 1. Before the agents start (human, about 10 min)

- [ ] **H1. Commit a baseline.** Commit the current working state so every agent change can be undone:
      `git add -A` then `git commit -m "Baseline before agent loop"`. Do not push yet.
- [ ] **H2. Decide the budget.** About $4.11 is already spent. Rough costs are:
      - a text-only iteration with `--reuse`: about $0.60,
      - a fresh extraction of one day: about $0.85,
      - audio for all four listeners: about $2.80.
      **Recommended:** set `API_BUDGET_USD=12` in `.env` for the remaining work. The agents may not edit `.env`.
- [ ] **H3. Check the ElevenLabs key.** Make sure it still has Text to Speech permission (audio was generated at 20:58, so it should).
- [ ] **H4. Answer key.** If Sourcera has shared the official listener profiles or answer key, put them in `resources/`, which is gitignored. Otherwise task P2-3 is skipped.

## 2. Agent roles

### Worker agent (copy-paste prompt)

> You are the worker on the Liquid Briefing repo (Python, `briefing/` package, `run.py`, `server.py`).
> Read `AGENT_PLAN.md` and `DONE.md` first. Work on exactly ONE task at a time, in the order given, unless the critic
> sends you a FAIL to fix.
>
> Rules:
> - Make the smallest change that completes the task. Do not refactor or restyle code outside the task.
> - Never edit `.env`, anything in `data/`, `liquid-briefing-data/`, or `listeners/*.json` (unless the task says so).
> - Never push to GitHub. Commit locally after each task the critic marks PASS: `git commit -m "<task id>: <what>"`.
> - Never weaken a check, test, threshold or prompt rule to make something pass.
> - Run cheap first: unit tests (`python -m unittest discover -s tests`), then `python run.py --reuse --no-audio`.
>   Only run a fresh extraction or audio when the task says so.
> - After every paid run, append the run's cost to `out/spend.log` (task P0-6 automates this) and stop if the
>   total would pass `API_BUDGET_USD`.
> - If you are stuck after two attempts, or a task needs a key, money, data or a human decision, write BLOCKED
>   with the reason and stop.
>
> Report format, every time:
> 1. Task id and one-line summary
> 2. Files changed (with line ranges)
> 3. Commands run, with the actual output (trimmed to what matters)
> 4. API spend for this task and the running total
> 5. Anything left open

### Critic agent (copy-paste prompt)

> You are the critic on the Liquid Briefing repo. You do not write or edit code. You check the worker's work against
> the task's acceptance check in `AGENT_PLAN.md` and the ten items in `DONE.md`.
>
> Rules:
> - Run the checks yourself. Never accept "it should work" or the worker's pasted output alone.
> - Read the actual files: the diff (`git diff`), `out/*.txt`, `out/*.sources.md`, `out/*.verify.json`.
> - Give PASS or FAIL for the task, with evidence (file:line, command output, or a quote from the briefing).
> - A FAIL must say exactly what is wrong and what result would make it pass.
> - Check for gaming: claims or facts silently deleted instead of fixed, loosened regexes or thresholds,
>   tests changed to match wrong behavior, prompt rules removed.
> - Rank problems by judging weight: trust and accuracy 25%, listener fit 20%, making sense of the news 20%,
>   cost 15%, listening experience 10%, path to product 10%.
> - Do not add new requirements. Put new ideas under "Later" in your report; they never block a PASS.
> - After 3 FAILs on the same task, stop and write ESCALATE with a summary for the human.
>
> Report format:
> 1. Task id: PASS / FAIL / ESCALATE
> 2. Evidence
> 3. If FAIL: the exact fix needed
> 4. Later (optional ideas, non-blocking)

### Human (you)

- Answer BLOCKED and ESCALATE reports.
- Listen to one MP3 per listener before submitting.
- Own the presentation (task P3-2) and the final push.

## 3. Tasks, in order

Each task lists the files, the change, and the acceptance check the critic runs. Do the P0 tasks first. P1 starts only when all P0 tasks pass.

### P0: trust and correctness (must do)

**P0-1. Add unit tests for the pure functions (no API calls)**
- Files: new `tests/__init__.py`, `tests/test_verify.py`, `tests/test_script.py`, `tests/test_rank.py`, `tests/test_extract.py`, `tests/test_cost.py`.
- Use the standard-library `unittest` (no new dependencies). Cover:
  - `verify._numbers` in English, German and Dutch (`1.08`, `1,08`, `1.234,5`, `1,5 Milliarden`, `2,3 miljard`, `5%`),
  - `verify.ADVICE` positive and negative cases in EN/DE/NL,
  - `script.validate_script` rejects unknown story and fact IDs,
  - `rank.rank_for_listener` respects `avoid` and `max_stories`,
  - `cost.CostTracker.projections`.
- Write the tests for the German and Dutch number cases so they **currently fail**. P0-2 makes them pass.
- Acceptance: `python -m unittest discover -s tests` runs. All tests pass except the DE/NL number and advice tests, and the critic confirms those fail for the right reason.

**P0-2. Make the number check language-aware and stop it leaking IDs**
- File: `briefing/verify.py`.
- Change `_numbers(text)` to `_numbers(text, language="en")`. For `de`/`nl`, read `.` as the thousands separator and `,` as the decimal separator. For `en`, the reverse. Return floats rounded to 6 significant figures, not strings, so `1.5 billion` and `1,5 miljard` compare as equal.
- Build source numbers only from each selected fact's `text` and the conflict claims, not from `json.dumps` of the whole fact objects, which includes IDs like `s12.f3` and source article IDs. Facts are written in English, so parse source numbers as `en` and segment numbers in the listener's language.
- Pass the language into `verify(script, stories, language)` from `make.py:16` (`lang`).
- Ignore four-digit years from 1900 to 2100 on both sides only if they also appear in the fact text or the article `published` dates. Otherwise keep flagging them.
- Acceptance: all P0-1 number tests pass. Running `python run.py --reuse --no-audio` still gives 0 flags on all four listeners. If new flags appear, the critic reads each one and confirms it is a real mismatch, not a parser error.

**P0-3. Add German and Dutch to the advice regex**
- File: `briefing/verify.py:24`.
- Add phrases such as `kaufen sie`, `jetzt kaufen`, `verkaufen sie`, `wir empfehlen`, `sie sollten (kaufen|verkaufen|investieren)`, `koop nu`, `verkoop nu`, `wij raden aan`, `je moet (kopen|verkopen|beleggen)`, `goed moment om (te )?(kopen|beleggen)`.
- Acceptance: the advice tests pass in all three languages, and the negative cases pass too: "Anleger kauften Gold" is reporting, not advice, and must not match.

**P0-4. Validate the source IDs the model returns during extraction**
- File: `briefing/extract.py`, after line 43.
- For each fact, keep only `sources` that are IDs of articles in this story. Map a translation ID to its English original's ID. Drop facts left with no valid source. Do the same for `conflicts[].positions[].sources`. Record counts in `out["dropped_sources"]` and `out["dropped_facts"]`.
- Add a repair helper `extract.clean_story(story)` that applies the same rule to an already-extracted story. Run it on `out/stories.json` once, with no API call, so `--reuse` runs get clean data. Fact IDs must stay stable: don't renumber.
- Acceptance: the test in `tests/test_extract.py` passes. A one-off check confirms that every fact source in `out/stories.json` is an article in its own story; the review found 1 bad source, and it should be 0 after the change. The critic confirms no story lost more than one fact because of this.

**P0-5. Enforce length from both sides**
- Files: `briefing/script.py`, `briefing/make.py`.
- Define one helper, `script.length_bounds(profile)`, that returns `(low, high)` = `(0.85 × target, 1.15 × target)` for the **whole spoken text including the disclosure**. Here `target = length_minutes × 150`. Use it everywhere: in `write_script`, in `make.validate_saved_briefing` (lines 81–84), and in `make_briefing`.
- In `write_script`, aim the model at `0.95 × target − disclosure_words`. Count the disclosure from `tts.DISCLOSURES[language]` instead of the fixed 25. If the draft is under `low`, ask for an expansion that uses unused provided facts, with the same fact-ID rules. If it's over `high`, ask for a cut. Allow at most 2 revisions, then fail as it does now.
- In `make_briefing(..., audio=True)`, the path the test page uses, run the same length check before TTS. Today only the CLI path checks length.
- Acceptance: after `python run.py --reuse --no-audio`, every listener's ratio is between 0.90 and 1.10 (the critic recomputes it from `out/<name>.txt`), and there are still 0 flags.

**P0-6. Make spend tracking truthful and the budget workable**
- Files: `briefing/cost.py`, `briefing/llm.py`, `briefing/tts.py`, `run.py`, `server.py`.
- Separate two numbers: `COST.session_usd()`, spent by this process, and the restored "measured" report. The budget check in `tts.py:50` uses the **cumulative ledger** (below), not `COST.total()`.
- Add an append-only ledger, `out/spend.log`, with one JSON line per paid call batch: `{"time", "step", "model", "usd"}`. Add a helper `cost.spent_to_date()` that sums it.
- Check the budget before **every** paid call: chat, embedding and TTS. If `spent_to_date() + estimate > API_BUDGET_USD`, raise a clear `BudgetExceeded` error.
- Add a `threading.Lock` around every change to `by_step`, and make ledger writes thread-safe.
- Acceptance: unit test for the lock and the ledger sum. After one `--reuse --no-audio` run, `out/spend.log` has lines whose sum matches the session cost printed by `run.py`. Token counts in `cost.json` are non-zero for every LLM step of that run.

**P0-7. Repair loop for flagged segments**
- Files: `briefing/make.py`, plus a small new function in `briefing/script.py`.
- After `verify`, if `verify.problems(report)` returns segments, call `script.revise_segments(profile, picked, sc, bad)`. It rewrites **only** the flagged segments with the large model, gives the model the segment's allowed facts and the verifier's reason, keeps the same story and fact-ID rules, and runs `validate_script`. Then re-verify only the changed segments. Allow at most 2 rounds.
- The rewrite may drop a claim but must not add new facts. Every segment must keep at least one fact ID.
- Save the original flags and how each was resolved in `out/<name>.verify.json` under `"revisions"`, so the critic can audit it.
- Acceptance: test with mocked `chat_json` (no API calls) showing that a flagged segment is replaced and re-checked. On a real `--reuse --no-audio` run, 0 unresolved flags, and the critic reads every revised segment against its facts.

### P1: robustness (should do)

**P1-1. Retries, timeouts and safe JSON in `llm.py`**
- Create the client with `OpenAI(timeout=90, max_retries=3)`.
- In `chat_json`, if `json.loads` fails, retry once, then raise a `ValueError` that names the step.
- Acceptance: test with a mocked client that returns invalid JSON once, then valid JSON.

**P1-2. One failed story must not abort extraction**
- File: `run.py:23–24`.
- Wrap `extract.extract_story` so each story is tried twice. On final failure, log `story_id` and the error to `out/extract_errors.json` and continue. Print the count at the end.
- Acceptance: test, or a manual run with `--limit 20`, where one story is forced to raise. The run completes and `stories.json` has 19 stories plus an error file.

**P1-3. Defensive ingest and cluster**
- `briefing/ingest.py`:
  - `merge_translations` only matches when `author` is non-empty,
  - a row with an unparseable `date` is skipped and counted instead of crashing,
  - `run.py` prints the count.
- `briefing/cluster.py:12`: use `(a['text'] or a['excerpt'] or '')[:1500]`.
- Acceptance: unit tests with a fake record with no author, one with no text, and one with a bad date.

**P1-4. Audio seeking on the test page**
- File: `server.py:136–144`.
- Support `Range: bytes=start-end` for MP3s: send `Accept-Ranges: bytes`, a `206 Partial Content` response and `Content-Range`. Keep the flat-folder protection against path traversal.
- Acceptance: `curl -s -D - -o NUL -H "Range: bytes=0-99" http://localhost:8000/out/fx_trader.mp3` shows `206` and `Content-Range`. In the browser, clicking a timestamp in the transcript jumps the audio there; the critic checks this with the browser tool.

**P1-5. Fresh, measured run (paid, about $0.85 plus text costs)**
- Only after P0 and P1-1 to P1-3 pass, and only if the budget allows:
  `python run.py --since 2026-11-18 --until 2026-11-18 --no-audio`.
- Acceptance: run every `DONE.md` text check again: 1, 3, 4, 5, 6, 8 and 10. `cost.json` has real token counts and its projections section is filled in.

### P2: score improvements (only if P0 and P1 pass before about 03:00)

**P2-1. Story variety and freshness in ranking**
- File: `briefing/rank.py`.
- After scoring, choose stories greedily. Lower a story's score by 3 if it shares its first topic with a story already picked, so a briefing isn't five Fed stories. Add a small recency bonus: +1 if published in the last 12 hours of the window.
- Acceptance: unit test. On a `--reuse --no-audio` run:
  - at least 3 of the FX trader's top 5 stories are tagged FX or macro (`forex`, `fed`, `ecb`, `boj`, `interest rates`, `inflation`, `usd`, `eur/usd`),
  - the Dutch and German briefings are in their own language,
  - no two listeners have the same top 3 stories in the same order.

**P2-2. World listener gets its full story count**
- It currently gets 3 stories while `max_stories` is 4. Check why: the `avoid` list or too few matches. Fix it in `rank.py`, not in the profile. Fallback: fill the remaining slots with the highest global non-market stories.
- Acceptance: `world_listener` has 4 stories, none about trading or markets. The critic reads the script.

**P2-3. Tune `CLUSTER_THRESHOLD` (only if the answer key exists in `resources/`)**
- Write `scripts/tune_cluster.py`. It embeds once, caching to `out/embeddings.npy`, then scores thresholds from 0.70 to 0.86 against the answer key's groupings (pairwise F1) and prints a table. Change the default in `config.py` only if F1 improves.
- Acceptance: the table is pasted, and the change is justified by the numbers.

**P2-4. Clean up**
- Delete the stray `out/ui-inline.js`.
- Update the README: setup, the `DONE.md` checks, the new flags, "First results" with the measured numbers from P1-5, and the tick boxes in Open TODOs.
- Acceptance: the critic follows the README setup from a fresh shell and it works.

### P3: final verification and submission

**P3-1. Final full run (paid: text plus audio, about $3.50)**
- Only after the human approves the spend.
  1. Move `out/` to `out_backup/`.
  2. Run `python run.py --since 2026-11-18 --until 2026-11-18`.
  3. Run `python server.py`.
- The critic re-checks **all ten** `DONE.md` items from scratch and samples 5 random claims per listener against the source article text in `data/raw/`.
- The human listens to one MP3 per listener.

**P3-2. Presentation (human, the worker can draft)**
- The worker drafts `docs/pitch.md` from the real `cost.json` numbers, covering:
  - the problem,
  - who pays (B2B: publishers and brokers embedding a personal audio briefing; B2C as a subscription add-on),
  - how it fits a newsroom's day,
  - how the AI voice is disclosed,
  - measured cost for one day, estimated cost for the full dataset and for 10× the volume, and the cost per listener per day,
  - what makes it trustworthy (fact IDs, verification, source notes).
- The human turns it into slides.

**P3-3. Ship**
- Run `git status` and confirm no `.env`, `data/`, `liquid-briefing-data/`, `out/` or `resources/` files are staged.
- Commit, then push once, done by the human.

## 4. Loop rules

- One task at a time. Worker report, then critic verdict, then either the next task or a fix.
- At most 3 rounds per task, then ESCALATE to the human.
- Default runs: unit tests first, then `--reuse --no-audio`. Fresh extraction and audio only in P1-5 and P3-1.
- Stop when every P0 and P1 task passes and the P3-1 final check passes all ten `DONE.md` items. P2 is optional.
- At 06:00, freeze features: finish or revert the task in progress, then go to P3.

## 5. Quick reference

```powershell
.venv\Scripts\Activate.ps1
python -m unittest discover -s tests
python run.py --reuse --no-audio
python run.py --since 2026-11-18 --until 2026-11-18 --no-audio
python run.py --audio-only
python server.py
```

- Unit tests: no API calls.
- `run.py --reuse --no-audio`: text iteration, about $0.60.
- `run.py --since … --until … --no-audio`: fresh extraction, about $0.85 plus text.
- `run.py --audio-only`: audio from the saved, verified scripts, about $2.80.
- `server.py`: test page on http://localhost:8000.

Key files:
- `briefing/extract.py`: facts with source IDs (P0-4)
- `briefing/verify.py`: trust checks (P0-2, P0-3)
- `briefing/script.py`: length and repair (P0-5, P0-7)
- `briefing/make.py`: one listener's pipeline
- `briefing/cost.py`, `briefing/llm.py`, `briefing/tts.py`: spend and budget (P0-6, P1-1)
- `briefing/rank.py`: personalization (P2-1, P2-2)
- `server.py`: test page and audio seeking (P1-4)
