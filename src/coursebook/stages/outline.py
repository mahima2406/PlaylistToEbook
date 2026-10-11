"""Stage 4: teaching points from a group of lectures -> concept chapters.

Points are sent as short references (P1..Pn) to keep prompts small and IDs exact.
Coverage contract: every point is placed exactly once or dropped with a reason.
A point the model forgets (up to MAX_AUTO_PLACE of them) is placed next to its
nearest placed neighbour from the same lecture and listed as `auto_placed`; more
than that means the outline failed and the run stops.
The outline is approved by a person (approvals/outline.json, tied to its hash);
without a current approval, renders are marked DRAFT and release is blocked.
"""
import time
from pathlib import Path
from ..core import digest, read, write
from .. import runner

PROMPT = Path("prompts/outline.txt")
PLAN_PROMPT = Path("prompts/plan.txt")
SINGLE_CALL_LECTURES = 4    # above this, plan chapters first, then outline each chapter
CORE_POINTS_IN_PLAN = 12


MAX_AUTO_PLACE = 0.05


def validate_outline(obj, refs, core_refs, allow_missing=0):
    errors, seen = [], {}
    chapters = obj.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ["'chapters' must be a non-empty list"]
    for c, chapter in enumerate(chapters):
        if not str(chapter.get("title", "")).strip():
            errors.append(f"chapter {c}: missing title")
        for s, section in enumerate(chapter.get("sections") or []):
            if not str(section.get("title", "")).strip():
                errors.append(f"chapter {c} section {s}: missing title")
            for ref in section.get("points") or []:
                if ref not in refs:
                    errors.append(f"unknown point {ref}")
                elif ref in seen:
                    errors.append(f"{ref} placed twice")
                seen[ref] = "placed"
        if not chapter.get("sections"):
            errors.append(f"chapter {c}: no sections")
    for drop in obj.get("dropped") or []:
        ref = drop.get("point")
        if ref not in refs:
            errors.append(f"unknown dropped point {ref}")
        elif ref in seen:
            errors.append(f"{ref} both placed and dropped")
        elif not str(drop.get("reason", "")).strip():
            errors.append(f"{ref}: dropped without a reason")
        seen[ref] = "dropped"
    missing = [r for r in refs if r not in seen]
    if len(missing) > allow_missing:
        errors.append(f"points not accounted for: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    return errors


def outline_points(gateway, config, entries, points, target=None, item=None):
    refs = {f"P{n + 1}": p for n, p in enumerate(points)}
    core = {r for r, p in refs.items() if p["importance"] == 3}
    lectures = "\n".join(f"Lecture {e['playlist_index']}: {e['title']}" for e in entries)
    listing = "\n".join(f"{r} | L{p['lecture']} | {p['kind']} | {p['importance']} | {p['text']}" for r, p in refs.items())
    target = target or config.get("chapters_target") or max(2, min(12, round(len(entries) / 4)))
    messages = [{"role": "system", "content": PROMPT.read_text().replace("{chapters}", str(target))},
                {"role": "user", "content": f"Reader: {config['reader']}\n\nLectures:\n{lectures}\n\nPoints:\n{listing}"}]
    allowed_missing = int(len(refs) * MAX_AUTO_PLACE)
    result = gateway.call_json("writer", messages, stage="outline", input_id=item or "+".join(e["video_id"] for e in entries),
                               validate=lambda o: validate_outline(o, refs, core, allowed_missing), max_completion_tokens=32000)
    parsed = result["parsed"]
    auto_placed = place_missing(parsed, list(refs))
    chapters = []
    for c, chapter in enumerate(parsed["chapters"], 1):
        sections = [{"id": f"ch{c:02d}.s{s:02d}", "title": section["title"],
                     "point_ids": [refs[r]["id"] for r in section["points"]]}
                    for s, section in enumerate(chapter["sections"], 1)]
        chapters.append({"id": f"ch{c:02d}", "title": chapter["title"], "summary": chapter.get("summary", ""),
                         "sections": sections})
    dropped = [{"point_id": refs[d["point"]]["id"], "reason": d["reason"]} for d in parsed.get("dropped", [])]
    return {"lectures": [e["video_id"] for e in entries], "chapters": chapters, "dropped": dropped,
            "auto_placed": [refs[r]["id"] for r in auto_placed]}


def place_missing(parsed, order):
    """Insert forgotten refs after their nearest placed neighbour (refs are in lecture order)."""
    location = {}
    for chapter in parsed["chapters"]:
        for section in chapter["sections"]:
            for ref in section["points"]:
                location[ref] = section
    dropped = {d["point"] for d in parsed.get("dropped", [])}
    missing = [r for r in order if r not in location and r not in dropped]
    for ref in missing:
        n = order.index(ref)
        neighbours = order[n - 1::-1] if n else []
        neighbours += order[n + 1:]
        anchor = next((r for r in neighbours if r in location), None)
        section = location[anchor] if anchor else parsed["chapters"][0]["sections"][0]
        position = section["points"].index(anchor) + 1 if anchor in section["points"] else len(section["points"])
        section["points"].insert(position, ref)
        location[ref] = section
    return missing


def validate_plan(obj, indexes):
    chapters = obj.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ["'chapters' must be a non-empty list"]
    flat = [n for c in chapters for n in (c.get("lectures") or [])]
    errors = [f"chapter {k}: missing title" for k, c in enumerate(chapters) if not str(c.get("title", "")).strip()]
    errors += [f"chapter {k}: no lectures" for k, c in enumerate(chapters) if not c.get("lectures")]
    if flat != indexes:
        errors.append(f"lectures must appear exactly once, in course order: expected {indexes}, got {flat}")
    return errors


def plan_chapters(gateway, config, entries, points_by_video):
    """Group consecutive lectures into chapters (large books)."""
    target = config.get("chapters_target") or max(2, min(12, round(len(entries) / 4)))
    blocks = []
    for e in entries:
        core = [p["text"] for p in points_by_video[e["video_id"]] if p["importance"] == 3][:CORE_POINTS_IN_PLAN]
        blocks.append(f"Lecture {e['playlist_index']}: {e['title']}\n" + "\n".join(f"  - {t}" for t in core))
    messages = [{"role": "system", "content": PLAN_PROMPT.read_text().replace("{chapters}", str(target))},
                {"role": "user", "content": f"Reader: {config['reader']}\n\n" + "\n\n".join(blocks)}]
    indexes = [e["playlist_index"] for e in entries]
    return gateway.call_json("writer", messages, stage="plan", input_id="book",
                             validate=lambda o: validate_plan(o, indexes))["parsed"]["chapters"]


def outline_book(gateway, config, entries, points_by_video):
    if len(entries) <= SINGLE_CALL_LECTURES:
        return outline_points(gateway, config, entries, [p for e in entries for p in points_by_video[e["video_id"]]])
    by_index = {e["playlist_index"]: e for e in entries}
    plan = plan_chapters(gateway, config, entries, points_by_video)

    def one(planned):
        group = [by_index[n] for n in planned["lectures"]]
        part = outline_points(gateway, config, group, [p for e in group for p in points_by_video[e["video_id"]]],
                              target=1, item="chapter:" + "+".join(str(n) for n in planned["lectures"]))
        return part, planned

    chapters, dropped, auto_placed = [], [], []
    for part, planned in gateway.map(one, plan, workers=config.get("llm", {}).get("concurrency", 4)):
        auto_placed += part["auto_placed"]
        for chapter in part["chapters"]:
            n = len(chapters) + 1
            chapters.append({"id": f"ch{n:02d}", "title": chapter["title"] if len(part["chapters"]) > 1 else planned["title"],
                             "summary": chapter["summary"] if len(part["chapters"]) > 1 else planned["summary"],
                             "sections": [{**s, "id": f"ch{n:02d}.s{k:02d}"} for k, s in enumerate(chapter["sections"], 1)]})
        dropped += part["dropped"]
    return {"lectures": [e["video_id"] for e in entries], "chapters": chapters, "dropped": dropped,
            "auto_placed": auto_placed}


def run_outline(root, gateway, config, entries):
    points_by_video, upstream = {}, {}
    for entry in entries:
        extracted = runner.load(root, "extract", entry["video_id"])
        if extracted is None:
            raise ValueError(f"{entry['video_id']}: run extract first")
        points_by_video[entry["video_id"]] = extracted["points"]
        upstream[entry["video_id"]] = runner.output_hash(root, "extract", entry["video_id"])
    inputs = {"extract": upstream, "prompt": digest(PROMPT.read_text()), "reader": config["reader"],
              "chapters_target": config.get("chapters_target"), "v": 1}
    if len(entries) > SINGLE_CALL_LECTURES:
        inputs["plan_prompt"] = digest(PLAN_PROMPT.read_text())
    return runner.run(root, "outline", "book", inputs, lambda: outline_book(gateway, config, entries, points_by_video))


def approve(root, approver):
    outline = runner.load(root, "outline", "book")
    if outline is None:
        raise ValueError("No outline to approve; run outline first")
    record = {"outline_hash": runner.output_hash(root, "outline", "book"), "approved_by": approver,
              "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write(Path(root) / "approvals" / "outline.json", record)
    return record


def approval_is_current(root):
    path = Path(root) / "approvals" / "outline.json"
    return path.exists() and read(path).get("outline_hash") == runner.output_hash(root, "outline", "book")
