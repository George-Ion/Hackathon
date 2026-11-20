# Liquid Briefing: shared definition of done

The worker and the critic use this same pass/fail checklist. The critic checks every item itself. No new requirement blocks a round unless it fixes a listed failure.

## Must pass

1. **Run:** `python run.py --since 2026-11-18 --until 2026-11-18` finishes without errors. During iteration, use `--reuse --no-audio`. The full command is for the final check only.
2. **Listener deliverables:** all four profiles in `listeners/` (at least two) each produce `<name>.txt`, `<name>.mp3`, `<name>.sources.md` and `<name>.verify.json` in `out/`.
3. **Traceability:** every story segment has at least one fact ID. Every fact ID exists in `out/stories.json`. Every fact source is the ID of an article in that same story. Every cited article's permalink equals its `permalink` field in the input data.
4. **Verification:**
   - `verify.problems()` returns nothing for each listener: no number mismatches, no unsupported or contradicted claims, no investment advice.
   - Flags resolved by the repair loop are listed under `"revisions"` and accepted by the critic.
   - Because the verifier is an LLM, this must hold on the final run.
5. **Personalization:**
   - `dutch_investor` is in Dutch and `german_investor` is in German.
   - At least 3 of `fx_trader`'s top 5 stories are FX or macro.
   - No two listeners have the same top 3 stories in the same order.
6. **Length:** each spoken text (`out/<name>.txt`, including the disclosure) is between 0.85 and 1.15 × `length_minutes × 150` words.
7. **Disclosure:** each `<name>.timeline.json` starts with the AI-voice disclosure in the listener's language, before any news segment.
8. **Costs:**
   - `cost.json` has measured token counts and dollar figures for the run, plus estimates for the full dataset and for 10× the volume.
   - The cumulative total in `out/spend.log` stays under `API_BUDGET_USD`.
9. **Preview:** `python server.py` loads the page and shows each briefing. The MP3 plays, and clicking a timestamp jumps the audio there.
10. **Git and data safety:** `git status` shows no `.env`, `data/`, `liquid-briefing-data/`, `out/` or `resources/` files tracked or staged. The agents never edit `.env` or the article data.

## Also required before submission (not checked by the agent loop)

11. **Accuracy spot check:** the critic reads 5 random claims per listener against the source article text.
12. **Human listen:** the user listens to one MP3 per listener.
13. **Presentation:** covers the problem, who pays, and the cost for the full dataset and at 10× the volume, using the numbers from `cost.json`.

## Round protocol

- The worker handles one task at a time and reports the exact commands and their output.
- The critic runs the relevant checks independently and returns PASS, FAIL or ESCALATE, with evidence.
- At most 3 rounds per task, then ESCALATE to the user.
- Anything that needs a key, money, data or a human decision is BLOCKED: stop and ask.
- Audio stays off until the text checks pass. Full audio generation is reserved for the final verification.
- The final round moves `out/` aside, runs everything fresh, and re-checks all ten items.
