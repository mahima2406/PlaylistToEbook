# Coursebook: YouTube playlist to book

Turns a lecture playlist into a book that carries its own evidence: every factual
sentence cites the caption lines it came from, a second model checks each sentence
against those lines, and the book reports how well that checker catches planted
false claims. First target: "Building LLMs from scratch"
(`PLPTV0NXA_ZSgsLAr8YCgCwhPIJNNtexWu`). Nothing in the code is specific to that
playlist; `config.json` holds the playlist, reader, models and budget.

Design: `docs/designs/proof-carrying-coursebook.md`. Plan and decisions: `docs/PLAN.md`.
Progress: `docs/STATUS.md`.

## Setup

Python 3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/), and
[Quarto](https://quarto.org) with TinyTeX (`quarto install tinytex`) for the PDF.

```sh
uv sync --locked
uv run --locked pytest -q
cp .env.example .env   # writer + judge deployments and key; never commit .env
```

## Pipeline

```sh
uv run --locked coursebook inventory              # freeze the playlist (order, ids, titles)
uv run --locked coursebook capture --limit 43     # captions -> content-addressed snapshots
uv run --locked coursebook run                    # reader, outline, framing, writing, checks, diagrams,
                                                  #   plant test, reference listings, cross-check
uv run --locked coursebook approve --by "Name"    # reviewer approves the current outline
uv run --locked coursebook review --by "Name"     # reviewer settles flagged sentences and reference conflicts
uv run --locked coursebook evaluate               # independent evaluator agent (grounding, coverage, quality)
uv sync --group listings && uv run --locked coursebook run-code   # execute listings, check stated numbers
uv run --locked coursebook render                 # output/book.pdf, output/html/, output/brief/*.md
uv run --locked coursebook why ch02.s09.p02       # full trail behind any sentence or paragraph
uv run --locked coursebook export                 # book-data/ package without raw captions
uv run --locked coursebook verify-package         # rebuild from book-data/ and compare fingerprints
uv run --locked coursebook status                 # progress, spend vs budget, review queue
```

```
captions -> segment (line IDs) -> extract (teaching points) -> reader (reader.md)
  -> plan + outline (concept chapters; reviewer approval) -> frame (intro, openers, at a glance)
  -> write (tagged, cited sentences) -> verify (judge, one rewrite, review queue)
  -> takeaways -> diagrams (each arrow checked) -> plant test (catch rate)
  -> reference listings (verbatim code) -> cross-check (conflicts to the reviewer)
  -> evaluator agent -> run-code (output + numeric checks) -> render (PDF + web edition + 6W brief)
```

Each stage stores its output with the hash of its inputs and is skipped when the
inputs are unchanged. Every model response is cached by request hash, so
`coursebook run --offline` rebuilds everything with no API calls and fails loudly
on a cache miss.

### The 6W brief (`output/brief/`)

| File | Question | Content |
|---|---|---|
| `reader.md` | who / what | inferred reader contract; every field cites evidence or is `unknown`; the configured brief overrides |
| `coverage.md` | how much | points per lecture placed / dropped / auto-placed; lectures not covered |
| `concept_map.md` | where | lectures → chapters → sections, with a map |
| `learning_path.md` | when | reading order with source minutes; readiness gates |
| `pipeline.md` | how | stages, models, calls, cache use and cost |
| `rationale.md` | why | measured rates against targets; evaluator agent verdict; open release conditions |

### Editions

- `output/book.pdf`: printed book (Quarto + LaTeX), chapter-level sources, appendix with
  per-section minute ranges and a coverage heatmap.
- `output/html/`: web edition; every paragraph has a hover note with its lecture
  timestamps (links jump to that second) and a short caption quote.

## What the guarantees mean

- Citation IDs are checked mechanically; whether a sentence is *supported* is a
  model judgement, measured by the planted-claim test and re-checked on a random
  sample by an independent evaluator agent (a third model, blind to the judge). The book states its measured rates instead of promising zero errors.
- The book is marked DRAFT, with reasons, until the outline is approved, the
  review queue and reference conflicts are settled, the evaluator agent passes,
  stated numbers agree with the executed code, and every lecture is covered.
- 21 of the 43 lectures (the odd-numbered ones from 3 to 43) are members-only on
  YouTube; their captions are not publicly retrievable. They are listed as not
  covered.
- Captions are automatic and can be misheard. Raw captions and the model cache stay
  in `data/` (git-ignored) because reuse rights are not established.
