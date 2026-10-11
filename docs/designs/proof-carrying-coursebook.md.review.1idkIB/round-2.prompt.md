# Office-hours independent spec review — round 2

Document: /Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md
Verdict: /Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md.review.1idkIB/round-2.json

Use only Read and Write for this review. Read the design at "/Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md" with Read and review all 5 dimensions independently, including new defects. Do not use Bash or Edit, and do not change the design.
Use Write only to save your complete verdict as JSON to "/Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md.review.1idkIB/round-2.json", then return that identical JSON as your entire response (no Markdown fences or prose). The parent runs the formatter to validate your saved JSON.
The saved JSON is your sole findings inventory: include every unresolved problem and necessary remedy, including minor findings that a short conclusion might omit.
Use one finding per distinct obligation. An exact duplicate shares a finding; a shared component does not combine separate decisions, behavior, or effort.

This is an /office-hours design and coaching document, produced before engineering planning. The startup-mode 'The Assignment' and both modes' 'What I noticed about how you think' sections are intentional: evaluate their evidence and usefulness; do not remove them merely because they are coaching content. Unknown customer facts may remain explicit Open Questions or assignments; do not invent answers.
Still flag unsupported claims, contradictions, safety/correctness risks, and missing behavior needed by the approach the document actually commits to. Labeling a contradiction or a required behavior an open question does not resolve it.

On re-review, classify EVERY preceding finding as resolved, persisting, or unverified. Cite the specific document decision/behavior proving the status or the missing evidence. Absence from the new findings list is not confirmation.
A new refinement of an accepted fix is new unless the same specific original obligation demonstrably remains unmet. For persisting/unverified issues, include that unmet obligation in the current findings and reference its current ID. Distinct prior obligations must retain distinct current findings.

Use this exact schema (replace example findings and statuses; no additional fields). The round and document below are assigned values:

```json
{
  "version": 1,
  "round": 2,
  "document": "/Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md",
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
      "problem": "The fallback's user-visible behavior is unspecified.",
      "remedy": "Choose and document whether the fallback warns the user or is intentionally silent."
    }
  ],
  "prior": []
}
```

