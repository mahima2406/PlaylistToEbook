"""Stage 4: teaching points from a group of lectures -> concept chapters.

Points are sent as short references (P1..Pn) to keep prompts small and IDs exact.
Coverage contract: every point is placed exactly once or dropped with a reason.
The outline is approved by a person (approvals/outline.json, tied to its hash);
without a current approval, renders are marked DRAFT and release is blocked.
"""
import time
from pathlib import Path
from ..core import digest, read, write
from .. import runner

PROMPT = Path("prompts/outline.txt")


def validate_outline(obj, refs, core_refs):
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
    if missing:
        errors.append(f"points not accounted for: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    return errors


def outline_points(gateway, config, entries, points):
    refs = {f"P{n + 1}": p for n, p in enumerate(points)}
    core = {r for r, p in refs.items() if p["importance"] == 3}
    lectures = "\n".join(f"Lecture {e['playlist_index']}: {e['title']}" for e in entries)
    listing = "\n".join(f"{r} | L{p['lecture']} | {p['kind']} | {p['importance']} | {p['text']}" for r, p in refs.items())
    target = config.get("chapters_target") or max(2, min(12, round(len(entries) / 4)))
    messages = [{"role": "system", "content": PROMPT.read_text().replace("{chapters}", str(target))},
                {"role": "user", "content": f"Reader: {config['reader']}\n\nLectures:\n{lectures}\n\nPoints:\n{listing}"}]
    result = gateway.call_json("writer", messages, stage="outline", input_id="+".join(e["video_id"] for e in entries),
                               validate=lambda o: validate_outline(o, refs, core), max_completion_tokens=32000)
    parsed = result["parsed"]
    chapters = []
    for c, chapter in enumerate(parsed["chapters"], 1):
        sections = [{"id": f"ch{c:02d}.s{s:02d}", "title": section["title"],
                     "point_ids": [refs[r]["id"] for r in section["points"]]}
                    for s, section in enumerate(chapter["sections"], 1)]
        chapters.append({"id": f"ch{c:02d}", "title": chapter["title"], "summary": chapter.get("summary", ""),
                         "sections": sections})
    dropped = [{"point_id": refs[d["point"]]["id"], "reason": d["reason"]} for d in parsed.get("dropped", [])]
    return {"lectures": [e["video_id"] for e in entries], "chapters": chapters, "dropped": dropped}


def run_outline(root, gateway, config, entries):
    points, upstream = [], {}
    for entry in entries:
        extracted = runner.load(root, "extract", entry["video_id"])
        if extracted is None:
            raise ValueError(f"{entry['video_id']}: run extract first")
        points += extracted["points"]
        upstream[entry["video_id"]] = runner.output_hash(root, "extract", entry["video_id"])
    inputs = {"extract": upstream, "prompt": digest(PROMPT.read_text()), "reader": config["reader"],
              "chapters_target": config.get("chapters_target"), "v": 1}
    return runner.run(root, "outline", "book", inputs, lambda: outline_points(gateway, config, entries, points))


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
