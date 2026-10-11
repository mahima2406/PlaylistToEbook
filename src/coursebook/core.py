"""Versioned artifacts, acquisition and evidence. No credentials in artifacts."""
import hashlib
import json
import math
import os
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


# Why a lecture could not be captured, as named reasons (the book and the release gate use these)
AVAILABILITY_REASONS = {"subscriber_only": "members_only", "premium_only": "premium_only",
                        "private": "private", "needs_auth": "sign_in_required"}
ERROR_REASONS = {"TranscriptsDisabled": "no_captions", "NoTranscriptFound": "no_captions_in_language",
                 "AgeRestricted": "age_restricted", "IpBlocked": "blocked_by_youtube", "RequestBlocked": "blocked_by_youtube",
                 "PoTokenRequired": "blocked_by_youtube", "VideoUnavailable": "unavailable_video",
                 "InvalidVideoId": "unavailable_video", "VideoUnplayable": "unplayable"}
REASON_TEXT = {"members_only": "members-only on YouTube", "premium_only": "YouTube Premium only", "private": "private",
               "sign_in_required": "requires sign-in", "no_captions": "captions turned off",
               "no_captions_in_language": "no captions in the configured language", "age_restricted": "age-restricted",
               "blocked_by_youtube": "YouTube blocked the caption request", "unavailable_video": "unavailable or deleted",
               "unplayable": "not playable", "capture_failed": "capture failed"}


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
                       "availability": entry.get("availability"),
                       "reuse_permission": "not_established"})
    return result


def youtube_proxy():
    """Proxy settings for YouTube requests, from the environment only (never config, logs or the repo).

    WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD   rotating residential proxy (recommended on servers)
    COURSEBOOK_PROXY_URL                                 any http(s) proxy URL
    Returns (transcript_proxy_config or None, yt_dlp_proxy_url or None)."""
    from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
    user, password = os.environ.get("WEBSHARE_PROXY_USERNAME"), os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if user and password:
        return (WebshareProxyConfig(proxy_username=user, proxy_password=password),
                f"http://{user}-rotate:{password}@p.webshare.io:80")
    url = os.environ.get("COURSEBOOK_PROXY_URL")
    return (GenericProxyConfig(http_url=url, https_url=url), url) if url else (None, None)


def inventory(root, config):
    import yt_dlp
    _, proxy = youtube_proxy()
    with yt_dlp.YoutubeDL({"extract_flat": "in_playlist", "quiet": True, "no_warnings": True, "noprogress": True,
                           "socket_timeout": 25, "retries": 2, **({"proxy": proxy} if proxy else {})}) as client:
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


BLOCKED_ERRORS = {"RequestBlocked", "IpBlocked", "PoTokenRequired"}


def captions_via_ytdlp(video_id, languages):
    """Second route to the same timed captions: yt-dlp's subtitle download (json3), optionally signed in
    with a YouTube session (COURSEBOOK_YT_COOKIES = path to a cookies.txt; never logged or copied)."""
    import tempfile
    import yt_dlp
    cookies = os.environ.get("COURSEBOOK_YT_COOKIES")
    _, proxy = youtube_proxy()
    with tempfile.TemporaryDirectory() as tmp:
        opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
                "subtitleslangs": list(languages), "subtitlesformat": "json3", "quiet": True, "no_warnings": True,
                "noprogress": True, "outtmpl": f"{tmp}/%(id)s.%(ext)s",
                **({"cookiefile": cookies} if cookies and Path(cookies).exists() else {}), **({"proxy": proxy} if proxy else {})}
        with yt_dlp.YoutubeDL(opts) as client:
            info = client.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        files = sorted(Path(tmp).glob(f"{video_id}.*.json3"))
        if not files:
            raise LookupError("no captions in the configured language")
        chosen = next((f for lang in languages for f in files if f.name.endswith(f".{lang}.json3")), files[0])
        segments = []
        for event in json.loads(chosen.read_text()).get("events", []):
            text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).replace("\n", " ").strip()
            if text:
                segments.append({"text": text, "start": event.get("tStartMs", 0) / 1000,
                                 "duration": event.get("dDurationMs", 0) / 1000})
        manual = bool((info.get("subtitles") or {}).get(chosen.name.split(".")[-2]))
        return {"video_id": video_id, "language": chosen.name.split(".")[-2], "is_generated": not manual,
                "segments": segments, "via": "yt-dlp"}


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
        if entry.get("availability") in AVAILABILITY_REASONS:  # YouTube says no public access: don't request it
            reports.append({"video_id": video_id, "playlist_index": entry["playlist_index"], "status": "blocked",
                            "reason": AVAILABILITY_REASONS[entry["availability"]]})
            continue
        if (root / "evidence" / f"{video_id}.json").exists():
            items = read(root / "evidence" / f"{video_id}.json")["items"]
            reports.append({"video_id": video_id, "status": "captured", "segments": len(items), "reused": True})
            continue
        try:
            try:
                transcript = YouTubeTranscriptApi(proxy_config=youtube_proxy()[0]).fetch(video_id, languages=config["languages"])
                raw = {"video_id": video_id, "language": transcript.language_code,
                       "is_generated": transcript.is_generated, "segments": transcript.to_raw_data()}
            except Exception as first:  # blocked (e.g. a cloud server): try the subtitle route, signed in if configured
                if type(first).__name__ not in BLOCKED_ERRORS:
                    raise
                try:
                    raw = captions_via_ytdlp(video_id, config["languages"])
                except Exception:
                    raise first from None
            evidence = evidence_from_segments(video_id, raw["segments"])
            path = snapshot(root, "captions", raw)
            write(root / "evidence" / f"{video_id}.json",
                  {"snapshot": path, "source_hash": digest(raw), "items": evidence,
                   "visual_review": "missing", "human_source_review": "pending"})
            reports.append({"video_id": video_id, "status": "captured", "segments": len(evidence)})
        except Exception as exc:
            # Do not serialize exception text: upstream URLs may contain tokens.
            reports.append({"video_id": video_id, "playlist_index": entry["playlist_index"], "status": "blocked",
                            "reason": ERROR_REASONS.get(type(exc).__name__, "capture_failed"),
                            "error_type": type(exc).__name__})
    write(root / "capture_report.json", reports)
    return reports


def review_is_current(chapter, review):
    return review.get("chapter_hash") == digest(chapter)
