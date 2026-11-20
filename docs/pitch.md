# Pitch notes: The Liquid Briefing

Talking points for the presentation. Numbers come from `out/cost.json` and the README's final run.

## 1. Problem
- A newsroom (or a feed like Newstex) gets thousands of articles a day. Readers don't have time to read them,
  but they do have 5 minutes on the commute.
- Generic news podcasts are one-size-fits-all. A personal one is only worth it if you can **trust** every number
  in it, because a listener cannot scroll back to check.

## 2. What we built
- One pipeline from a day's raw feed to a personal audio briefing per listener: same news, different stories,
  order, depth, length and language (EN / NL / DE).
- **Every claim is traceable**: facts are extracted with their source article ids, the script may only use those
  facts, a checker compares every figure and claim against the sources and an automatic fix pass corrects what it
  flags. Each briefing comes with show notes: claim -> outlet -> link, at the second it is spoken.
- Conflicting sources are said out loud ("Invezz reports X, ActionForex reports Y"). No investment advice, by rule
  and by check.

## 3. Cost and scale (15% of the score)
- Cheap where possible: translation merging and ranking are rules (free); clustering is embeddings (~$0.001 a
  day); extraction and checking use a small model; **only the script uses the large model**.
- Pre-ranking with free signals (outlet count, sections, profile similarity) picks the stories that can reach a
  briefing; only those are extracted. Extracting every story of the full dataset cost us ~$4.95 (1,400 stories);
  with pre-ranking the extraction bill is capped by the number of listeners, not by article volume.
- Measured run (18 Nov: 124 articles, 117 stories, 4 listeners): **$4.10** in total. Shared per day: $0.26
  extraction. Per listener: ~$0.20 text (script, check, repair) and ~$0.76 voice, so **~$0.96 per listener a day**.
- Full dataset (1,502 articles after folding translations): **~$7.00**. 10x volume: **~$35**. Voice is the
  biggest cost and grows with listeners, not with articles.
- Clustering never merges articles more than 72 hours apart, so a week of recurring topics ("EUR/USD outlook")
  doesn't collapse into one story.

## 4. Who pays
- **Publishers / content distributors (main buyer).** A newsroom or aggregator like Newstex licenses it to turn
  its existing feed into a personalised audio product for subscribers: more time spent, a reason to subscribe,
  new inventory. B2B licence per brief or per subscriber.
- **Listeners** pay indirectly through the publisher's premium subscription (audio as a perk).
- **Advertisers**: a pre-roll slot in a briefing that is already targeted by interests the listener chose. Clearly
  separated from the news and never read in the news voice.

## 5. How it fits a newsroom's day
- Runs overnight on the incoming feed (05:00): a few minutes and well under a dollar of text per listener.
- An editor opens the review page at 06:00: top stories, merged duplicates, flagged claims with the before/after
  of every automatic correction. They fix or drop anything still flagged; nothing needs re-reading from scratch.
- Briefings go out at 06:30. Editors can add a profile (a new audience) in seconds, as in the live wildcard test.

## 6. Disclosure of the synthetic voice
- Every briefing opens with a spoken line: "This briefing is read by an AI-generated voice and was assembled
  automatically from news sources" (in the listener's language).
- Show notes repeat it and list every source. Outlets are named in the audio ("according to Invezz").
- No cloned journalist voices without their consent; a stock voice by default.

## 7. Licence
- Article text is never read out or published; only facts, short attributed quotes, titles and links.
