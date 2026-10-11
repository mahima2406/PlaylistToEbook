"""Stage 2: caption lines -> line IDs -> ~30 s windows -> ~15 min chunks.

Line ID: `VIDEO@S` where S is whole seconds from the start (a letter suffix
separates two lines that start in the same second). Windows are `VIDEO@S-E`.
Prompts receive line-tagged text, one caption per line: `[S] text`, which is
about 9x smaller than the evidence JSON and keeps every line citable.
"""
from pathlib import Path
from ..core import digest, read, evidence_from_segments
from .. import runner

WINDOW_SECONDS = 30
CHUNK_SECONDS = 900


def make_lines(video_id, items):
    lines, seen = [], {}
    for item in items:
        second = int(item["start"])
        count = seen.get(second, 0)
        seen[second] = count + 1
        key = str(second) + ("" if count == 0 else chr(ord("a") + count))
        lines.append({"id": f"{video_id}@{key}", "key": key, "video_id": video_id,
                      "start": item["start"], "end": item["end"],
                      "text": " ".join(item["text"].split()), "evidence_id": item["id"],
                      "url": item["url"]})
    return lines


def group(lines, seconds):
    groups, current = [], []
    for line in lines:
        if current and line["start"] - current[0]["start"] >= seconds:
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)
    return groups


def segment_lecture(video_id, items):
    lines = make_lines(video_id, items)
    windows = []
    for group_lines in group(lines, WINDOW_SECONDS):
        start, end = int(group_lines[0]["start"]), int(group_lines[-1]["end"])
        windows.append({"id": f"{video_id}@{start}-{end}", "start": start, "end": end,
                        "line_ids": [x["id"] for x in group_lines]})
    chunks, current = [], []
    for window in windows:
        if current and window["start"] - current[0]["start"] >= CHUNK_SECONDS:
            chunks.append(current)
            current = []
        current.append(window)
    if current:
        chunks.append(current)
    chunk_records = [{"id": f"{video_id}@{c[0]['start']}-{c[-1]['end']}", "start": c[0]["start"],
                      "end": c[-1]["end"], "window_ids": [w["id"] for w in c]} for c in chunks]
    return {"video_id": video_id, "lines": lines, "windows": windows, "chunks": chunk_records}


def format_lines(lines, full_ids=False):
    """Prompt text: one caption line per row, tagged with its citable ID."""
    return "\n".join(f"[{x['id'] if full_ids else x['key']}] {x['text']}" for x in lines)


def lines_of(segmented, window_ids):
    by_window = {w["id"]: w for w in segmented["windows"]}
    by_line = {x["id"]: x for x in segmented["lines"]}
    return [by_line[i] for w in window_ids for i in by_window[w]["line_ids"]]


def run_segment(root, video_id):
    """Check the evidence packet against its raw snapshot, then segment it."""
    root = Path(root)
    packet = read(root / "evidence" / f"{video_id}.json")
    raw = read(root / packet["snapshot"])
    if digest(raw) != packet["source_hash"]:
        raise ValueError(f"{video_id}: caption snapshot changed")
    if packet["items"] != evidence_from_segments(video_id, raw["segments"]):
        raise ValueError(f"{video_id}: evidence differs from caption snapshot")
    return runner.run(root, "segment", video_id, {"source_hash": packet["source_hash"], "v": 1},
                      lambda: segment_lecture(video_id, packet["items"]))
