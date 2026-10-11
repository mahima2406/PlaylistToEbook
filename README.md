# Coursebook: YouTube playlist to book

Evaluation assignment for playlist `PLPTV0NXA_ZSgsLAr8YCgCwhPIJNNtexWu`.
Status: implementation in progress. Synthetic tests are not evidence of source fidelity.

## Setup

Install Python 3.11 and uv (https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked coursebook inventory
uv run --locked coursebook capture --limit 1
```

`yt-dlp` and `youtube-transcript-api` are project dependencies installed by uv.
No global downloader, Codex session, gstack skill or browser login is required.
The lockfile pins transitive packages. YouTube availability and rate limits are
external dependencies; acquisition failures return nonzero and are recorded.

## Fresh generation

Copy `.env.example` to `.env` locally and fill in credentials, the model deployment
name and the inference base URL. A Foundry project URL is not the inference URL.
Never commit `.env`. Run:

```sh
uv run --locked coursebook draft VIDEO_ID
uv run --locked coursebook build
```

This writes draft `output/book.md`, `book.pdf`, `evaluation_report.json` and
`run_manifest.json`. Model requests and responses are saved under `data/runs/`,
without authentication headers. Fresh model output is not promised to be identical.
No live model call is made by `build`. Model charges apply to `draft`.

## Replay and review

The data package must accompany a submitted book. It contains frozen playlist
metadata, original captions, normalized evidence, saved chapters, model runs and
review decisions. `build` reconstructs outputs from these files without network.
Raw snapshots are content-addressed and checked at build time. Captions are
preserved as returned; automatic captions may contain errors.

For each chapter, a reviewer must inspect source material and final prose and
write `data/reviews/VIDEO_ID.json` with `chapter_hash`, `source_hash`, `reviewer`,
`support_review`, `visual_review`, `source_coverage_review`. The three review
statuses must be `passed`. Hashes must refer to the exact reviewed artifacts.
Do not mark these passed merely because an LLM agrees with itself. Store detailed
review observations beside the decision. Editing prose invalidates prior review.

```sh
uv run --locked coursebook build --release
```

Release fails on missing chapters, unresolved gaps, stale or absent reviews.
Evidence references prove traceability only; they do not establish semantic truth.

## Architecture

Frozen playlist -> unchanged timed captions -> evidence -> candidate paragraphs
-> human claim/source/visual review -> Markdown + PDF + reports.

The initial implementation uses inspectable JSON artifacts. SQLite migration,
multimodal capture, structured teaching-point extraction, chunked drafting,
whole-book editing and durable editorial patches remain planned. This is a
deliberate pilot implementation, not a claim that the full Notion design exists.

## Tests and limitations

CI runs offline synthetic tests for order preservation, bad timestamps, fabricated
references, source tampering, review staleness, deterministic PDF replay and blocked
release. Real acquisition and paid model quality must be tested separately.
The first PDF renderer supports prose with linked citations. Technical code blocks,
equations, figures, Unicode typography and an automatic table of contents are not
yet supported at eBook release quality. No full-playlist book has been verified.

Source reuse permissions are tracked as unknown until established. Generated
data is ignored by git by default; assemble an authorized submission data package
explicitly. Do not distribute credentials or assume source redistribution rights.
