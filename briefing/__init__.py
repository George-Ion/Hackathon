"""Liquid Briefing pipeline: a day of news articles in, a verified personal audio briefing per listener out.

  ingest -> cluster -> prerank -> extract -> rank -> script -> verify -> tts -> sources

  ingest.py        read the JSONL feeds, date window, fold translations into the English original
  cluster.py       group articles about the same event (embeddings + small-model check of borderline pairs)
  prerank.py       free signals pick the stories worth a model call
  extract.py       facts and figures with source article ids, disagreements, importance (small model)
  rank.py          per-listener order; named "must hear" stories first
  script.py        the spoken script, written for the ear from the facts only (large model)
  verify.py        claim, number and advice checks; repair of flagged segments
  tts.py           ElevenLabs voice, disclosure first, timeline
  sources.py       show notes: every claim with outlet, title and link
  make.py          one listener's briefing end to end (used by run.py and server.py)
  ondemand.py      extract a new listener's missing stories live
  voice_request.py spoken "what I want to hear" -> listener profile
  must_hear.py     find a story a listener names
  llm.py, cost.py, config.py   model calls, spend tracking and budget, settings from .env
"""
