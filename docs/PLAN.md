# Coursebook working plan (CEO review, scope expansion)

Source design: `docs/designs/proof-carrying-coursebook.md` (APPROVED 2026-10-11).
Review: /plan-ceo-review, mode SCOPE EXPANSION, depth implementation-ready.
This file is a plan. No code has changed.

## Decision ledger

| ID / owner | Contract and evidence | Current | Proposed | Status | Exact approval and scope |
|---|---|---|---|---|---|
| D1 deadline / user | AUQ D1 | 2+ weeks | – | approved | "2+ weeks" |
| D2 mode / user | AUQ D2 (recommended reduction) | SCOPE EXPANSION | – | approved | "Scope expansion" |
| D3 office-hours / user | AUQ D3 | ran | – | approved | "Run /office-hours" |
| P1-P5 premises / user | design doc §Premises | agreed | – | approved | P4-P5 answer; P1-P3 re-ask answer |
| D5 P2 revision / user | Codex challenge | flagged-only review + blinded audit | – | approved | "Revise: flagged-only + audit" |
| REF reference policy / user | lecture 1 captions cite Raschka; repo Apache-2.0 | lectures teach, repo verifies | – | approved | "Lectures teach, repo verifies" |
| D6 approach / user | office-hours Phase 4 | B proof-carrying engine, slice-first | – | approved | "B: proof-carrying engine" |
| DOC design doc / user | spec review 6→8/10, 13 concerns recorded | APPROVED | – | approved | "Approve" |
| D7.1 heatmap / S10 | 0G | in scope | – | approved | "Add" |
| D7.2 glossary+index / S10 | 0G | in scope | – | approved | "Add" |
| D7.3 `coursebook why` / S8 | 0G | in scope | – | approved | "Add" |
| D7.4 exercises / S6 | 0G (recommended defer) | in scope | – | approved | "Add" |
| D8 second-playlist gate / S9 | R2-9 | full release gate | – | approved | "Full release gate" (recommended was replay+outline): outline approval, review queue, audit (sample = min(100, all auto-passed claims)); +3-4 h human time |
| D9 disagreement materiality / S4 | R2-10 | facts/behaviour only | – | approved | "Facts/behaviour only": judge labels a claim against both sources; only supported-vs-contradicted is queued; listings labelled 'adapted from rasbt/LLMs-from-scratch (Apache-2.0)'; ~10-30 items |
| D10 data mode + quotes + audio / S3 | R2-3, R2-12, OQ3-4 | private mode, quotes ≤25 words, opt-in media | – | approved | "Private + short quotes": raw captions in a local data package; CI replays hashes + cached outputs; `--allow-media-download` local only |
| D11 judge model / S1 | OQ1 | Azure writer + a different Azure deployment as judge | – | approved | "Same provider, other model" (recommended was a different family): the plant catch rate is reported as the check on self-agreement |
| D12 LLM call contract / S2 | model.py:33-36 | typed gateway | – | approved | "Typed gateway": the rescue table in Section 2 as written, plus a fixture test for each class |
| D13 capture error contract / S2 | core.py:108 | named reason codes | – | approved | "Named reasons": the listed exceptions, RequestBlocked backoff 60s x3, a test for each code |
| D14 build order / Outside voice | Codex #1/#7, spec #11/#12 | book-first gate | – | approved | "Book-first gate": slice core only; day-3 metrics; full PDF read by day 8 before any extras; triggers on days 10/12 |
| D15 PDF engine / S9 | spec #8 | Quarto + LaTeX (TinyTeX) | – | approved | "LaTeX / TinyTeX"; margin-key spike in days 1-3 |
| D16 small ops / S8 | spec #10 | `status`, planted-injection test, cache secret scan, concurrency, `--only`, cost meter | – | approved | "Approve all six", each with a test |
| D17 miss audit / Outside voice | Codex #6 | 20 random 2-min clips per book, blind miss check | – | approved | "Add to audit": miss rate reported; an untaught importance-3 point blocks release |

## Accepted scope

Approach B from the design doc (stages 1-9, contracts, cut line, checkpoints),
plus the four accepted extras:
- **Coverage heatmap appendix** (lecture minutes × chapters, plus dropped points
  with reasons). Built from stage 4 data.
