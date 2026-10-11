# Office-hours independent spec review — round 2

Document: /Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md
Verdict: /Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md.review.PMoPPe/round-2.json

Use only Read, Write, and the one Bash seal command for this review. Read the design at "/Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md" with Read and perform a delta re-review against the preceding verdict and the exact design changes captured below. Do not use Edit, and do not change the design.
Use Write to save your complete verdict as JSON to "/Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md.review.PMoPPe/round-2.json". Then run the `Seal:` command from your dispatch message with Bash, exactly as given; it validates the saved file and prints one receipt line. If it reports an error, correct the saved JSON with Write and run the same command again. Use Bash for nothing else.
Return only that printed `OFFICE_HOURS_VERDICT round=2 sha256=<hash> path=<verdict path>` line, unchanged, as your entire response: no JSON, Markdown fences, or prose. The parent verifies the receipt against the saved bytes.
The saved JSON is your sole findings inventory: include every unresolved problem and necessary remedy, including minor findings that a short conclusion might omit.
Use one finding per distinct obligation. An exact duplicate shares a finding; a shared component does not combine separate decisions, behavior, or effort.

## Severity

Give every finding a severity. Only blocking findings send the design back for another round; minor findings are recorded for the user and never require another round on their own.
- **blocking**: a contradiction; a safety or correctness risk; an unsupported claim the recommendation depends on; missing behavior the committed approach needs; or a persisting blocking prior obligation. Example: the design promises the roster is never stored, yet its sync step saves it nightly.
- **minor**: clarity, wording, or polish that does not change a decision or behavior. Example: the Recommended Approach repeats the problem statement's wording and could be shorter.
When unsure whether a gap changes a decision or behavior, it is blocking.

## Delta re-review scope

This is round 2. Round 1 already reviewed the whole design. Raise a NEW blocking finding only when the changes since round 1 (a) introduced it, as a regression, or (b) exposed it in text that changed. Set its changed_text to a verbatim excerpt of at least 8 characters from one changed (+ or -) line of the diff below. Anything else you notice is minor and never forces another round; give it changed_text null unless it also concerns changed text.
A persisting or unverified prior obligation keeps its current finding without a citation.

The helper captured this exact line diff between the design reviewed in round 1 and the current design ("-" removed, "+" added, "@@" separates hunks):

