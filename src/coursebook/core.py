"""Versioned artifacts, acquisition and evidence. No credentials in artifacts."""
import hashlib
import json
import math
import re
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def snapshot(root, kind, payload):
    key = digest(payload)
    path = Path(root) / "raw" / kind / (key + ".json")
    if path.exists():
        if read(path) != payload:
            raise ValueError("Snapshot integrity error")
    else:
        write(path, payload)
    return str(path.relative_to(root))


def normalize_manifest(raw):
    entries = raw.get("entries") or []
    if not entries:
        raise ValueError("Playlist contains no entries")
    result = []
    for index, entry in enumerate(entries, 1):
        entry = entry or {}
        if entry.get("id") and not re.fullmatch(r"[A-Za-z0-9_-]+", entry["id"]):
            raise ValueError("Unsafe source identifier")
        result.append({"playlist_index": index, "video_id": entry.get("id"),
                       "title": entry.get("title") or "Unavailable video",
                       "duration": entry.get("duration"),
                       "access": "unprobed" if entry.get("id") else "unavailable",
                       "reuse_permission": "not_established"})
    return result


def inventory(root, config):
    import yt_dlp
    with yt_dlp.YoutubeDL({"extract_flat": "in_playlist", "quiet": True,
                           "socket_timeout": 25, "retries": 2}) as client:
        raw = client.extract_info(config["playlist_url"], download=False)
        raw = client.sanitize_info(raw)
    source = snapshot(root, "playlist", raw)
    manifest = {"playlist_url": config["playlist_url"], "title": raw.get("title"),
                "source_snapshot": source, "source_hash": digest(raw),
                "entries": normalize_manifest(raw)}
    write(Path(root) / "manifest.json", manifest)
    return manifest


def evidence_from_segments(video_id, segments):
    if not segments:
        raise ValueError("Empty transcript")
    evidence = []
    last = -1
    for n, segment in enumerate(segments):
        start, duration = segment["start"], segment["duration"]
        if (not isinstance(start, (int, float)) or not isinstance(duration, (int, float))
                or not math.isfinite(start) or not math.isfinite(duration)
                or start < 0 or duration < 0 or start < last):
            raise ValueError("Invalid or out-of-order caption timestamps")
        if not isinstance(segment["text"], str):
            raise ValueError("Caption text must be a string")
        last = start
        evidence.append({"id": f"{video_id}:{n:05d}", "video_id": video_id,
                         "start": start, "end": start + duration, "text": segment["text"],
                         "modality": "caption", "timestamp_status": "provider_supplied",
                         "url": f"https://www.youtube.com/watch?v={video_id}&t={int(start)}s"})
    return evidence


def capture(root, config, limit):
    from youtube_transcript_api import YouTubeTranscriptApi
    root = Path(root)
    manifest = read(root / "manifest.json")
    reports = []
    for entry in manifest["entries"][:limit]:
        video_id = entry["video_id"]
        if not video_id:
            reports.append({"playlist_index": entry["playlist_index"], "status": "blocked", "reason": "unavailable_video"})
            continue
        try:
            transcript = YouTubeTranscriptApi().fetch(video_id, languages=config["languages"])
            raw = {"video_id": video_id, "language": transcript.language_code,
                   "is_generated": transcript.is_generated, "segments": transcript.to_raw_data()}
            evidence = evidence_from_segments(video_id, raw["segments"])
            path = snapshot(root, "captions", raw)
            write(root / "evidence" / f"{video_id}.json",
                  {"snapshot": path, "source_hash": digest(raw), "items": evidence,
                   "visual_review": "missing", "human_source_review": "pending"})
            reports.append({"video_id": video_id, "status": "captured", "segments": len(evidence)})
        except Exception as exc:
            # Do not serialize exception text: upstream URLs may contain tokens.
            reports.append({"video_id": video_id, "status": "blocked", "error_type": type(exc).__name__})
    write(root / "capture_report.json", reports)
    return reports


def validate_chapter(chapter, evidence):
    ids = {item["id"] for item in evidence}
    errors = []
    seen = set()
    if not chapter.get("sections"):
        errors.append("No sections")
    for section in chapter.get("sections", []):
        if not section.get("paragraphs"):
            errors.append("Empty section")
        for paragraph in section.get("paragraphs", []):
            pid = paragraph.get("id")
            if not pid or pid in seen:
                errors.append("Missing or duplicate paragraph ID")
            seen.add(pid)
            if not paragraph.get("text", "").strip():
                errors.append(f"{pid}: empty prose")
            refs = paragraph.get("evidence_ids", [])
            if not refs or not set(refs) <= ids:
                errors.append(f"{pid}: missing or invalid evidence references")
    return errors


def review_is_current(chapter, review):
    return review.get("chapter_hash") == digest(chapter)
