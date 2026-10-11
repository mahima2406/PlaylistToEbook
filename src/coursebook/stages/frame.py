"""Framing: book introduction, chapter openers + "At a glance", chapter takeaways.

    outline ──> intro      (sources: the configured intro lecture, e.g. L01, + outline)
            ──> opener     (per chapter: core points' caption lines + outline)
    verify  ──> takeaways  (per chapter: restates fact-checked sentences only)
Every piece is judged like section prose (verify_section): F sentences against
their cited lines, R (roadmap) sentences against the outline, C must carry no claim.
"""
from pathlib import Path
from ..core import digest, read
from .. import runner
from .segment import format_lines, run_segment
from .verify import LineIndex, verify_section, JUDGE_PROMPT, REWRITE_PROMPT
from .write import validate_section, source_lines, assign_ids

INTRO_PROMPT = Path("prompts/intro.txt")
OPENER_PROMPT = Path("prompts/opener.txt")
TAKEAWAYS_PROMPT = Path("prompts/takeaways.txt")
MAX_CORE_POINTS = 25


def outline_text(outline):
    return "\n".join(f"Chapter {n}: {c['title']} — {c['summary']}\n  Sections: "
                     + "; ".join(s["title"] for s in c["sections"])
                     for n, c in enumerate(outline["chapters"], 1))


def intro_entry(root, config):
    """Manifest entry for the configured intro lecture, if its captions were captured."""
    index = config.get("frame", {}).get("intro_lecture", 1)
    if not index:
        return None
    for entry in read(Path(root) / "manifest.json")["entries"]:
        if entry["playlist_index"] == index and (Path(root) / "evidence" / f"{entry['video_id']}.json").exists():
            return entry
    return None


def _context(root, config, outline):
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    entry = intro_entry(root, config)
    if entry and entry["video_id"] not in segments:
        segments[entry["video_id"]] = run_segment(root, entry["video_id"])
    return segments, LineIndex(segments), entry


def _verify(gateway, unit_id, paragraphs, segments, index, cutoff, outline_txt):
    return verify_section(gateway, {"section_id": unit_id, "paragraphs": paragraphs},
                          segments, index, cutoff, outline_txt)


def _common_inputs(config, outline_hash):
    return {"outline": outline_hash, "title": config["title"], "reader": config["reader"],
            "judge": digest(JUDGE_PROMPT.read_text()), "rewrite": digest(REWRITE_PROMPT.read_text()),
            "cutoff": config.get("verify", {}).get("confidence_cutoff", 0.7), "v": 2}


def write_intro(gateway, config, outline, segments, index, entry, cutoff):
    lines = segments[entry["video_id"]]["lines"] if entry else []
    allowed = {x["id"] for x in lines}
    source = f"Caption lines of the introductory lecture:\n{format_lines(lines, full_ids=True)}" if lines \
        else "No introductory lecture is available; write only roadmap and connective sentences."
    messages = [{"role": "system", "content": INTRO_PROMPT.read_text()},
                {"role": "user", "content": f"Book: {config['title']}\nReader: {config['reader']}\n\n"
                                            f"Outline:\n{outline_text(outline)}\n\n{source}"}]
    result = gateway.call_json("writer", messages, stage="intro", input_id="book", max_completion_tokens=16000,
                               validate=lambda o: validate_section(o, allowed, roadmap=True))
    paragraphs = assign_ids(result["parsed"]["paragraphs"], "intro")
    return _verify(gateway, "intro", paragraphs, segments, index, cutoff, outline_text(outline))


def validate_opener(obj, allowed):
    errors = validate_section(obj.get("opener") or {}, allowed, roadmap=True)
    glance = obj.get("at_a_glance")
    if not isinstance(glance, list) or not 3 <= len(glance) <= 6:
        errors.append("at_a_glance must have 3-5 items")
    else:
        errors += validate_section({"paragraphs": [{"sentences": [g]} for g in glance]}, allowed)
        errors += [f"at_a_glance item {n} must be F" for n, g in enumerate(glance) if g.get("type") != "F"]
    return errors