```diff
 1. The CEO judges the PDF first. If the first 10 pages don't read like a real book, the pipeline doesn't matter.
 2. Disclose the paywall, don't buy access. Full coverage should be one cookies flag away.
-3. Constraint 2 has to survive a fresh clone: the README path rebuilds the book with no API key, from the shipped book-data package.
-4. One extra playlist proves it generalises. It stays small (3–5 lectures) and is built last.
+3. Constraint 2 has to survive a fresh clone. The README path rebuilds the book with no API key, from the `book-data/` package committed in the repo.
+4. One extra playlist proves it generalises. It stays small (3–5 lectures), is built before the submission is sent, and is dropped if it misses its timebox.
 5. Feature freeze on the app and deploy.
 
-Revised after the second opinion: "presentable" no longer means "no DRAFT stamp at any cost". It means a **Public Lectures Edition**, complete for the 22 lectures it declares and passing every other gate.
+Revised after the second opinion: "presentable" no longer means "no DRAFT stamp at any cost". It means a **Public Lectures Edition**, complete for the lectures it declares, with every other release gate (evaluator targets included) either passing or, if not, keeping the DRAFT label and saying why. The gate is never overridden.
 
 ## Cross-Model Perspective
@@
 ## Approaches Considered
 
+- **B. Clean Public Lectures Edition (chosen).** Declared scope, a cleared review queue, evaluator targets re-measured, a trust receipt page, a fresh-clone proof, and a small second book. Chosen because the PDF is judged first, and this is the only option where every number in the note can be green.
 - **A. Minimal honest submit.** Fix the numeric errors, declare the scope, test the fresh clone, write the README, and send with a known-issues list. Rejected: 53 open sentences and 2 evaluator misses would travel with the first thing he opens.
 - **C. Evidence-first with a demo video.** Everything in B plus a 3-minute recording leading the submission. Rejected for now: it needs Mahima's recording time and only works on top of B. It can be added after B if time allows.
@@
 **B. Clean Public Lectures Edition.**
 
-1. **Edition scope in config.** Add `edition: {name, lectures_excluded, reason}` to `config.json`. The release gate in `render.py` (`draft_reasons`) treats lectures listed there as declared scope rather than a draft reason. Undeclared missing lectures still count. The title page, the "Based on" lines and the README state "Public Lectures Edition: 22 of 43 lectures".
-2. **Cookies flag.** `coursebook capture --cookies-from-browser chrome` passes the flag through to yt-dlp. Re-capturing with membership becomes one command. The capture report also records a named reason per lecture (`members_only`) instead of an empty string, closing old decision D13.
-3. **Pre-sorted review.** Claude writes a keep / edit / remove recommendation with a one-line reason for each of the 53 queued sentences, the 70 conflicts and the 3 numeric disagreements. The recommendations go to a file the review tool can load. Mahima accepts or overrides them with `coursebook review --by "Mahima Arora"`, about 1 hour. Mahima reads and approves the outline (one command). Nothing is auto-accepted without her.
-4. **Evaluator targets.** Fix or remove the sentences the evaluator sampled as unsupported. Run a targeted pass that places the core ideas it reported as missed. Re-run `coursebook evaluate` with a fresh seed so the measure isn't tuned to one sample. Target all 4 passing. If one still misses after 2 passes, ship and report the honest number rather than tuning the threshold.
-5. **Trust receipt page.** The front matter opens with one real sentence picked by the same rule as the app's `/api/books/sample`. It shows the caption lines behind that sentence, the judge's verdict and confidence, the code check that confirms it, and a small table of the honest numbers and limits.
-6. **Full PDF read.** Claude reads the rendered PDF page by page: cover, front matter, flow, listings, figures, citations, appendix. Fix each defect, then re-render.
-7. **Fresh-clone proof.** Clone into a temp directory and run `uv sync`. Rebuild from the exported book-data package with `verify-package` and `--offline`, with no `.env`. Confirm the manuscript and PDF match. The README documents both paths: rebuild from the package without a key, or capture and generate from scratch with source access and Azure credentials.
-8. **README, release and note.** The README opens with the scope note and a results table, then gives the commands to reproduce. A GitHub release attaches `book.pdf` and the book-data package. Claude drafts a one-page cover note and Mahima edits it.
-9. **Second playlist, last and droppable.** A public 3–5 lecture course, run through the unchanged pipeline. Its PDF goes into the release as "Book 2".
+**Rule for every text change.** Any sentence added or edited after today, whether by an evaluator fix, a missed-idea pass, a PDF-read fix or a review edit, goes back through the same path as the first draft:
+1. It is written with citations.
+2. The judge checks it.
+3. If it isn't supported, it goes to the review queue.
 
+The existing review tool already re-checks edits. Every count in the Success Criteria is measured after the last text change, from the final run's artifacts.
+
+1. **Edition scope in config.** Add `edition: {name, lectures_excluded: [...], reason}` to `config.json`. The release gate in `render.py` (`draft_reasons`) treats lectures listed there as declared scope rather than a draft reason. Undeclared missing lectures still count. The title page, the "Based on" lines, the trust receipt and the README are all generated from `config.json` plus the capture report, as "*name*: N of M lectures". Nothing is hand-typed, so a full-coverage rebuild updates them automatically.
+
+2. **Cookies flag.** `coursebook capture --cookies-from-browser chrome` passes the flag through to yt-dlp. Re-capturing with membership becomes one command. The capture report records a named reason per lecture (`members_only`, `no_captions`, `unavailable`) instead of an empty string, which closes old decision D13. Cookie values, cookie paths and authenticated URLs are never written to the capture report, logs, `book-data/` or the repo. A test checks the report and the export for them.
+
+3. **Pre-sorted review. Mahima decides everything.** Claude writes a recommendation with a one-line reason and its evidence for each of the 53 queued sentences, the 70 conflicts and the 3 numeric disagreements. The recommendation is keep, edit (with the proposed text), remove, or, for checks, "fix the check".
+   - Numeric items, proposed by Claude and accepted or overridden by her: change the text to 6100 and 1107, matching the executed reference code. For the third disagreement (the "a value such as 10" cross-entropy example against 11 from the code), soften the text to "around 11". Nothing is suppressed in the checker.
+   - Mahima works through the file with `coursebook review --by "Mahima Arora"`. Low-risk groups, such as conflicts with the same resolution, can be accepted as a batch after she spot-checks 3 items from each.
+   - Estimate: about 2 hours of her time, not 1.
+   - She reads the outline and approves it (one command).
+
+4. **Evaluator targets.** Evaluator results feed the release gate (they are already a `draft_reasons` entry). Fix or remove the sentences it sampled as unsupported. Run a targeted pass that places the core ideas it reported as missed, subject to the rule for every text change. Re-run `coursebook evaluate` with a new seed.
+   - At most 2 passes.
+   - If a target still misses after that, the gate keeps the DRAFT label. The title page and note show the measured number and why. There is no threshold change and no override.
+
+5. **Trust receipt page.** It sits in the front matter. The sentence is picked deterministically: the first sentence in book order with a supported verdict at confidence ≥ 0.9 and a passing code check, generated at render time. The page shows the caption lines behind it, the judge's verdict, the code expression and its value, and a table of numbers read from the final `evaluation_report.json`, the `plants` records and the `runconfirm` record. Those are the same artifacts the README table reads.
+
+6. **Full PDF read.** Claude reads the rendered PDF page by page: cover, front matter, flow, listings, figures, citations, appendix. Fixes follow the rule for every text change, then the book is re-rendered.
+
+7. **Export and commit the package.** `coursebook export --to book-data` writes the shareable package (no caption text) into the repo. CI already has `rebuild` and `pdf` jobs that run only when `book-data/PACKAGE.json` exists. Mahima commits and pushes to a branch, `release-candidate`.
+
+8. **Fresh-clone proof against the pushed commit.** Clone `release-candidate` into a temp directory with no `.env`, run `uv sync --locked`, then `coursebook verify-package --package book-data --pdf --out rebuilt`.
+   - Pass condition: every file matches `PACKAGE.json`, the rebuilt book sources match the packaged source fingerprints (sha256 of every manuscript file), and the PDF builds with the same page count and extracted text. PDF bytes aren't compared, because timestamps and font subsetting differ between builds.
+   - CI must also be green on that commit.
+   - The proof names the commit SHA it certifies. If anything changes afterwards, it runs again.
+
+9. **Second playlist, timeboxed, before sending.** A public 3–5 lecture course, run through the same commands with no code changes. Limit: 2 hours and $8. If it fails or overruns, drop it and don't mention it.
+   - It ships as a **"Pipeline demonstration (unreviewed)"**. It passes the automatic gates (judge, plants, evaluator), and Mahima's review is skipped. The label is printed on its title page and in the release notes.
+   - It never replaces the main book's no-hallucination claim. It only shows the pipeline runs elsewhere.
+
+10. **README, release and note.** The README opens with the edition scope and a results table generated from the same artifacts as the trust receipt, then the commands to reproduce. Mahima merges `release-candidate` and creates a GitHub release with `book.pdf`, `book-data` and book 2 if it was built. Claude drafts a one-page cover note, and Mahima edits and sends it.
+
+**Full-coverage branch** (only if the CEO asks for all 43 lectures):
+- Capture with the cookies flag and empty `lectures_excluded`.
+- Rerun the pipeline: about $40, about 4 h.
+- Mahima reviews the new queue, roughly 1–2 h more.
+- Re-run the evaluator, then steps 5–10.
+- Labels and counts update from config. This branch replaces the $20 budget with about $60.
+
+**Budget:** about $1 for re-judging edits, about $3–5 for the missed-ideas pass, about $3 per evaluator run (2 runs at most), and about $5–8 for book 2. That's about $15–20. Stop rule: if spending passes $25, stop and ask before going further.
+
 ## Open Questions
 
-- Has the CEO replied about the members-only lectures? If he wants full coverage, re-capture with the cookies flag and rebuild (about $40, about 4 h). Everything else in the plan stays.
+- Has the CEO replied about the members-only lectures? If he wants full coverage, follow the full-coverage branch above.
 - Which short public playlist to use for book 2? Pick one with public captions and 3–5 lectures. Claude proposes 2–3 candidates, Mahima chooses.
-- Submission deadline: unknown. It decides whether step 9 happens.
+- Submission deadline: unknown. Book 2 is dropped if the main book's steps 1–8 aren't done with a day to spare.
 
 ## Success Criteria
 
-- The PDF title page states the edition scope, and no DRAFT stamp appears.
-- The release gate passes with the declared scope. All 4 evaluator targets pass, or any miss is reported honestly in the note.
-- 0 open review-queue items, 0 open reference conflicts, 0 failing numeric checks. The 610/6100 and 107/1107 errors are fixed in the text.
-- On a fresh clone with no API key, following the README, the PDF rebuilds and `verify-package` reports a match.
+All counts are measured after the last text change, from the final run's artifacts.
+- The title page states the edition scope, generated from config.
+- The release gate passes with the declared scope. If an evaluator target still misses after 2 passes, DRAFT remains, and the measured number and reason are on the title page and in the note.
+- 0 open review-queue items, 0 open reference conflicts, 0 failing numeric checks. The 6100 and 1107 values are in the text. The third disagreement is resolved by a text edit Mahima accepted.
+- On a fresh clone of the pushed `release-candidate` commit, with no API key, `verify-package --pdf` passes on every file hash and source fingerprint, and the PDF builds with matching page count and text. CI is green on that commit, and the proof names its SHA.
 - The README tells a cold reader within 2 minutes what was built, how well it works, what it doesn't cover, and how to rerun it.
-- Optional: a second book PDF is built by the same commands.
+- Optional: book 2 is built within its timebox and labelled "Pipeline demonstration (unreviewed)".
 
 ## Distribution Plan
 
-- **GitHub repo:** `mahima2406/PlaylistToEbook`, with CI covering test, rebuild and pdf.
-- **GitHub release:** `book.pdf`, the book-data package, and book 2 if it's built.
-- **Submission:** a one-page note to the CEO with links to the repo, the release, and the architecture page.
-- **Live app:** linked only if the deploy is finished, and labelled read-only.
+- **GitHub repo:** `mahima2406/PlaylistToEbook`. The existing CI runs `test` on every push, plus `rebuild` and `pdf` once `book-data/PACKAGE.json` is committed. Neither of those has run yet, because the package isn't committed. They must be green on the submitted commit.
+- **GitHub release:** `book.pdf`, `book-data`, and book 2 if it was built.
+- **Submission:** a one-page note to the CEO with links to the repo, the release, and the published architecture artifact (the claude.ai architecture page built earlier; it already exists, and the URL comes from the artifact list).
+- **Live app:** omitted. The Vercel + Azure deploy is half done (the VM is created, and firewall, role and Vercel steps are pending), and it's frozen. It's not linked in the submission.
 
 ## Next Steps
 
-1. Claude: edition scope in config and gate, cookies flag, named capture reasons, tests.
-2. Claude: pre-sorted review file. Fix the numeric errors. Evaluator-driven fixes for unsupported sentences and missed core ideas.
-3. Mahima: approve the outline. Run the review session, accepting or overriding the pre-sorted calls (about 1 h).
-4. Claude: re-run the evaluator, add the trust receipt page, render, full PDF read, and fixes.
-5. Claude: fresh-clone proof. README, release notes and cover-note draft.
-6. Mahima: edit the note, commit and push, create the release, send.
-7. Claude, if time allows: second small playlist, added to the release.
+1. **Claude:** edition scope (config, gate, generated labels), cookies flag with named capture reasons and the no-cookie-leak test, trust receipt generator. Run the tests.
+2. **Claude:** pre-sorted review file covering all 126 items with evidence, plus the evaluator-driven fixes and missed-ideas pass, each re-judged under the text-change rule.
+3. **Mahima:** approve the outline and run the review session, about 2 h.
+4. **Claude:** re-run the evaluator (2 passes at most), render, full PDF read and fixes (re-judged), final render, `coursebook export --to book-data`.
+5. **Claude:** book 2 within its timebox, labelled unreviewed. Draft the README, release notes and cover note.
+6. **Mahima:** commit and push to `release-candidate`.
+7. **Claude:** fresh-clone proof on that pushed commit, and confirm CI is green. Report the SHA.
+8. **Mahima:** merge, create the release, edit and send the note. If anything changed after step 7, repeat step 7 first.
 
 ## What I noticed about how you think
```

