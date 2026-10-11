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

Next: Task 4 (stage runner, `status`, `--only`), then Task 5 (segment +
extract) on lectures 8 and 10.
