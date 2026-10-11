"""Independent evaluator agent: judges the finished book on the release metrics.

Runs with its own model ("evaluator" role), its own prompts, and never sees the
pipeline's verdicts, rewrites or review decisions. Three audits:

    grounding  random sample of final factual sentences → supported? material error?
               → independent support rate, material errors per 100, agreement with the judge
    coverage   random 2-minute caption clips → core ideas taught there → are they in the book?
               → share of core ideas missed
    quality    each chapter scored 1–5 on clarity, flow, book voice, definitions first,
               concision, reader fit, title fit → averages + suggested improvements
Results are checked against `evaluation.thresholds`; failures are release blockers.
"""
import random
from pathlib import Path
from ..core import digest
from .. import runner
from .segment import format_lines
from .verify import LineIndex

PROMPTS = {k: Path(f"prompts/eval_{k}.txt") for k in ("grounding", "coverage", "quality")}
CRITERIA = ["clarity", "flow", "book_voice", "definitions_first", "concision", "reader_fit", "title_fit"]
BATCH = 15


def final_units(root, outline, decisions):
    from ..review import apply_decisions
    units = {s["id"]: runner.load(root, "verify", s["id"]) for c in outline["chapters"] for s in c["sections"]}
    return {k: apply_decisions(v, decisions) for k, v in units.items() if v}


def _validate_grounding(obj, n):
    verdicts = obj.get("verdicts")
    if not isinstance(verdicts, list):
        return ["'verdicts' must be a list"]
    ids = {v.get("id") for v in verdicts}
    errors = [f"missing verdict S{k}" for k in range(1, n + 1) if f"S{k}" not in ids]
    errors += [f"{v.get('id')}: bad verdict" for v in verdicts if v.get("verdict") not in ("supported", "partial", "unsupported")]
    return errors


def audit_grounding(gateway, sentences, index, seed):
    out = []
    for start in range(0, len(sentences), BATCH):
        batch = sentences[start:start + BATCH]
        blocks = []
        for n, s in enumerate(batch, 1):
            cited = [index.lines[c] for c in s["cites"] if c in index.lines]
            context = [x for x in index.context(s["cites"]) if x["id"] not in set(s["cites"])]
            blocks.append(f"S{n}: {s['text']}\n  cited:\n{format_lines(cited, True)}\n  context:\n{format_lines(context, True)}")
        result = gateway.call_json("evaluator", [{"role": "system", "content": PROMPTS["grounding"].read_text()},
                                                 {"role": "user", "content": "\n\n".join(blocks)}],
                                   stage="evaluate", input_id=f"grounding#{seed}#{start // BATCH}",
                                   validate=lambda o, k=len(batch): _validate_grounding(o, k), max_completion_tokens=16000)
        by_id = {v["id"]: v for v in result["parsed"]["verdicts"]}
        out += [{"sentence_id": s["id"], "text": s["text"], **{k: by_id[f"S{n}"].get(k) for k in ("verdict", "material", "reason")}}
                for n, s in enumerate(batch, 1)]
    return out


def _validate_coverage(obj):
    ideas = obj.get("ideas")
    if not isinstance(ideas, list):
        return ["'ideas' must be a list"]
    return [f"idea {n}: needs idea, core and in_book" for n, i in enumerate(ideas)
            if not str(i.get("idea", "")).strip() or not isinstance(i.get("core"), bool) or not isinstance(i.get("in_book"), bool)]


def audit_coverage(gateway, segments, units, clips, seconds, rng):
    sentences = [s for u in units.values() for p in u["paragraphs"] for s in p["sentences"] if s["type"] == "F"]
    lines = {x["id"]: x for seg in segments.values() for x in seg["lines"]}
    results = []
    videos = [v for v, seg in segments.items() if seg["lines"]]
    for n in range(clips):
        video = rng.choice(videos)
        seg_lines = segments[video]["lines"]
        end_time = seg_lines[-1]["start"]
        start = rng.uniform(0, max(0.0, end_time - seconds))
        clip = [x for x in seg_lines if start <= x["start"] < start + seconds]
        related = [s for s in sentences if any(c in lines and lines[c]["video_id"] == video
                                               and start - 30 <= lines[c]["start"] < start + seconds + 30 for c in s["cites"])]
        book = "\n".join(f"- {s['text']}" for s in related) or "(no book sentences draw on this part of the lecture)"
        result = gateway.call_json("evaluator", [{"role": "system", "content": PROMPTS["coverage"].read_text()},
                                                 {"role": "user", "content": f"Lecture excerpt:\n{format_lines(clip, True)}\n\nBook sentences:\n{book}"}],
                                   stage="evaluate", input_id=f"coverage#{video}@{int(start)}",
                                   validate=_validate_coverage, max_completion_tokens=8000)
        ideas = result["parsed"]["ideas"]
        results.append({"video_id": video, "start": int(start), "end": int(start + seconds), "ideas": ideas,
                        "core": sum(i["core"] for i in ideas), "core_missed": sum(i["core"] and not i["in_book"] for i in ideas)})
    return results