- **Glossary + index** from `definition` points, cited and checked like any other prose.
- **`coursebook why <paragraph-id>`**: a read-only command that prints the trail
  for one paragraph (caption lines → points → outline approval → judge verdicts →
  review record → cache keys).
- Glossary definitions and exercise answers receive plants (2 per chapter) and
  are included in the audit sample.
- **"Check yourself" exercises** for each chapter, generated from points; answers
  are cited and go through stage 6. Cut-line position: dropped second, right after the
  figures stage (given its added checking load).

Consistency fixes from spec review round 2 (these follow from approved
contracts and need no new decision):
- R2-1/R2-2: windows use `VIDEO@S-E` (start and end in seconds). Within each
  window, every caption line keeps its `VIDEO@S` ID, one line per caption, as
  `[S] text`. Write and verify prompts receive these line-tagged windows, and the
  judge receives the cited lines plus their windows.
- R2-4: the writer tags each sentence `F` (factual), `T` (technical) or `C`
  (connective). `validate_chapter` checks only that tags and citations agree; the
  judge checks that `C` sentences make no claim.
- R2-5: the slice uses the full protocol of 20 plants (4 × 5 types).
- R2-6: the success criterion becomes "every `exec` listing runs in CI, every
  `display` listing is labelled; counts appear in the report".
