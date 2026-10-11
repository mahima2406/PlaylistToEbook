"""WHO / WHAT: infer the reader contract (reader.md) from course evidence.

    lecture titles + intro-lecture captions + core points sampled early/middle/late
        ──writer──> reader contract (every inferred field cites evidence, or is "unknown")
    precedence: explicit reader brief (config "reader", status "override") > inferred > unknown
The contract is rendered to reader.md. When `reader_profile.enabled` is true, its text
replaces the one-line reader brief in every writing prompt (so turning it on rewrites
the book; its hash is part of those stages' inputs).
"""
from pathlib import Path
from ..core import digest, read
from .. import runner
from .segment import format_lines

PROMPT = Path("prompts/reader.txt")
STATUSES = {"observed", "inferred", "unknown", "override"}
LIST_FIELDS = ["known_prior_skills", "unknown_prior_skills", "instructional_modes", "representations_to_preserve"]
POINTS_PER_PHASE = 15


def validate_reader(obj, evidence_ids):
    errors = []

    def check(item, where):
        if not isinstance(item, dict) or not str(item.get("value", "")).strip():
            errors.append(f"{where}: needs a value")
            return
        if item.get("status") not in STATUSES:
            errors.append(f"{where}: status must be one of {sorted(STATUSES)}")
        ev = item.get("evidence") or []
        if item.get("status") in ("observed", "inferred") and not ev:
            errors.append(f"{where}: {item.get('status')} values need evidence IDs")
        bad = [e for e in ev if e not in evidence_ids]
        if bad:
            errors.append(f"{where}: unknown evidence IDs {bad[:3]}")

    for field in ("primary_learning_outcome", "reader_profile"):
        check(obj.get(field), field)
    for field in LIST_FIELDS:
        for n, item in enumerate(obj.get(field) or []):
            check(item, f"{field}[{n}]")
    for field in ("uncertainties_to_validate", "editorial_rules"):
        if not isinstance(obj.get(field), list):
            errors.append(f"{field} must be a list")
    return errors


def sample_points(points_by_video, entries):
    """Core points from early, middle and late lectures (representative sampling)."""
    n = len(entries)
    phases = {"early": entries[: max(1, n // 3)], "middle": entries[n // 3: max(n // 3 + 1, 2 * n // 3)],
              "late": entries[2 * n // 3:] or entries[-1:]}
    sample = []
    for phase, group in phases.items():
        core = [p for e in group for p in points_by_video[e["video_id"]] if p["importance"] == 3]
        step = max(1, len(core) // POINTS_PER_PHASE)
        sample += [{**p, "phase": phase} for p in core[::step][:POINTS_PER_PHASE]]
    return sample


def infer_reader(gateway, config, entries, points_by_video, intro):
    sample = sample_points(points_by_video, entries)
    intro_lines = intro["lines"] if intro else []
    evidence_ids = {x["id"] for x in intro_lines} | {p["id"] for p in sample}
    titles = "\n".join(f"Lecture {e['playlist_index']}: {e['title']}" for e in entries)
    points = "\n".join(f"{p['id']} ({p['phase']}, L{p['lecture']}) {p['text']}" for p in sample)
    brief = config.get("reader") or "(none)"
    messages = [{"role": "system", "content": PROMPT.read_text()},
                {"role": "user", "content": f"Explicit reader brief: {brief}\n\nLectures:\n{titles}\n\n"
                                            f"Introductory lecture captions:\n{format_lines(intro_lines, True) or '(not available)'}\n\n"
                                            f"Sampled core points:\n{points}"}]
    contract = gateway.call_json("writer", messages, stage="reader", input_id="book", max_completion_tokens=16000,
                                 validate=lambda o: validate_reader(o, evidence_ids))["parsed"]
    return {"contract": contract, "brief": brief, "sampled_points": [p["id"] for p in sample],
            "intro_lecture": intro["video_id"] if intro else None}


def run_reader(root, gateway, config, entries):
    from .frame import intro_entry
    from .segment import run_segment
    points_by_video = {e["video_id"]: runner.load(root, "extract", e["video_id"])["points"] for e in entries}
    entry = intro_entry(root, config)
    intro = run_segment(root, entry["video_id"]) if entry else None
    inputs = {"extract": {e["video_id"]: runner.output_hash(root, "extract", e["video_id"]) for e in entries},
              "intro": digest(intro) if intro else None, "brief": config.get("reader"),
              "prompt": digest(PROMPT.read_text()), "v": 1}
    return runner.run(root, "reader", "book", inputs, lambda: infer_reader(gateway, config, entries, points_by_video, intro))


def reader_markdown(record, label=lambda vid: vid):
    """Render the contract as reader.md (human-editable view; evidence as lecture + time)."""
    c = record["contract"]

    def ev(item):
        ids = item.get("evidence") or []
        return f" _[{item['status']}; evidence: {', '.join(ids[:4])}{' …' if len(ids) > 4 else ''}]_" if ids else f" _[{item['status']}]_"

    out = ["# reader.md", "", "Who this book is for and what it may assume. Inferred from the course; every inferred "
           "value cites evidence or is marked unknown. An explicit brief overrides inference.", "",
           f"**Explicit brief (override):** {record['brief']}", "",
           f"## Primary learning outcome\n\n{c['primary_learning_outcome']['value']}{ev(c['primary_learning_outcome'])}", "",
           f"## Reader profile\n\n{c['reader_profile']['value']}{ev(c['reader_profile'])}", ""]
    titles = {"known_prior_skills": "Known prior skills", "unknown_prior_skills": "Unknown prior skills (do not assume)",
              "instructional_modes": "How the course teaches", "representations_to_preserve": "Representations to preserve"}
    for field, title in titles.items():
        out += [f"## {title}", ""] + [f"- {i['value']}{ev(i)}" for i in c.get(field) or []] + ["- (none recorded)" if not c.get(field) else "", ""]
    out += ["## Editorial rules", ""] + [f"- {r}" for r in c.get("editorial_rules") or []] + [""]
    out += ["## Uncertainties to validate", ""] + [f"- {u}" for u in c.get("uncertainties_to_validate") or []] + [""]
    return "\n".join(out)


def reader_for_prompts(root, config):
    """Text given to writing prompts: reader.md when enabled and present, else the one-line brief."""
    if not config.get("reader_profile", {}).get("enabled"):
        return config["reader"]
    record = runner.load(root, "reader", "book")
    if record is None:
        raise ValueError("reader_profile.enabled is true but no reader profile exists; run the pipeline first")
    return reader_markdown(record)