Finding IDs are R2-<number>; dimension names are the five lowercase keys above. Supply a quality score from 1 to 10. A dimension is ISSUES exactly when it has findings; otherwise PASS.
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
  "version": 1,
  "round": 1,
  "document": "/Users/mahimaarora/Projects/coursebook/docs/designs/proof-carrying-coursebook.md",
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
      "dimension": "consistency",
      "problem": "The success criterion and Distribution Plan require a fresh clone of a public repo plus `make book` to reproduce outputs offline in public CI, and Premise 3 commits captions to the repo, but Open Question 3 says captions may not be committable and proposes hashes plus a private data package. If that fallback is taken, public CI has no inputs to replay, so the committed reproducibility contract cannot hold as written.",
      "remedy": "State the replay contract for both rights outcomes: what public CI replays when captions cannot be published (for example, cached model outputs plus hashes only, with stages that need raw captions skipped and verified only locally), and reword the success criterion so it is achievable under the private-data fallback."
    },
    {
      "id": "R1-2",
      "dimension": "feasibility",
      "problem": "Stage 8 sends video frames to a vision model, and the cache key includes an inputs hash, but Open Question 4 keeps frames only in a local cache. Offline CI replay cannot recompute the cache key for figure calls without the frames, and it cannot re-run diagram verification against the frame evidence.",
      "remedy": "Specify that frame hashes are recorded in the manifest and used as the cache-key input, so replay looks up figure responses without the image bytes, and say which figure checks run only locally."
    },
    {
      "id": "R1-3",
      "dimension": "consistency",
      "problem": "The Problem Statement makes 'no hallucinations' a hard rule, but the release gate tolerates a measured error rate (proposed at most 2 material errors in 100 audited claims), and the success criteria only publish rates. The document both promises zero and accepts a non-zero rate.",
      "remedy": "Restate the hard rule as the measurable guarantee the pipeline actually provides (every claim cited and judged, a published audited error rate, and a release gate), and say how the book discloses residual risk to readers."
    },
    {
      "id": "R1-4",
      "dimension": "consistency",
      "problem": "The evidence granularity disagrees between sections. 'What Makes This Cool' promises that every paragraph links to the exact caption line and second, while stage 2 cites ~30 s windows (`VIDEO@mm:ss`) and stage 5 says every sentence carries citations. Paragraph versus sentence, and exact second versus 30-second window, are different contracts.",
      "remedy": "Pick one citation unit (sentence or paragraph) and one anchor precision (window start, or the caption line inside the window), and use them consistently in the feature list, stage 5 and the render stage."
    },
    {
      "id": "R1-5",
      "dimension": "feasibility",
      "problem": "A citation on every sentence of an 8-10 chapter book, rendered as PDF footnotes, means thousands of footnotes. That conflicts with the core requirement of a coherent, readable eBook. Footnote labels like `[^VIDEO@mm:ss]` also repeat across sentences, and Pandoc footnote labels must be unique per definition.",
      "remedy": "Define how citations render in the PDF (for example, grouped per paragraph, numbered endnotes per chapter, or a compact margin source key) and how repeated window IDs map to footnote definitions without collisions."
    },
    {
      "id": "R1-6",
      "dimension": "clarity",
      "problem": "The rule 'every sentence carries citations' does not say how transitional, structural or pedagogical sentences that make no factual claim are handled, or how sentences that rely only on the reference pack are cited. The `validate_chapter` first gate cannot be specified without this.",
      "remedy": "Define which sentence types need a caption citation, which may cite the reference pack instead, and which are exempt, and make the citation-ID gate enforce that rule."
    },
    {
      "id": "R1-7",
      "dimension": "completeness",
      "problem": "The planted-false-claim test is central to the headline feature, but its method is unspecified: who or what writes the false claims, what kinds and subtlety they cover, where they are inserted, whether the judge is blinded to which claims are planted, and how they are guaranteed to be removed from the published book. Ten plants also give a very coarse catch rate.",
      "remedy": "Specify the planting protocol (source of plants, mix of claim types and difficulty, insertion point, blinding, sample size per chapter or book) and the mechanism that keeps planted text out of release artifacts."
    },
    {
      "id": "R1-8",
      "dimension": "completeness",
      "problem": "The blinded audit of 100 auto-passed claims has no defined auditor, blinding method, sampling scheme or definition of a 'material error'. For a solo assignment it is unclear who is blinded to what. It is also undefined what happens after the gate blocks a release.",
      "remedy": "Define who performs the audit and what they are blinded to, how the 100 claims are sampled (random or stratified by chapter or claim kind), the material-error rubric, and the remediation path when the threshold is exceeded (fix, re-verify, re-sample)."
    },
    {
      "id": "R1-9",
      "dimension": "completeness",
      "problem": "Stage 6 says 'one rewrite pass, then flag' but does not say whether rewritten text is re-verified, and does not say what happens when a human edits or rewrites a flagged paragraph during review (re-verification, new review hash, cache impact).",
      "remedy": "State that every rewritten or human-edited paragraph goes back through claim extraction and judging, and that its review record is bound to the post-edit hash through `review_is_current`."
    },
    {
      "id": "R1-10",
      "dimension": "completeness",
      "problem": "The reference policy says lecture/reference-pack disagreements are 'flagged, never silently resolved', but it does not say who resolves a flag, what the book shows the reader when the sources disagree, or whether an unresolved disagreement blocks release.",
      "remedy": "Define the disagreement workflow: it enters the human review queue, the allowed outcomes (follow the lecture, follow the reference, or show both with a note), how the outcome renders in the book, and whether open disagreements block the release gate."
    },
    {
      "id": "R1-11",
      "dimension": "consistency",
      "problem": "Premise 5 and the Problem Statement name 'web citations' and 'external check' as optional stages, but the pipeline has no web-citation stage. The only external source is the reference pack. It is unclear whether web search is in scope.",
      "remedy": "Either add the web-citation stage with its inputs, caching and verification, or remove web citations from Premise 5 and define 'external check' as the reference pack only."
    },
    {
      "id": "R1-12",
      "dimension": "completeness",
      "problem": "Human approvals (the outline hash, flagged-paragraph sign-offs) are mandatory gates, but the document does not say how `make book` and CI treat them: whether approval records are committed artifacts, and whether replay fails when an approval is missing or stale.",
      "remedy": "Specify that approval and review records are committed artifacts tied to content hashes, and that `make book` and CI fail (or mark the build as unreleasable) when any required approval is missing or stale."
    },
    {
      "id": "R1-13",
      "dimension": "clarity",
      "problem": "The success criterion 'the second playlist builds with a new config file only' conflicts with the pipeline needing per-playlist outline approval, review records, cached captions and model responses. It is unclear whether those count as allowed data or violate 'config only'.",
      "remedy": "Restate the criterion as 'no code changes', and list the per-playlist data artifacts (config, captions or hashes, cache, approvals) that are expected alongside the config."
    },
    {
      "id": "R1-14",
      "dimension": "clarity",
      "problem": "Premise 5 says optional stages 'switch off cleanly when a playlist has nothing for them' but does not say whether they are switched off by config flags or by auto-detection, or what 'cleanly' means for the render and the evaluation report (for example, no figures section, and code tests reported as skipped). The config schema is listed only as topic, reader profile, reference pack and code language.",
      "remedy": "Define the config schema, including per-stage enable flags or detection rules, and the documented output of each stage when it is disabled."
    },
    {
      "id": "R1-15",
      "dimension": "feasibility",
      "problem": "Running 'every code listing' from `rasbt/LLMs-from-scratch` in CI inside an offline replay job is under-specified. Many listings need PyTorch, downloaded GPT-2 weights or datasets, or long training runs, which conflicts with no-network replay and CI time limits. Executed listings with random seeds or timings also make the Markdown/HTML hash comparison unstable.",
      "remedy": "Define the CI code contract: pinned CPU-only dependencies, which listings execute and which are display-only, how weights and data are handled (excluded or cached), fixed seeds, and whether executed outputs are frozen (for example, with Quarto freeze) before hashing."
    },
    {
      "id": "R1-16",
      "dimension": "clarity",
      "problem": "Stage 7 maps reference-pack files to sections, but the lectures (Dr Dandekar) are not the same course as the reference repo (Raschka). There is no rule for when a listing differs from the code taught in the lecture, or for how the mapping is chosen, by the model or by a person.",
      "remedy": "Specify how listings are matched to sections (model proposal plus human approval, or config mapping), and what to do when the reference code diverges from the lecture's code (flag it through the disagreement workflow, or prefer one source)."
    },
    {
      "id": "R1-17",
      "dimension": "completeness",
      "problem": "The figures stage has no failure path. A vision-generated SVG of a whiteboard may be wrong or may fail the claims-back verification, and raw frames cannot be published under Open Question 4. It also does not say what the diagram-derived claims are checked against, since the evidence is an image rather than a caption window.",
      "remedy": "Define the evidence a diagram's claims are judged against (the cited caption windows around the frame), and the fallback when a diagram fails verification (drop it, simplify it, or route it to human review)."
    },
    {
      "id": "R1-18",
      "dimension": "feasibility",
      "problem": "Days 4-7 assume capture of all 43 lectures (31 h), but only 1/43 has captions, YouTube blocks cloud IPs, local capture is rate-limited, and the Whisper fallback over 31 h of audio is slow. Human review of the flagged queue and the outline across the whole book is also not estimated. The schedule has no buffer for either.",
      "remedy": "Estimate the capture time (including the Whisper fallback) and the expected review-queue size and human hours, and either start full capture on day 1 in parallel with the slice or extend the days 4-7 allocation."
    },
    {
      "id": "R1-19",
      "dimension": "scope",
      "problem": "The plan commits to all four headline features, an HTML edition with popovers, GitHub Pages, a second playlist in CI and a blinded audit in about 14 days. The coaching section says this holds only because of slice-first ordering, but there is no cut line saying what gets dropped first if the slice or the full run slips.",
      "remedy": "Add an explicit priority order and descoping rule: a minimum submittable book (for example, grounded chapters, citations, verification report and offline replay) versus stretch items (figures, popovers, Pages), with a checkpoint date for the decision."
    },
    {
      "id": "R1-20",
      "dimension": "feasibility",
      "problem": "There is no cost or token budget, although Open Question 1 leaves the model and budget open. Extraction over 31 h of captions, an outline over all teaching points, per-sentence claim judging, a rewrite pass, the planted-claim runs and vision calls could be expensive. It is also unclear whether the outline prompt over all 43 lectures' points fits one context window.",
      "remedy": "Give an order-of-magnitude call and token estimate per stage, a budget ceiling, and the outline strategy if all teaching points exceed the context window (hierarchical or per-module outlining)."
    },
    {
      "id": "R1-21",
      "dimension": "clarity",
      "problem": "Stage 3 'lecture chunk' size, the 'importance' scale and threshold used by the stage 4 coverage check, and the 'low-confidence' threshold that sends a paragraph to human review are all undefined, so the coverage check and the review queue cannot be implemented or sized.",
      "remedy": "Define the chunk size, the importance scale and the cutoff that counts as 'important', and the confidence signal and threshold that route a paragraph to review."
    },
    {
      "id": "R1-22",
      "dimension": "clarity",
      "problem": "The cache key uses 'model ID', but on Azure the deployment name can point at a model version that changes. The window ID `VIDEO@mm:ss` is also ambiguous for lectures up to 94 minutes (whether minutes go beyond 59 or an hours field is added).",
      "remedy": "Record the resolved model version returned by the API (not just the deployment name) in the cache key or entry, and define the window ID format for lectures over 60 minutes."
    }
  ],
  "prior": []
}
```