def _validate_quality(obj):
    scores = obj.get("scores") or {}
    errors = [f"missing score {c}" for c in CRITERIA if c not in scores]
    errors += [f"{c}: score must be 1-5" for c in CRITERIA if c in scores and scores[c].get("score") not in (1, 2, 3, 4, 5)]
    return errors


def audit_quality(gateway, outline, units, reader_text):
    results = []
    for chapter in outline["chapters"]:
        parts = [f"# {chapter['title']}"]
        for section in chapter["sections"]:
            unit = units.get(section["id"])
            if unit:
                parts.append(f"## {section['title']}")
                parts += [" ".join(s["text"] for s in p["sentences"]) for p in unit["paragraphs"]]
        result = gateway.call_json("evaluator", [{"role": "system", "content": PROMPTS["quality"].read_text()},
                                                 {"role": "user", "content": f"Reader profile:\n{reader_text}\n\nChapter:\n" + "\n\n".join(parts)}],
                                   stage="evaluate", input_id=f"quality#{chapter['id']}",
                                   validate=_validate_quality, max_completion_tokens=8000)
        parsed = result["parsed"]
        results.append({"chapter": chapter["id"], "title": chapter["title"],
                        "scores": {c: parsed["scores"][c] for c in CRITERIA},
                        "average": round(sum(parsed["scores"][c]["score"] for c in CRITERIA) / len(CRITERIA), 2),
                        "improvements": parsed.get("improvements", [])[:3]})
    return results


def evaluate(gateway, config, root, outline, decisions, reader_text, seed=0):
    settings = config.get("evaluation", {})
    rng = random.Random(f"evaluator:{seed}")
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    index = LineIndex(segments)
    units = final_units(root, outline, decisions)
    factual = [s for u in units.values() for p in u["paragraphs"] for s in p["sentences"] if s["type"] == "F"]
    sample = rng.sample(factual, min(settings.get("grounding_sample", 60), len(factual)))
    grounding = audit_grounding(gateway, sample, index, seed)
    coverage = audit_coverage(gateway, segments, units, settings.get("coverage_clips", 20),
                              settings.get("clip_seconds", 120), rng)
    quality = audit_quality(gateway, outline, units, reader_text)

    judge = {sid: v for u in units.values() for sid, v in u["verdicts"].items()}
    agree = [g for g in grounding if g["sentence_id"] in judge]
    supported = sum(g["verdict"] == "supported" for g in grounding)
    material = sum(bool(g["material"]) and g["verdict"] != "supported" for g in grounding)
    core = sum(c["core"] for c in coverage)
    missed = sum(c["core_missed"] for c in coverage)
    metrics = {
        "grounding_sample": len(grounding),
        "independent_support": round(supported / len(grounding), 4) if grounding else None,
        "material_errors_per_100": round(100 * material / len(grounding), 2) if grounding else None,
        "agreement_with_judge": round(sum((g["verdict"] == "supported") == (judge[g["sentence_id"]]["verdict"] == "supported")
                                          for g in agree) / len(agree), 4) if agree else None,
        "coverage_clips": len(coverage), "core_ideas_seen": core,
        "core_ideas_missed": round(missed / core, 4) if core else None,
        "quality_average": round(sum(q["average"] for q in quality) / len(quality), 2) if quality else None,
    }
    t = settings.get("thresholds", {})
    checks = {
        "independent_support": metrics["independent_support"] is not None and metrics["independent_support"] >= t.get("independent_support", 0.95),
        "material_errors_per_100": metrics["material_errors_per_100"] is not None and metrics["material_errors_per_100"] <= t.get("material_errors_per_100", 2),
        "core_ideas_missed": metrics["core_ideas_missed"] is not None and metrics["core_ideas_missed"] <= t.get("core_ideas_missed", 0.1),
        "quality_average": metrics["quality_average"] is not None and metrics["quality_average"] >= t.get("quality_min_average", 3.5),
    }
    return {"metrics": metrics, "checks": checks, "passed": all(checks.values()),
            "grounding": grounding, "coverage": coverage, "quality": quality}


def run_evaluator(root, gateway, config, seed=0):
    from ..review import load_decisions
    from .reader import reader_for_prompts
    outline = runner.load(root, "outline", "book")
    if outline is None:
        raise ValueError("No outline; run the pipeline first")
    decisions = load_decisions(root)
    reader_text = reader_for_prompts(root, config)
    inputs = {"verify": {s["id"]: runner.output_hash(root, "verify", s["id"]) for c in outline["chapters"] for s in c["sections"]},
              "decisions": digest(decisions), "reader": digest(reader_text), "settings": config.get("evaluation"),
              "prompts": {k: digest(p.read_text()) for k, p in PROMPTS.items()}, "seed": seed, "v": 1}
    return runner.run(root, "evaluation", "book", inputs,
                      lambda: evaluate(gateway, config, root, outline, decisions, reader_text, seed))
