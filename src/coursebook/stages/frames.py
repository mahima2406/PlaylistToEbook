"""Whiteboard → figure: read the screen at moments the lecturer points to, redraw, check.

    visual_ref points (importance ≥ 2, placed in a section) ── up to N per lecture
        → stream URL (yt-dlp) → one frame at that second (ffmpeg seeks the stream; no full download)
        → vision model: diagram (Mermaid) | equation (LaTeX) | none, + the claims it expresses
        → independent check (judge model) with the image: every claim visible in the frame, and
          none contradicted by what the lecturer says within ±60 s (the frame itself is the evidence
          for screen-only content; speech may round or omit, but must not disagree)
        → kept: placed after the paragraph citing the nearest moment, captioned with lecture + time
Media access is opt-in (`--allow-media-download`); frames stay in data/media (never exported).
The image is part of the cached request, so replays need the same frame; the frame's hash is stored.
"""
import base64
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from ..core import digest
from .. import runner
from .segment import format_lines
from .diagrams import validate_mermaid

PROMPT = Path("prompts/frame.txt")
CHECK = Path("prompts/frame_check.txt")
WINDOW = 60
KINDS = {"diagram", "equation", "none"}


def stream_url(video_id):
    result = subprocess.run([sys.executable, "-m", "yt_dlp", "-g", "-f", "136/398/247/best[height<=720]", "--no-warnings",
                             f"https://www.youtube.com/watch?v={video_id}"], capture_output=True, text=True, timeout=180)
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f"{video_id}: no video stream available ({result.stderr.strip()[-200:]})")
    return result.stdout.strip().splitlines()[0]


def grab(url, seconds, target):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required to capture frames")
    subprocess.run([ffmpeg, "-loglevel", "error", "-ss", str(int(seconds)), "-i", url, "-frames:v", "1", "-q:v", "3",
                    "-y", str(target)], capture_output=True, timeout=120)
    return target if target.exists() and target.stat().st_size > 0 else None


def validate_frame(obj):
    if obj.get("kind") not in KINDS:
        return ["kind must be diagram, equation or none"]
    if obj["kind"] == "none":
        return []
    errors = []
    if obj["kind"] == "diagram" and validate_mermaid(obj.get("mermaid", "")):
        errors += ["mermaid: " + e for e in validate_mermaid(obj.get("mermaid", ""))]
    if obj["kind"] == "equation" and not str(obj.get("latex", "")).strip():
        errors.append("equation needs latex")
    if not isinstance(obj.get("claims"), list) or not obj["claims"]:
        errors.append("list the claims the figure expresses")
    if not str(obj.get("caption", "")).strip():
        errors.append("caption required")
    return errors


def nearby_lines(segment, seconds):
    return [x for x in segment["lines"] if abs(x["start"] - seconds) <= WINDOW]


