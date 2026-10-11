# Implementation evidence

2026-10-11
- Playlist frozen: 43 ordered entries (31.0 h).
- Captions captured for the 22 public lectures (25,826 lines). The 21
  odd-numbered lectures (3-43) are members-only on YouTube (VideoUnplayable);
  the evaluator has been asked how to proceed (plan D18).
- Model endpoints verified: writer gpt-5.4 (gpt-5.4-2026-03-05), judge gpt-5.2
  (gpt-5.2-2025-12-11), Azure resource linkmem-us-resource.
- Task 3 done: `src/coursebook/llm.py` gateway. It caches responses by request
  hash, has typed errors, retries with backoff, makes one repair turn for bad
  JSON, records the model version, and has a per-run cost ledger, a budget
  ceiling and bounded concurrency. Live probe: both roles answered, offline
  replay hit the cache, cost $0.0006.
- 30 offline tests pass (fake provider; no network or credentials).

Prices in config.json are estimates (Azure Global Standard, Oct 2026). Check
them against the invoice.


2026-10-11 (later): Tasks 4-9 done, slice = lectures 8 + 10
- Stage runner keyed by inputs hash; `run`, `--offline`, `--only`, `approve`,
  `render` and `status` commands.
- Extract: 213 teaching points, every 15-min chunk produced points.
- Outline: 2 concept chapters, 13 sections; every point placed or dropped with a reason.
- Write: about 6,000 words in the book's own voice; sentences tagged F or C with
  line citations.
- Verify (gpt-5.2): 93% of factual sentences supported on the first pass, 97% after
  one rewrite of 20/57 paragraphs; 9 sentences in the review queue.
- Plant test: 37/40 planted false sentences caught (missed 1 term swap, 1 reversed
  cause, 1 wrong attribution); 1/40 real sentences wrongly flagged.
- Render: output/book.pdf, 21 pages, margin source keys linking to the second of
  the video, front matter with measured rates, DRAFT reasons, sources and report
  appendices.
- Offline replay of the whole slice: 0.16 s, $0. Total model spend so far $2.67
  (including prompt iterations).
- 37 tests pass.

Known issues: subword tokens are sometimes capitalised from the captions ("EST");
judge batches are capped at 15 sentences after a 300 s timeout.

Next: review tooling for the 9 queued sentences and the outline approval;
Task 10 (CI replay without raw captions, plan D10); then the day-3 checkpoint
numbers and scaling to all 22 public lectures.