- R2-7: success criteria split into **Minimum** (matching the cut line) and **Stretch**.
- R2-8: build-order wording becomes "no code changes (config plus its own data)".
- R2-11 (corrected after spec review #5): the 0.7 cutoff is provisional. It is
  calibrated on the plants the judge wrongly passed plus audit errors, re-fitted
  at the day-8 gate across all chapters, and reported with its sample size.
- R2-13: coaching line fixed in the design doc.

## 0I Temporal interrogation (CC session hours within days 1-3; the design doc's 14-day table is the calendar)

```
HOUR 1 (foundations)  first commit; install Quarto; probe the Azure endpoint with one tiny call;
                      start full caption capture in the background         [human ~1 day]
HOUR 2-3 (core)       segment + cache + stage runner; extract/outline/write/verify on L7-8
                      ambiguity: how sentence tags and citations look inside Markdown
                      -> decided: sidecar JSON per section, Markdown generated from it
HOUR 4-5 (integration) Quarto render with popovers and margin key; planted-claim run;
                      `why` command; surprise: Quarto + Typst/LaTeX setup on CI, freeze  [human ~1 wk]
HOUR 6+ (polish)      calibration, heatmap, glossary, exercises, second playlist, audit
                      they will wish for: cost meter per stage, `--only chapter` reruns
```
Feasibility blockers before scaling: both Azure deployments (writer and judge,
D11) must answer a probe call. Data mode is settled (D10: private).

## Section 1 - Architecture

```
                         config/<playlist>.json
                                   |
  +----------------- coursebook (stage runner, DAG) ------------------+
  | capture -> segment -> extract -> outline* -> write -> verify** ->  |
  |    |                                  |          |       |          |
  |    v                                  v          v       v          |
  | raw/ (content-addressed)        approvals/   chapters/ verdicts/    |
  |                                                                     |
  | [code] <- reference pack (pinned commit)   [figures] <- frames(local)|
  |                         \                     /                     |
  |                          render (Quarto: HTML + PDF + report)        |
  +---------------------------------------------------------------------+
        |                        |                         |
   llm.call() --> cache/<sha>.json (replay) --> provider (Azure / other)
   * human outline approval     ** human review queue + audit
```
- **Boundaries:** each stage is a pure function from hashed inputs to a hashed
  output. The runner keys each run by `stage_id + inputs_hash` (input hashes
  include the prompt template and config section) and skips a stage when a
  completed record for that key exists. Optional stages: `code`, `figures`,
  `html`, `glossary`, `exercises`, `heatmap`, each with an `enabled` flag in
  config. `capture.fallback` is `none` or `whisper` (whisper needs
  `--allow-media-download`). This replaces today's single `build()`
  (build.py:7, about 80 lines, more than 5 branches).
- **One LLM gateway** (`llm.call`) owns caching, cost metering, retries and
  model-version recording. Today `model.py` writes its own HTTP call; that becomes
  the gateway.
- **Single points of failure:** the model endpoint (mitigated by the replay
  cache), YouTube capture (mitigated by snapshots), and the Quarto toolchain
  (mitigated by pinning the version in CI).
- **10x / 100x:** a 300-hour playlist means about 10x the calls and hits the
  `budget_usd` ceiling first; outlining stays within context because it works per
  lecture group. Nothing else breaks.
- **Rollback:** git tags per release; the data cache only ever grows.
- **Expansion:** the stage DAG plus content-addressed cache is the platform.
  Adding EPUB output or a new kind of source (slides, PDFs) is one new stage.
- Judge model (D11, approved): a second Azure deployment.

## Section 2 - Error & Rescue Map

```
CODEPATH            | WHAT CAN GO WRONG                     | CLASS
--------------------|---------------------------------------|---------------------
capture.playlist    | playlist private / removed            | PlaylistUnavailable
                    | entry deleted / private video         | (manifest: access=unavailable)
capture.captions    | no captions in language               | NoTranscriptFound
                    | YouTube IP block / 429                | RequestBlocked / IpBlocked
                    | network timeout                       | httpx/yt-dlp timeout
llm.call            | 429 / 5xx / timeout                   | ProviderTransient
                    | 401/403/404 (bad key, deployment)     | ProviderConfig
                    | content filter (Azure)                | ProviderRefusal
                    | finish_reason=length (truncated)      | TruncatedOutput
                    | empty content / not JSON              | MalformedOutput
                    | JSON valid, schema wrong              | SchemaViolation
                    | citation IDs not in input             | InvalidCitation
                    | budget exceeded                       | BudgetExceeded
verify.judge        | judge disagrees with itself on rerun  | (cached; calibration)
render.quarto       | quarto missing / version mismatch     | ToolchainError
code.exec           | listing fails / exceeds time limit    | ListingFailed
replay              | snapshot or cache hash mismatch       | IntegrityError

CLASS             | RESCUED? | ACTION                                 | USER SEES
------------------|----------|----------------------------------------|---------------------------
PlaylistUnavailable| N       | stop                                   | "playlist unavailable" exit 2
NoTranscriptFound | Y        | Whisper fallback if enabled, else blocked | listed in capture report
RequestBlocked    | Y        | backoff 60s x3, then mark blocked       | capture report + exit 2
ProviderTransient | Y        | backoff 2,4,8,16s, max 4                | progress line; then fail with stage+input id
ProviderConfig    | N        | stop immediately                       | which setting is wrong
ProviderRefusal   | Y        | record; extract/outline: retry once with the chunk split; write: queue the section with its points and lines so the reviewer writes or excuses it; judge: count the claim as unverified (queued) | listed in report
TruncatedOutput   | Y        | extract: split the chunk at a window boundary; outline merge: merge in two halves; write: split the section's points into two calls; judge: one claim per call | transparent; logged
MalformedOutput   | Y        | one repair retry with the error message | then fail with saved run file
SchemaViolation   | Y        | same as Malformed                      | same
InvalidCitation   | Y        | one repair retry; then paragraph flagged | review queue
BudgetExceeded    | N        | stop before the call                   | spent/limit per stage
ListingFailed     | N        | CI fails                               | listing id + stderr
IntegrityError    | N        | stop                                   | which file, expected vs actual hash
```
- **GAP (CRITICAL):** `model.py:33-36` raises on any non-200 without retrying,
  doesn't distinguish config errors from transient ones, and doesn't handle
  truncation or refusals. A `KeyError` on `choices` would also escape. → **D12 approved: typed gateway.**
- **GAP (WARNING):** `core.py:108` uses `except Exception` and records only the
  type name. A blocked IP and a missing transcript look the same. → **D13 approved: named reason codes.**
- Every failure writes a structured run record (stage, input id, class, attempt);
  secrets and full upstream URLs are never logged (keeps today's rule from core.py:109).

## Section 3 - Security & threat model

| Threat | Likelihood | Impact | Mitigated? |
|---|---|---|---|
| Prompt injection through captions ("ignore previous instructions") | Low | Med | Yes: the prompts treat evidence as data (writer.txt:2); the judge never sees writer instructions; plus a planted-injection test |
| API key leaked in committed cache/run files | Med | High | Yes: requests are saved without headers (model.py:39); add a pre-commit `gstack-redact`/regex check over `data/**/cache` |
| Running third-party code (reference pack) in CI | Low | Med | Pinned commit and hash, no network, CPU-only, no secrets in that job |
| Republishing captions / video frames without rights | Med | Med | Yes (D10): private mode, quotes ≤25 words, media download opt-in and local |
| Path traversal through video IDs | Low | Med | Yes: regex at core.py:44 and model.py:12 |
| Supply chain (Quarto, torch, yt-dlp) | Low | Med | Pinned in uv.lock; Quarto version pinned in CI |

## Section 4 - Data flow & edge cases

```
URL -> manifest -> captions -> lines -> windows -> points -> outline -> sections -> verdicts -> render
 |nil/private  |deleted entry |no captions|empty    |0 points |point dropped  |0 citations |judge refusal
 |reordered    |duplicate id  |auto vs manual|overlapping times |>context|unapproved|invalid ids |cache miss in replay
```
- **Playlist changed** (videos reordered, added or removed): re-freezing makes a
  new manifest hash. Dependent stages are invalidated; approvals become stale, so
  the build is marked DRAFT. Tested.
- **Duplicate video in the playlist:** captured once, with both positions kept
  in the manifest.
- **Overlapping auto-caption times** (seen in Xpr8D6LeAtw: line 1 ends at 10.28,
  line 2 starts at 7.84): allowed. Only the start times must be in order (as now).
- **Lecture with 0 extracted points:** flagged in the heatmap as "no content
  placed", not silently skipped.
- **Interactive:** `coursebook why` with an unknown or stale ID gives a clear
  error naming the latest build hash.
- Disagreement materiality (D9, approved): facts/behaviour only.

## Section 5 - Code quality

- `model.py:29,36` uses `__import__("json")`; replace it with a normal import
  when the gateway is written.
- `build.py:7` is an ~80-line function mixing integrity checks, review gating
  and rendering. It splits into `replay.verify_integrity`, `gate.release_issues`
  and `render.quarto`.
- `build.py:25` calls `evidence_from_segments` again on every build; keep it
  (it is the integrity check) but move it into `verify_integrity`.
- Keep the module layout simple: `core` (hashing, IO), `stages/*.py` (one file
  per stage), `llm.py`, `render.py`, `cli.py`. No plugin framework (that would
  be over-engineering).

## Section 6 - Tests

| New thing | Type | Happy | Failure | Edge |
|---|---|---|---|---|
| segment | unit | lines → windows with IDs | non-monotonic start → error | 94-min lecture IDs > 3600 s |
| llm.call cache | unit | hit returns stored response, no network | hash mismatch → IntegrityError | model version change → miss |
| llm.call errors | unit (fake provider) | 200 OK | 429 then 200 → retry; 401 → stop; length → split | empty / non-JSON / refusal |
| extract/outline/write | integration (fake LLM fixtures) | fixture lecture → section JSON | invalid citation → repair → flag | 0 points |
| validate tags | unit | F with cite passes | F without cite fails; C with claim → judge flags | T with ref only |
| verify + plants | integration | plants caught | plants never reach release (string scan) | all plants caught / none |
| approvals | unit | fresh approval → release ok | stale hash → DRAFT, release fails | missing approval |
| why | unit | complete trail | unknown id → clear error | paragraph edited after review |
| heatmap/glossary/exercises | integration | rendered from fixtures | definition fails judge → dropped from glossary | lecture with no points |
| replay | system (CI) | fresh clone → `make book` offline → hashes equal | tampered caption → IntegrityError | private mode skip list |
| second playlist | system (CI) | builds, no code change | – | stage disabled → "skipped" |
| code listings | CI job | exec listings pass, assertions hold | broken listing fails CI | display listings labelled |

Prompt changes are evaluated on the slice: planted-claim catch rate by type, and
the support rate before and after, compared against the previous cached run.
Flakiness: every LLM-backed test uses recorded fixtures; live calls happen only in
`make fresh`.

## Section 7 - Performance

- About 1,200 model calls per full run. Bounded concurrency (default 4,
  configurable) with backoff. Expected wall time for a full fresh run is about
  1-2 h; replay takes under 2 min.
- Memory: the largest single input is one 15-min chunk (~3k tokens) or one
  lecture-group outline. No full-book prompt.
- The cache is the main optimisation: only changed inputs are re-run.

## Section 8 - Observability

- Each stage appends to `data/<playlist>/runs/<run-id>.jsonl`: stage, input id,
  cache hit/miss, tokens, cost, duration, outcome class.
- `coursebook status` prints for each stage: done/total, cost so far against
  `budget_usd`, review queue size, stale approvals. `coursebook why` (accepted)
  covers per-paragraph debugging.
- The evaluation report is the dashboard: support rate, plant catch rate by
  type, audit error rate, coverage heatmap, exec/display counts, model versions,
  total cost.

## Section 9 - Deployment & rollout

- CI jobs: `test` (unit/integration, fixtures), `replay` (both playlists
  offline), `code` (exec listings), `release` (gate; tag-triggered).
- Rollout: the slice is tagged `v0.1-slice` before scaling out; each checkpoint
  gets a tag. Rollback = the previous tag (data cache is append-only).
- Quarto version pinned in CI; output checked by comparing the Markdown/HTML
  hashes and the extracted PDF text.
- Second playlist (D8, approved): full release gate. Pick a short playlist (3-5 videos, captions, a non-ML field) so its review queue and audit stay around 3-4 h.

## Section 10 - Long-term trajectory

- Reversibility 4/5: a stage DAG with a cache keyed by content hash is easy to extend.
- Debt we're taking on: Quarto as a toolchain dependency; two replay modes.
- Phase 2 (after submission): EPUB, more source types (slide PDFs, lecture
  notes), a public "course → book" CLI. The architecture supports all of these
  without a rewrite.
- Main knowledge risk: prompt templates. They are versioned and hashed into the
  cache key, and each has a header comment saying what the stage guarantees.

## Section 11 - Design & UX

SKIPPED (no app UI). The HTML book's reading experience is handled by Quarto
defaults plus the citation hover. Recommend `/design-review` on the rendered HTML
edition after the slice.

## NOT in scope
- General web-search stage (P5 / R1-11).
- Agent-style writer (Approach C, not chosen).
- Per-chapter human sign-off of every paragraph (replaced by D5).

## Outside voice (Codex, plan challenge) and spec review of this plan

- Codex: 8 findings (2 critical, 4 high, 2 medium). Applied: #1/#7 → D14; #2
  (gate trusts a hand-written status) is covered by stage 6 and the approvals
  contract; #3 (chapter-per-video code) is replaced by stages 3-5; #4 → private
  CI scope written into the design; #5 → calibration corrected; #6 → per-lecture
  inventory + D17; #8 → single Minimum/Stretch list in the design, plus the CI
  replay task below.
- Spec reviewer (CEO plan + this file): 6/10, 12 issues. Fixed: design
  consistency (R2-1..R2-8, R2-11 written in), private-mode rendering, extras as
  config stages with cut-line positions and plant/audit coverage,
  `capture.fallback`, calibration, runner key, audit as a rate with a
  small-sample rule, PDF engine (D15), per-stage rescue actions, unledgered
  additions (D16), human-time budget and day-3/8/10/12 triggers. No re-review was
  run after the fixes (one review round).

## Human time budget (one reviewer)
Outline 1 h · slice self-review 1 h · full-PDF read 4-6 h · review queue 3-5 h ·
disagreements 1-2 h · audit 2 h + clip check 40 min · second playlist 3-4 h ·
glossary/exercise check 1 h. **Total ≈ 17-23 h over 14 days.** The day-3
checkpoint re-estimates this from measured minutes per paragraph.

## What already exists
`core.py` snapshot/digest/manifest/order checks; `review_is_current`; the
`validate_chapter` ID check; offline replay and hash checks in `build.py`; nine
synthetic tests; CI that runs pytest. Data: manifest of 43 videos; captions for
Xpr8D6LeAtw.

## Dream state delta
Current: 1/43 captions, 0 prose. After this plan: a read and corrected
43-lecture book that carries its own evidence, plus a playlist-agnostic engine.
What's left toward the 12-month ideal: more source types and a public CLI.

## Failure modes registry
| Failure | Detection | Impact | Plan response |
|---|---|---|---|
| YouTube blocks capture | reason code RequestBlocked | missing lectures | backoff; Whisper if allowed; else gap blocks release |
| Judge passes a false claim | plant misses, audit | wrong fact in book | calibration, review queue, audit gate |
| Extraction drops content | inventory, D17 clip audit | incomplete book | gate on untaught importance-3 points |
| Azure model version changes | cache records version | stale cache | invalidate, rerun affected stages |
| Budget exhausted mid-run | cost meter | partial book | stop before the call; `--only` resume |
| Quarto/LaTeX breaks in CI | render job | no PDF | pinned versions; cached TinyTeX |
| Schedule slips | day 3/8/10/12 triggers | extras missing | cut line, minimum book still ships |

## Implementation Tasks
1. [P1] First commit of the scaffold (Mahima's commit) · S · CC 5 min
2. [P1] Probe both Azure deployments; install Quarto + TinyTeX; start full capture (D13 reason codes) · S · CC 30 min
3. [P1] `llm.call` gateway: cache keyed by content, typed errors (D12), cost meter, budget, concurrency (D16) + fixture tests · M · CC 1.5 h
4. [P1] Stage runner keyed by `stage_id + inputs_hash`; `status`, `--only` (D16) · S · CC 1 h
5. [P1] segment (`VIDEO@S`, line-tagged windows) + extract + inventory · M · CC 1.5 h
6. [P1] outline (grouped then merged) + approval records + code mapping · M · CC 1.5 h
7. [P1] write (sentence tags F/T/C) + validate · M · CC 1 h
8. [P1] verify: judge (2nd deployment), rewrite pass, review queue, plants with exclusion test, injection plant (D16) · L · CC 2.5 h
9. [P1] Quarto/LaTeX render with margin key, private-mode `quotes.json`, report; the day-3 checkpoint · M · CC 2 h
10. [P1] CI: offline replay job; secret scan of the cache (D16) · S · CC 45 min
11. [P1] Scale to 43 lectures; re-fit the cutoff; Mahima reads the full PDF (day 8) · L · human 4-6 h
12. [P2] Code stage (exec/display, CPU torch, freeze) · M · CC 2 h
13. [P2] Second playlist, full gate (D8) · M · CC 1 h + human 3-4 h
14. [P2] HTML popovers; Pages · S · CC 1 h
15. [P2] Audit + D17 clip check; release gate · M · human 3 h
16. [P3] Heatmap, glossary + index, `why`, exercises · M · CC 2.5 h
17. [P3] Figures stage · L · CC 3 h

## Completion Summary
- Mode: SCOPE EXPANSION, then sequenced book-first after the outside reviews (D14).
- Decisions: 17 rows, all approved. Two answers differed from my recommendation:
  D8 (full gate for the second playlist) and D11 (same-provider judge). One
  accepted extra went against a recommended defer: D7.4 (exercises).
- Critical gaps found: 2 (D12 model-call errors, D14 build order), both resolved.
- Sections 1-10 reviewed; Section 11 skipped (no app UI).
- Outside voice: Codex completed. Spec review: design doc 2 rounds (6→8/10);
  CEO plan 1 round (6/10, fixes applied, not re-reviewed).

Approval readiness: PASS. Checked rows D1-D3, P1-P5, D5, REF, D6, DOC, D7.1-D7.4,
D8-D17 against their quoted answers above.

## GSTACK REVIEW REPORT

| Run | Status | Findings |
|---|---|---|
| plan-ceo-review (Sections 1-10) | done | 2 critical (resolved), 6 warnings (resolved) |
| office-hours spec review (design) | CONVERGENCE, 8/10 | 35 observed, 21 confirmed resolved, rest fixed after the review |
| CEO plan spec review | 6/10, fixes applied | 12 issues, all addressed, not re-reviewed |
| Outside voice (Codex) | completed | 8 findings; all mapped to D14/D17 or contracts |

OUTSIDE COVERAGE / CROSS-MODEL: Codex (office-hours cold read + plan challenge),
Claude subagents (3 spec reviews). Codex and Claude agreed that the schedule was
overloaded; resolved by D14.

VERDICT: APPROVED FOR IMPLEMENTATION (book-first). Status: clean.

NO UNRESOLVED DECISIONS
