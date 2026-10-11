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
uv run --locked coursebook run                    # segment, extract, outline, write, verify, plant test
uv run --locked coursebook approve --by "Name"    # approve the current outline (tied to its hash)
uv run --locked coursebook render                 # output/book.pdf + evaluation_report.json
uv run --locked coursebook status                 # progress, spend vs budget, review queue
```

```
captions -> segment (line IDs, 30 s windows) -> extract (teaching points)
  -> outline (concept chapters; human approval) -> write (tagged, cited sentences)
  -> verify (judge each sentence; one rewrite; review queue) -> plants (catch-rate test)
  -> render (Quarto + LaTeX, margin source keys, evaluation report)
```

Each stage stores its output with the hash of its inputs and is skipped when the
inputs are unchanged. Every model response is cached by request hash, so
`coursebook run --offline` rebuilds everything with no API calls and fails loudly
on a cache miss. `run --lectures 8,10` and `--only ch01.s03` limit the work.

## What the guarantees mean

- Citation IDs are checked mechanically; whether a sentence is *supported* is a
  model judgement, measured by the planted-claim test and (planned) a blinded
  human audit. The book states its measured rates instead of promising zero errors.
- The book is marked DRAFT, with reasons, until the outline is approved, the
  review queue is empty, the audit has run and every lecture is covered.
- 21 of the 43 lectures (the odd-numbered ones from 3 to 43) are members-only on
  YouTube; their captions are not publicly retrievable. They are listed as not
  covered.
- Captions are automatic and can be misheard. Raw captions and the model cache stay
  in `data/` (git-ignored) because reuse rights are not established.