def write_opener(gateway, config, outline, chapter, points, segments, index, cutoff):
    n = outline["chapters"].index(chapter)
    previous = outline["chapters"][n - 1] if n else None
    following = outline["chapters"][n + 1] if n + 1 < len(outline["chapters"]) else None
    core = [points[i] for s in chapter["sections"] for i in s["point_ids"] if points[i]["importance"] == 3][:MAX_CORE_POINTS]
    lines = source_lines(segments, [i for p in core for i in p["line_ids"]])
    allowed = {x["id"] for x in lines}
    context = (f"Book: {config['title']}\nReader: {config['reader']}\n"
               f"This chapter: {chapter['title']} — {chapter['summary']}\n"
               f"Sections: " + "; ".join(s["title"] for s in chapter["sections"]) + "\n"
               f"Previous chapter: {previous['title'] + ' — ' + previous['summary'] if previous else '(this is the first chapter)'}\n"
               f"Next chapter: {following['title'] if following else '(this is the last chapter)'}")
    core_text = "\n".join(f"- {p['text']}" for p in core)
    messages = [{"role": "system", "content": OPENER_PROMPT.read_text()},
                {"role": "user", "content": f"{context}\n\nCore teaching points:\n{core_text}\n\n"
                                            f"Source caption lines:\n{format_lines(lines, full_ids=True)}"}]
    result = gateway.call_json("writer", messages, stage="opener", input_id=chapter["id"], max_completion_tokens=16000,
                               validate=lambda o: validate_opener(o, allowed))
    parsed = result["parsed"]
    opener = assign_ids(parsed["opener"]["paragraphs"], f"{chapter['id']}.open")
    glance = assign_ids([{"sentences": [g]} for g in parsed["at_a_glance"]], f"{chapter['id']}.glance")
    checked = _verify(gateway, f"{chapter['id']}.open", opener + glance, segments, index, cutoff, outline_text(outline))
    return {**checked, "opener": [p for p in checked["paragraphs"] if ".open." in p["id"]],
            "at_a_glance": [p for p in checked["paragraphs"] if ".glance." in p["id"]]}


def validate_takeaways(obj, allowed):
    items = obj.get("takeaways")
    if not isinstance(items, list) or not 3 <= len(items) <= 8:
        return ["takeaways must have 5-7 items"]
    errors = validate_section({"paragraphs": [{"sentences": [t]} for t in items]}, allowed)
    return errors + [f"takeaway {n} must be F" for n, t in enumerate(items) if t.get("type") != "F"]


def write_takeaways(gateway, chapter, verified, segments, index, cutoff):
    facts = [s for v in verified for p in v["paragraphs"] for s in p["sentences"]
             if s["type"] == "F" and v["verdicts"].get(s["id"], {}).get("verdict") == "supported"]
    allowed = {c for s in facts for c in s["cites"]}
    listing = "\n".join(f"{s['id']} | cites: {', '.join(s['cites'])} | {s['text']}" for s in facts)
    messages = [{"role": "system", "content": TAKEAWAYS_PROMPT.read_text()},
                {"role": "user", "content": f"Chapter: {chapter['title']}\n\nFact-checked sentences:\n{listing}"}]
    result = gateway.call_json("writer", messages, stage="takeaways", input_id=chapter["id"], max_completion_tokens=16000,
                               validate=lambda o: validate_takeaways(o, allowed))
    items = assign_ids([{"sentences": [t]} for t in result["parsed"]["takeaways"]], f"{chapter['id']}.take")
    return _verify(gateway, f"{chapter['id']}.take", items, segments, index, cutoff, None)


def run_frame(root, gateway, config, outline, workers=4):
    """Intro + chapter openers (before the sections are written)."""
    segments, index, entry = _context(root, config, outline)
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)
    points = {p["id"]: p for v in outline["lectures"] for p in runner.load(root, "extract", v)["points"]}
    common = _common_inputs(config, runner.output_hash(root, "outline", "book"))
    intro_inputs = {**common, "prompt": digest(INTRO_PROMPT.read_text()),
                    "intro": runner.output_hash(root, "segment", entry["video_id"]) if entry else None}
    jobs = [("intro", intro_inputs, lambda: write_intro(gateway, config, outline, segments, index, entry, cutoff))]
    for chapter in outline["chapters"]:
        inputs = {**common, "prompt": digest(OPENER_PROMPT.read_text()), "chapter": chapter["id"],
                  "extract": {v: runner.output_hash(root, "extract", v) for v in outline["lectures"]}}
        jobs.append((chapter["id"], inputs,
                     lambda c=chapter: write_opener(gateway, config, outline, c, points, segments, index, cutoff)))
    return gateway.map(lambda job: runner.run(root, "frame", job[0], job[1], job[2]), jobs, workers=workers)


def run_takeaways(root, gateway, config, outline, workers=4):
    segments, index, _ = _context(root, config, outline)
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)
    common = _common_inputs(config, runner.output_hash(root, "outline", "book"))

    def job(chapter):
        verified = [runner.load(root, "verify", s["id"]) for s in chapter["sections"]]
        inputs = {**common, "prompt": digest(TAKEAWAYS_PROMPT.read_text()),
                  "verify": [runner.output_hash(root, "verify", s["id"]) for s in chapter["sections"]]}
        return runner.run(root, "takeaways", chapter["id"], inputs,
                          lambda: write_takeaways(gateway, chapter, verified, segments, index, cutoff))

    return gateway.map(job, outline["chapters"], workers=workers)
