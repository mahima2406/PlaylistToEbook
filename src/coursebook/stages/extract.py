"""Stage 3: each ~15 min chunk -> teaching points with caption-line citations.

A truncated answer splits the chunk at a window boundary and retries both halves.
The per-lecture inventory counts points per chunk and flags chunks with none,
so missing content is visible rather than silent.
"""
from pathlib import Path
from ..core import digest
from ..llm import TruncatedOutput
from .. import runner
from .segment import format_lines, lines_of

KINDS = {"definition", "claim", "procedure", "code", "equation", "analogy", "visual_ref"}
PROMPT = Path("prompts/extract.txt")


def validate_points(obj, allowed_keys):
    errors = []
    points = obj.get("points")
    if not isinstance(points, list):
        return ["'points' must be a list"]
    for n, point in enumerate(points):
        where = f"point {n}"
        if point.get("kind") not in KINDS:
            errors.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if point.get("importance") not in (1, 2, 3):
            errors.append(f"{where}: importance must be 1, 2 or 3")
        if not str(point.get("text", "")).strip():
            errors.append(f"{where}: empty text")
        lines = point.get("lines")
        if not lines or not isinstance(lines, list):
            errors.append(f"{where}: lines must be a non-empty list")
        elif not set(map(str, lines)) <= allowed_keys:
            errors.append(f"{where}: unknown line IDs {sorted(set(map(str, lines)) - allowed_keys)[:5]}")
    return errors


def _extract_windows(gateway, entry, segmented, window_ids, prompt, depth=0):
    lines = lines_of(segmented, window_ids)
    allowed = {x["key"] for x in lines}
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": f"Lecture {entry['playlist_index']}: {entry['title']}\n\n"
                                            + format_lines(lines)}]
    item = f"{entry['video_id']}@{lines[0]['key']}"
    try:
        result = gateway.call_json("writer", messages, stage="extract", input_id=item,
                                   validate=lambda o: validate_points(o, allowed))
    except TruncatedOutput:
        if depth >= 2 or len(window_ids) < 2:
            raise
        half = len(window_ids) // 2
        return (_extract_windows(gateway, entry, segmented, window_ids[:half], prompt, depth + 1)
                + _extract_windows(gateway, entry, segmented, window_ids[half:], prompt, depth + 1))
    return result["parsed"]["points"]


def extract_lecture(gateway, entry, segmented, workers=4):
    prompt = PROMPT.read_text()
    per_chunk = gateway.map(lambda chunk: _extract_windows(gateway, entry, segmented, chunk["window_ids"], prompt),
                            segmented["chunks"], workers=workers)
    vid = entry["video_id"]
    points, inventory = [], []
    for chunk, chunk_points in zip(segmented["chunks"], per_chunk):
        for point in chunk_points:
            points.append({"id": f"{vid}:p{len(points) + 1:03d}", "video_id": vid,
                           "lecture": entry["playlist_index"], "kind": point["kind"],
                           "importance": point["importance"], "text": " ".join(point["text"].split()),
                           "line_ids": [f"{vid}@{k}" for k in map(str, point["lines"])]})
        inventory.append({"chunk": chunk["id"], "start": chunk["start"], "end": chunk["end"],
                          "points": len(chunk_points),
                          "core_points": sum(1 for p in chunk_points if p["importance"] == 3),
                          "flag": "no points extracted" if not chunk_points else None})
    return {"video_id": vid, "points": points, "inventory": inventory}


def run_extract(root, gateway, entry, workers=4):
    vid = entry["video_id"]
    segmented = runner.load(root, "segment", vid)
    if segmented is None:
        raise ValueError(f"{vid}: run segment first")
    inputs = {"segment": runner.output_hash(root, "segment", vid), "prompt": digest(PROMPT.read_text()),
              "title": entry["title"], "index": entry["playlist_index"], "v": 1}
    return runner.run(root, "extract", vid, inputs, lambda: extract_lecture(gateway, entry, segmented, workers))