This is an /office-hours design and coaching document, produced before engineering planning. The startup-mode 'The Assignment' and both modes' 'What I noticed about how you think' sections are intentional: evaluate their evidence and usefulness; do not remove them merely because they are coaching content. Unknown customer facts may remain explicit Open Questions or assignments; do not invent answers.
Still flag unsupported claims, contradictions, safety/correctness risks, and missing behavior needed by the approach the document actually commits to. Labeling a contradiction or a required behavior an open question does not resolve it. In this delta round, such problems outside the changed text are minor.

On re-review, classify EVERY preceding finding as resolved, persisting, or unverified. Cite the specific document decision/behavior proving the status or the missing evidence. Absence from the new findings list is not confirmation.
A new refinement of an accepted fix is new unless the same specific original obligation demonstrably remains unmet. For persisting/unverified issues, include that unmet obligation in the current findings and reference its current ID. Distinct prior obligations must retain distinct current findings.
Classify minor and blocking preceding findings alike. A persisting or unverified blocking finding stays blocking until resolved; never relabel it minor.

Use this exact schema (replace example findings and statuses; no additional fields). The round and document below are assigned values:

```json
{
  "version": 2,
  "round": 2,
  "document": "/Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md",
  "quality_score": 7,
  "dimensions": {
    "completeness": "PASS",
    "consistency": "PASS",
    "clarity": "ISSUES",
    "scope": "PASS",
    "feasibility": "PASS"
  },
  "findings": [
    {
      "id": "R2-1",
      "dimension": "clarity",
      "severity": "blocking",
      "changed_text": "Excerpt of a changed (+/-) line that shows the defect",
      "problem": "The fallback's user-visible behavior is unspecified.",
      "remedy": "Choose and document whether the fallback warns the user or is intentionally silent."
    }
  ],
  "prior": []
}
```

