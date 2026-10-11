import hashlib
import pytest
from coursebook.core import digest, write, read, snapshot, normalize_manifest, evidence_from_segments, validate_chapter, review_is_current
from coursebook.build import build


def fixture(tmp_path):
    raw = {"entries": [{"id": "fixture", "title": "Synthetic lesson"}]}
    source = snapshot(tmp_path, "playlist", raw)
    write(tmp_path / "manifest.json", {"source_snapshot": source, "source_hash": digest(raw), "entries": normalize_manifest(raw)})
    captions = {"segments": [{"text": "A fictional example has two objects.", "start": 0, "duration": 2}]}
    path = snapshot(tmp_path, "captions", captions)
    ev = evidence_from_segments("fixture", captions["segments"])
    write(tmp_path / "evidence/fixture.json", {"snapshot": path, "source_hash": digest(captions), "items": ev})
    chapter = {"title": "Synthetic fixture, not playlist content", "sections": [{"heading": "Example", "paragraphs": [{"id": "p1", "text": "This fictional example contains two objects.", "evidence_ids": ["fixture:00000"]}]}], "gaps": []}
    write(tmp_path / "chapters/fixture.json", {"source_hash": digest(captions), "chapter": chapter})
    return chapter, ev


def test_playlist_order_and_missing():
    result = normalize_manifest({"entries": [{"id": "z"}, None, {"id": "a"}]})
    assert [r["video_id"] for r in result] == ["z", None, "a"]
    assert result[1]["access"] == "unavailable"


@pytest.mark.parametrize("start,duration", [(-1, 2), (0, -1), (float("nan"), 2)])
def test_invalid_time(start, duration):
    with pytest.raises(ValueError):
        evidence_from_segments("v", [{"start": start, "duration": duration, "text": "x"}])


def test_invalid_reference(tmp_path):
    chapter, ev = fixture(tmp_path)
    chapter["sections"][0]["paragraphs"][0]["evidence_ids"] = ["invented"]
    assert validate_chapter(chapter, ev)


def test_stale_review(tmp_path):
    chapter, _ = fixture(tmp_path)
    review = {"chapter_hash": digest(chapter)}
    assert review_is_current(chapter, review)
    chapter["title"] = "Changed"
    assert not review_is_current(chapter, review)


def test_offline_replay_is_deterministic(tmp_path):
    fixture(tmp_path)
    config = {"title": "Fixture book"}
    report = build(tmp_path, tmp_path / "out", config)
    assert not report["release_ready"]
    before = (tmp_path / "out/book.pdf").read_bytes()
    build(tmp_path, tmp_path / "out", config)
    assert before == (tmp_path / "out/book.pdf").read_bytes()
    from pypdf import PdfReader
    text = " ".join(p.extract_text() for p in PdfReader(tmp_path / "out/book.pdf").pages)
    assert "two objects" in text
    assert "REVIEW INCOMPLETE" in text


def test_release_blocked(tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError, match="Release blocked"):
        build(tmp_path, tmp_path / "out", {"title": "Fixture"}, release=True)


def test_tampered_evidence_rejected(tmp_path):
    fixture(tmp_path)
    packet = read(tmp_path / "evidence/fixture.json")
    packet["items"][0]["text"] = "Invented fact"
    write(tmp_path / "evidence/fixture.json", packet)
    with pytest.raises(ValueError, match="differs"):
        build(tmp_path, tmp_path / "out", {"title": "Fixture"})
