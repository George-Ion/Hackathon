# Liquid Briefing: shared definition of done

Both implementation and critic rounds use this same pass/fail checklist. No new requirements block a round unless they fix a listed failure.

## Must pass

1. **Run:** `python run.py --since 2026-11-18 --until 2026-11-18` finishes without errors.
2. **Listener deliverables:** at least two listener profiles (target all four in `listeners/`) each produce a script, MP3, and sources file in `out/`.
3. **Traceability:** every factual script claim has one or more valid fact IDs, article IDs present in the input, and a working article permalink.
4. **Verification:** each `*.verify.json` contains no unresolved number, unsupported-claim, or investment-advice flags.
5. **Personalization:** the Dutch profile produces Dutch; the FX profile prioritizes relevant FX/macro stories; listener story selections or ordering are observably different.
6. **Length:** each spoken briefing, including its disclosure, is within 15% of its listener's target word count.
7. **Disclosure:** each MP3 timeline starts with the AI-voice disclosure before any news segment.
8. **Costs:** `cost.json` contains measured run costs plus documented estimates for the full dataset and 10x volume; cumulative API spend stays under $5.
9. **Preview:** `python server.py` loads the page, exposes the generated briefing, and the MP3 plays from its audio control.
10. **Git/data safety:** `.env` and licensed article data are not tracked. Do not edit `.env` or article data during this loop.

## Nice to have after all must-pass items

- Tune the clustering threshold against the answer key.
- Automatically revise flagged segments.
- Try `gpt-5-nano` for extraction.

## Round protocol

- Worker handles one failing item at a time and reports the exact command/output.
- Critic independently runs the relevant check, reads scripts and source notes, and returns PASS/FAIL with evidence.
- Maximum three critic/worker rounds per task. Stop when all ten must-pass items pass.
- Keep audio disabled until text checks pass. Reserve full audio generation for final verification.
- User listens to at least one MP3 per listener before submission.