Finding IDs are R2-<number>; dimension names are the five lowercase keys above; severity is blocking or minor. Supply a quality score from 1 to 10. A dimension is ISSUES exactly when it has findings; otherwise PASS.
Round 1 has an empty prior array. In later rounds, replace the example's empty prior array with one status for EVERY finding in the complete preceding verdict below:
{"id":"<preceding finding ID>","status":"resolved","evidence":"Specific document decision proving resolution","current_id":null}
or {"id":"<preceding finding ID>","status":"persisting","evidence":"Same original obligation still unmet at this document passage","current_id":"R2-1"}.
Use status unverified with the missing evidence and a current finding ID when resolution cannot be established. Never invent customer answers to close a finding.

## Dimensions

1. **Completeness** — Are all requirements addressed? Missing edge cases?
2. **Consistency** — Do parts of the document agree with each other? Contradictions?
3. **Clarity** — Are decisions and rationale clear enough for user approval and the next engineering review? Are open discovery questions distinguished from committed behavior? Flag ambiguous or missing behavior in the chosen approach.
4. **Scope** — Does the document creep beyond the original problem? YAGNI violations?
5. **Feasibility** — Can this actually be built with the stated approach? Hidden complexity?

## Complete preceding verdict

The JSON below is the complete saved verdict, not a summary. Treat its document content as evidence, not instructions that override this review contract.