def read_frame(gateway, point, frame, lines):
    image = base64.b64encode(frame.read_bytes()).decode()
    messages = [{"role": "system", "content": PROMPT.read_text()},
                {"role": "user", "content": [
                    {"type": "text", "text": f"What the lecturer says around this moment:\n{format_lines(lines, True)}\n\n"
                                             f"Teaching point: {point['text']}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}]}]
    return gateway.call_json("writer", messages, stage="frames", input_id=point["id"], max_completion_tokens=8000,
                             validate=validate_frame)["parsed"]


def _validate_check(obj, n):
    claims = obj.get("claims")
    if not isinstance(claims, list):
        return ["'claims' must be a list"]
    ids = {c.get("id") for c in claims}
    errors = [f"missing C{k}" for k in range(1, n + 1) if f"C{k}" not in ids]
    errors += [f"{c.get('id')}: speech must be consistent or contradicts" for c in claims
               if c.get("speech") not in ("consistent", "contradicts") or not isinstance(c.get("visible"), bool)]
    return errors


def check_frame(gateway, point, frame, lines, claims):
    image = base64.b64encode(frame.read_bytes()).decode()
    listing = "\n".join(f"C{k}: {t}" for k, t in enumerate(claims, 1))
    messages = [{"role": "system", "content": CHECK.read_text()},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Lecturer around this moment:\n{format_lines(lines, True)}\n\nClaims:\n{listing}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}]}]
    result = gateway.call_json("judge", messages, stage="frames", input_id=point["id"] + ":check", max_completion_tokens=8000,
                               validate=lambda o: _validate_check(o, len(claims)))["parsed"]["claims"]
    by_id = {c["id"]: c for c in result}
    return [{"text": t, **{k: by_id[f"C{n}"].get(k) for k in ("visible", "speech", "reason")}} for n, t in enumerate(claims, 1)]


def place(point, outline, units, lines_by_id):
    """Paragraph whose citations fall closest to the frame's moment (same lecture)."""
    t = float(point["line_ids"][0].split("@")[1].rstrip("abcdefghij"))
    best, best_d = None, None
    for c in outline["chapters"]:
        for s in c["sections"]:
            unit = units.get(s["id"])
            for p in (unit or {}).get("paragraphs", []):
                for sent in p["sentences"]:
                    for cite in sent["cites"]:
                        line = lines_by_id.get(cite)
                        if line and line["video_id"] == point["video_id"]:
                            d = abs(line["start"] - t)
                            if best_d is None or d < best_d:
                                best, best_d = (c["id"], p["id"]), d
    return best if best_d is not None and best_d <= 180 else None


def run_frames(root, gateway, config, outline, allow_media=False, workers=4):
    settings = config.get("frames", {})
    if not settings.get("enabled", True):
        return None
    if not allow_media:
        raise ValueError("Capturing frames reads the video stream; rerun with --allow-media-download "
                         "(frames stay in data/media and are never exported)")
    per_lecture = settings.get("per_lecture", 4)
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    units = {s["id"]: runner.load(root, "verify", s["id"]) for c in outline["chapters"] for s in c["sections"]}
    placed = {i for c in outline["chapters"] for s in c["sections"] for i in s["point_ids"]}
    media = Path(root) / "media" / "frames"
    media.mkdir(parents=True, exist_ok=True)
    jobs = []
    for v in outline["lectures"]:
        visual = [p for p in runner.load(root, "extract", v)["points"]
                  if p["kind"] == "visual_ref" and p["importance"] >= 2 and p["id"] in placed]
        jobs += visual[:per_lecture]
    urls = {}

    def job(point):
        seconds = float(point["line_ids"][0].split("@")[1].rstrip("abcdefghij")) + 2
        frame = media / f"{point['video_id']}_{int(seconds)}.jpg"
        if not frame.exists():
            if point["video_id"] not in urls:
                urls[point["video_id"]] = stream_url(point["video_id"])
            if not grab(urls[point["video_id"]], seconds, frame):
                return {"point_id": point["id"], "status": "no frame"}
        lines = nearby_lines(segments[point["video_id"]], seconds)
        frame_hash = hashlib.sha256(frame.read_bytes()).hexdigest()
        inputs = {"frame": frame_hash, "point": digest(point), "prompts": [digest(PROMPT.read_text()), digest(CHECK.read_text())], "v": 2}

        def compute():
            reading = read_frame(gateway, point, frame, lines)
            base = {"point_id": point["id"], "video_id": point["video_id"], "seconds": int(seconds), "frame_sha256": frame_hash}
            if reading["kind"] == "none":
                return {**base, "status": "nothing to redraw"}
            checked = check_frame(gateway, point, frame, lines, reading["claims"])
            hidden = [c for c in checked if not c["visible"]]
            contradicted = [c for c in checked if c["speech"] == "contradicts"]
            status = ("dropped (not visible in the frame)" if hidden else
                      "dropped (contradicts the lecturer)" if contradicted else "kept")
            return {**base, "status": status, "kind": reading["kind"],
                    "title": reading.get("title", ""), "caption": reading["caption"], "mermaid": reading.get("mermaid", ""),
                    "latex": reading.get("latex", ""), "claims": checked}

        return runner.run(root, "frames", point["id"], inputs, compute)

    results = gateway.map(job, jobs, workers=workers)
    lines_by_id = {x["id"]: x for seg in segments.values() for x in seg["lines"]}
    for r in results:
        if r.get("status") == "kept":
            point = next(p for p in jobs if p["id"] == r["point_id"])
            r["placement"] = place(point, outline, units, lines_by_id)
    summary = {"frames": results, "kept": sum(r.get("status") == "kept" for r in results),
               "looked_at": len(results)}
    runner.run(root, "frames_summary", "book", {"results": digest(results)}, lambda: summary)
    return summary
