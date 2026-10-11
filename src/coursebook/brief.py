"""The 6W brief: one markdown file per question, written next to the book.

    reader.md         WHO / WHAT  who the book is for, what it may assume (inferred, evidence-linked)
    coverage.md       HOW MUCH    lectures, points, placed / dropped / auto-placed, gaps
    concept_map.md    WHERE       which lectures feed which chapters and sections (+ Mermaid map)
    learning_path.md  WHEN        reading order with source minutes; production readiness gates
    pipeline.md       HOW         stages, models, prompts, calls, cost, cache use
    rationale.md      WHY         release conditions, measured rates against targets, evaluator verdict
Generated from stored results only (no model calls); regenerated on every render.
"""
import json
from collections import Counter
from pathlib import Path
from . import runner
from .core import digest


def clock(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _points(root, outline):
    return {p["id"]: p for v in outline["lectures"] for p in (runner.load(root, "extract", v) or {"points": []})["points"]}


def coverage_md(root, manifest, outline, label):
    points = _points(root, outline)
    placed = {i for c in outline["chapters"] for s in c["sections"] for i in s["point_ids"]}
    dropped = {d["point_id"]: d["reason"] for d in outline["dropped"]}
    auto = set(outline.get("auto_placed", []))
    covered = set(outline["lectures"])
    out = ["# coverage.md", "", "How much of the course reached the book. Every teaching point is placed in a "
           "section or dropped with a reason.", "",
           "| Lecture | Points | Core | Placed | Dropped | Auto-placed | Empty chunks |", "|---|---:|---:|---:|---:|---:|---:|"]
    for v in outline["lectures"]:
        ex = runner.load(root, "extract", v)
        ps = ex["points"]
        out.append(f"| {label[v]} | {len(ps)} | {sum(p['importance'] == 3 for p in ps)} | "
                   f"{sum(p['id'] in placed for p in ps)} | {sum(p['id'] in dropped for p in ps)} | "
                   f"{sum(p['id'] in auto for p in ps)} | {sum(1 for i in ex['inventory'] if i['flag'])} |")
    out += ["", f"**Totals:** {len(points)} points · {len(placed)} placed · {len(dropped)} dropped · {len(auto)} auto-placed", ""]
    missing = [e for e in manifest["entries"] if e["video_id"] not in covered]
    if missing:
        out += ["## Not covered", ""] + [f"- {label.get(e['video_id'], '#%d' % e['playlist_index'])}: {e['title']}" for e in missing] + [""]
    kinds = Counter(p["kind"] for p in points.values())
    out += ["## Kinds of teaching point", ""] + [f"- {k}: {n}" for k, n in kinds.most_common()] + [""]
    if dropped:
        out += ["## Dropped, with reasons", ""] + [f"- {points[i]['text']} — *{r}*" for i, r in dropped.items() if i in points] + [""]
    return "\n".join(out)


def concept_map_md(root, outline, label):
    points = _points(root, outline)
    out = ["# concept_map.md", "", "Where each part of the course lives in the book: which lectures feed which "
           "chapters and sections.", ""]
    edges = Counter()
    for c in outline["chapters"]:
        out += [f"## {c['id']} · {c['title']}", "", c["summary"], ""]
        for s in c["sections"]:
            feeds = Counter(label[points[i]["video_id"]] for i in s["point_ids"] if i in points)
            out.append(f"- **{s['title']}** ← " + ", ".join(f"{l} ({n})" for l, n in sorted(feeds.items())))
            for l, n in feeds.items():
                edges[(l, c["id"])] += n
        out.append("")
    out += ["## Map", "", "```mermaid", "flowchart LR"]
    for (lecture, chapter), n in sorted(edges.items()):
        out.append(f"  {lecture}[\"{lecture}\"] -->|{n}| {chapter}[\"{chapter}\"]")
    out += ["```", ""]
    return "\n".join(out)


def learning_path_md(root, outline, label, status):
    points = _points(root, outline)
    out = ["# learning_path.md", "", "When the reader meets each idea (reading order, with the source minutes behind it), "
           "and when the book is ready (production gates).", "", "## Reading order", ""]
    for c in outline["chapters"]:
        out.append(f"**{c['id']} · {c['title']}**")
        for s in c["sections"]:
            spans = {}
            for i in s["point_ids"]:
                p = points.get(i)
                if not p:
                    continue
                starts = [float(x.split("@")[1].rstrip("abcdefghij")) for x in p["line_ids"]]
                lo, hi = spans.get(p["video_id"], (min(starts), max(starts)))
                spans[p["video_id"]] = (min(lo, *starts), max(hi, *starts))
            where = "; ".join(f"{label[v]} {clock(a)}–{clock(b)}" for v, (a, b) in spans.items())
            out.append(f"1. {s['title']} — {where}")
        out.append("")
    out += ["## Readiness gates", "", "| Gate | State |", "|---|---|"] + [f"| {g} | {v} |" for g, v in status.items()] + [""]
    return "\n".join(out)


def pipeline_md(root, config):
    calls = []
    for path in sorted((Path(root) / "runs").glob("*.jsonl")):
        calls += [json.loads(line) for line in path.read_text().splitlines()]
    by_stage = {}
    for c in calls:
        b = by_stage.setdefault(c.get("stage"), {"calls": 0, "hits": 0, "cost": 0.0, "versions": set()})
        b["calls"] += 1
        b["hits"] += c.get("cache") == "hit"
        b["cost"] += c.get("cost_usd") or 0
        if c.get("model_version"):
            b["versions"].add(c["model_version"])
    out = ["# pipeline.md", "", "How this book was made: stages, models and what each step cost.", "",
           "Stages: capture → segment → extract → reader → plan/outline → frame → write → verify → takeaways → "
           "diagrams → plant test → evaluator agent → render.", "",
           "| Stage | Model calls | Cache hits | Cost (USD) | Model versions |", "|---|---:|---:|---:|---|"]
    for stage, b in sorted(by_stage.items(), key=lambda kv: str(kv[0])):
        out.append(f"| {stage} | {b['calls']} | {b['hits']} | {b['cost']:.2f} | {', '.join(sorted(b['versions']))} |")
    total = sum(b["cost"] for b in by_stage.values())
    out += ["", f"**Total spend recorded:** ${total:.2f} of a ${config.get('llm', {}).get('budget_usd', 0)} budget.", "",
            "## Prompts", ""] + [f"- `{p.name}` · {digest(p.read_text())[:12]}" for p in sorted(Path('prompts').glob('*.txt'))] + [""]
    return "\n".join(out)


def rationale_md(metrics, reasons, evaluation, config):
    t = config.get("evaluation", {}).get("thresholds", {})
    out = ["# rationale.md", "", "Why this book can (or cannot yet) be trusted: measured rates against targets and "
           "the release conditions.", "", "## Pipeline measurements", "",
           f"- Factual sentences supported after one rewrite: {metrics.get('support_rate_final')}",
           f"- Planted false sentences caught: {metrics.get('plants_caught')} / {metrics.get('plants_planted')}",
           f"- Real sentences wrongly flagged in the plant run: {metrics.get('real_sentences_flagged_in_plant_run')} / {metrics.get('real_sentences_in_plant_run')}",
           f"- Points placed / dropped / auto-placed: {metrics.get('points_placed')} / {metrics.get('points_dropped')} / {metrics.get('points_auto_placed', 0)}", ""]
    if evaluation:
        m = evaluation["metrics"]
        out += ["## Evaluator agent (independent model, blind to pipeline verdicts)", "",
                "| Measure | Result | Target | Pass |", "|---|---:|---:|---|",
                f"| Independent support rate | {m['independent_support']} | ≥ {t.get('independent_support')} | {evaluation['checks']['independent_support']} |",
                f"| Material errors per 100 | {m['material_errors_per_100']} | ≤ {t.get('material_errors_per_100')} | {evaluation['checks']['material_errors_per_100']} |",
                f"| Core ideas missed (clip audit) | {m['core_ideas_missed']} | ≤ {t.get('core_ideas_missed')} | {evaluation['checks']['core_ideas_missed']} |",
                f"| Reading quality (1–5) | {m['quality_average']} | ≥ {t.get('quality_min_average')} | {evaluation['checks']['quality_average']} |",
                "", f"Agreement with the pipeline's judge: {m['agreement_with_judge']} on {m['grounding_sample']} sampled sentences.", ""]
    else:
        out += ["## Evaluator agent", "", "Not run yet (`coursebook evaluate`).", ""]
    out += ["## Release conditions still open", ""] + ([f"- {r}" for r in reasons] or ["- none"]) + [""]
    return "\n".join(out)


def write_brief(root, config, destination, manifest, outline, label, metrics, reasons, status):
    from .stages.reader import reader_markdown
    destination = Path(destination) / "brief"
    destination.mkdir(parents=True, exist_ok=True)
    reader = runner.load(root, "reader", "book")
    evaluation = runner.load(root, "evaluation", "book")
    files = {
        "reader.md": reader_markdown(reader) if reader else "# reader.md\n\nNot inferred yet; run the pipeline.\n",
        "coverage.md": coverage_md(root, manifest, outline, label),
        "concept_map.md": concept_map_md(root, outline, label),
        "learning_path.md": learning_path_md(root, outline, label, status),
        "pipeline.md": pipeline_md(root, config),
        "rationale.md": rationale_md(metrics, reasons, evaluation, config),
    }
    for name, text in files.items():
        (destination / name).write_text(text)
    return sorted(files)