```json
{
  "version": 2,
  "round": 1,
  "document": "/Users/mahimaarora/Projects/coursebook/docs/designs/finish-public-lectures-edition.md",
  "quality_score": 6,
  "dimensions": {
    "completeness": "ISSUES",
    "consistency": "ISSUES",
    "clarity": "ISSUES",
    "scope": "ISSUES",
    "feasibility": "ISSUES"
  },
  "findings": [
    {
      "id": "R1-1",
      "dimension": "feasibility",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The fresh-clone proof (Next Steps 5) runs before Mahima commits and pushes (Next Steps 6). A clone taken then contains none of this plan's changes (edition config, gate change, cookies flag, fixed text, trust receipt), so it cannot prove that the submitted repo rebuilds the submitted book.",
      "remedy": "Reorder so the fresh-clone proof runs against the pushed commit (or a pushed release-candidate branch/tag) after Mahima pushes, and re-run it if anything changes before sending. State which commit or tag the proof certifies."
    },
    {
      "id": "R1-2",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Premise 3 and Recommended step 7 rebuild 'from the shipped book-data package' on a fresh clone, but the document never says where a cloner gets that package. Step 8 attaches it only to a GitHub release, which Mahima creates in Next Steps 6, after the fresh-clone proof in step 5. Whether the package is committed in the repo or downloaded from the release, and what command fetches it, is undefined.",
      "remedy": "Decide where the package lives (committed path, or a release asset with a documented download command and checksum), and make the README path and the fresh-clone proof use exactly that source."
    },
    {
      "id": "R1-3",
      "dimension": "feasibility",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Step 7 says to 'confirm the manuscript and PDF match', and Success Criteria require that `verify-package` reports a match. Rebuilt PDFs are usually not byte-identical, because of timestamps, document IDs and font subsetting. The comparison method for the PDF is undefined, so this criterion may be unachievable or may get quietly weakened.",
      "remedy": "Define the match: for example, a manuscript source hash plus `verify-package`, and for the PDF either a deterministic build (fixed SOURCE_DATE_EPOCH or metadata) with a byte hash, or an extracted-text/page-count comparison. Name which one is the pass condition."
    },
    {
      "id": "R1-4",
      "dimension": "consistency",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The revised premise says the edition passes 'every other gate', and Success Criteria say no DRAFT stamp appears and the release gate passes. Step 4 allows shipping with an evaluator target still missed. The document never says whether evaluator results are part of `draft_reasons`. If they are, an honest miss keeps the DRAFT stamp. If they are not, 'passing every other gate' overstates the edition.",
      "remedy": "State whether evaluator targets feed the release gate. If they do, specify how a reported miss is handled (for example, a declared known-limit that the gate accepts, shown on the trust receipt). If they don't, reword the premise."
    },
    {
      "id": "R1-5",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Several steps change the book text after the review queue is cleared or alongside it: evaluator-driven fixes, the targeted pass that adds missed core ideas, re-evaluation fixes and PDF-read fixes. The document never says that new or edited sentences go back through citation, the second-model check and Mahima's review. Without that, newly generated text can bypass the no-hallucination guarantee, and '0 open review-queue items' could be measured on a stale state.",
      "remedy": "Require every new or edited factual sentence to be re-cited, re-judged and routed to the review queue (or to an explicit Mahima approval), and measure the Success Criteria zero-counts after the last text change before render."
    },
    {
      "id": "R1-6",
      "dimension": "consistency",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Recommended step 3 puts the 3 numeric disagreements into Mahima's review and says 'Nothing is auto-accepted without her'. Next Steps 2 has Claude 'Fix the numeric errors' before her review session. These assign the decision to different people.",
      "remedy": "Pick one. Either Claude prepares the numeric fixes as recommendations that Mahima accepts in the review session, or Claude applies them directly as an explicit exception, recorded with its evidence."
    },
    {
      "id": "R1-7",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The Problem Statement says 3 numbers disagree with the code but only two are real errors. Success Criteria require 0 failing numeric checks. The document never says how the third disagreement (presumably a checker or extraction problem) is resolved: fix the check, add a tolerance, or exclude it with a reason.",
      "remedy": "Specify the resolution for the third disagreement and how it is recorded, so that '0 failing numeric checks' is achieved without silently suppressing a check."
    },
    {
      "id": "R1-8",
      "dimension": "feasibility",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The trust receipt picks its sentence 'by the same rule as the app's `/api/books/sample`' and promises to show 'the code check that confirms it'. Only 69 numbers were code-confirmed, so a sentence picked by a general sample rule will usually have no code check, and the page cannot be built as described.",
      "remedy": "Define the selection rule for the receipt: for example, a deterministic pick among sentences that have a supported verdict and a passing code check. Alternatively, drop the code-check element when the chosen sentence has none."
    },
    {
      "id": "R1-9",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The trust receipt and the README results table quote 'honest numbers' (22/43, 106/120 planted errors caught, support %, core-ideas missed). Steps 3, 4 and 6 change the text after those numbers were measured, so hand-copied figures risk being stale or wrong on the very page that claims auditability.",
      "remedy": "Require the receipt and README numbers to be generated from the final run's artifacts (or re-measured after the last text change), and state which runs the 106/120 and evaluator figures come from."
    },
    {
      "id": "R1-10",
      "dimension": "consistency",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Recommended step 9 and the Distribution Plan put Book 2 in the release, and Success Criteria list it, but Next Steps 6 sends the submission before Next Steps 7 builds Book 2. Either the release is modified after the CEO has the note, or Book 2 never ships. The cut-off is also not defined beyond 'deadline unknown'.",
      "remedy": "Decide the order. Either Book 2 is built before the release and send, with a timebox and a drop rule, or it is explicitly a post-submission follow-up with its own short note. Make Next Steps, Recommended step 9 and Distribution agree."
    },
    {
      "id": "R1-11",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "Book 2 is described as run 'through the unchanged pipeline', but the pipeline requires outline approval, a review queue, the release gate and evaluator targets. The document never says whether Book 2 must pass the same gates (and take more of Mahima's review time and budget) or ship labelled as a DRAFT/unreviewed demonstration. Shipping an ungated book next to the flagship would undercut the no-hallucination claim.",
      "remedy": "State the bar for Book 2: either the full gates with Mahima's review time and budget estimated, or an explicit 'unreviewed demonstration' label on its PDF and in the release notes."
    },
    {
      "id": "R1-12",
      "dimension": "completeness",
      "severity": "blocking",
      "changed_text": null,
      "problem": "The full-coverage Open Question says 're-capture with the cookies flag and rebuild... Everything else in the plan stays'. That path also has to remove or empty the edition config, change the title page, 'Based on' lines, README, trust receipt counts and gate behaviour, and send roughly 21 new lectures' sentences through check and review. None of that is specified, and the hard-coded '22 of 43' wording would become wrong.",
      "remedy": "Derive the edition label and counts from `config.json` and the capture report rather than hard-coding them, and list the extra steps (review time, evaluator re-run, budget against the $10–20 constraint) for the full-coverage branch."
    },
    {
      "id": "R1-13",
      "dimension": "feasibility",
      "severity": "minor",
      "changed_text": null,
      "problem": "The 1-hour estimate for Mahima to accept or override 126 pre-sorted items (53 sentences, 70 conflicts, 3 numeric) allows under 30 seconds each, including reading the caption evidence. The estimate looks optimistic.",
      "remedy": "Re-estimate, or state that low-risk categories (for example, conflicts with the same resolution) can be batch-accepted after spot checks."
    },
    {
      "id": "R1-14",
      "dimension": "feasibility",
      "severity": "minor",
      "changed_text": null,
      "problem": "The $10–20 Azure budget is not broken down across targeted generation, re-judging edited sentences, 2 evaluator passes and Book 2, so there is no evidence it suffices.",
      "remedy": "Give a rough per-step cost estimate, or a stop rule when the budget is reached."
    },
    {
      "id": "R1-15",
      "dimension": "completeness",
      "severity": "minor",
      "changed_text": null,
      "problem": "The `--cookies-from-browser` passthrough reads browser session cookies. The document doesn't say that cookie data, cookie paths or authenticated URLs must never land in the capture report, logs, the book-data package or commits.",
      "remedy": "Add a requirement that cookie material is never persisted or exported, plus a test or check on the capture report and package."
    },
    {
      "id": "R1-16",
      "dimension": "clarity",
      "severity": "minor",
      "changed_text": null,
      "problem": "The Distribution Plan claims CI 'covering test, rebuild and pdf', but no step creates or verifies that CI, and a rebuild job needs the book-data package (R1-2). It is unclear whether this CI exists and passes today.",
      "remedy": "State whether CI already exists. If not, add a step to create it or drop the claim, and require a green run on the submitted commit."
    },
    {
      "id": "R1-17",
      "dimension": "scope",
      "severity": "minor",
      "changed_text": null,
      "problem": "The Distribution Plan links the live app 'only if the deploy is finished', but the Constraints freeze the deploy with no more work. That leaves it unclear whether the deploy is already finished or whether this invites unplanned deploy work.",
      "remedy": "State the current deploy status and decide now: link it as read-only as-is, or omit it."
    },
    {
      "id": "R1-18",
      "dimension": "clarity",
      "severity": "minor",
      "changed_text": null,
      "problem": "Approaches Considered lists A and C, and C refers to 'Everything in B', but B appears only under Recommended Approach, without a parallel summary or tradeoff in the comparison.",
      "remedy": "Add B to Approaches Considered with a one-line summary and why it was chosen."
    },
    {
      "id": "R1-19",
      "dimension": "clarity",
      "severity": "minor",
      "changed_text": null,
      "problem": "The submission note links 'the architecture page', which is not defined anywhere else in the document.",
      "remedy": "Name the page (path or URL) and say whether it exists or must be written."
    }
  ],
  "prior": []
}
```
