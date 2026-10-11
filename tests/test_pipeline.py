import pytest
from coursebook.core import normalize_manifest, evidence_from_segments, digest, review_is_current


def test_playlist_order_and_missing():
    result = normalize_manifest({"entries": [{"id": "z"}, None, {"id": "a"}]})
    assert [r["video_id"] for r in result] == ["z", None, "a"]
    assert result[1]["access"] == "unavailable"


@pytest.mark.parametrize("start,duration", [(-1, 2), (0, -1), (float("nan"), 2)])
def test_invalid_time(start, duration):
    with pytest.raises(ValueError):
        evidence_from_segments("v", [{"start": start, "duration": duration, "text": "x"}])


def test_stale_review():
    chapter = {"title": "Fixture"}
    review = {"chapter_hash": digest(chapter)}
    assert review_is_current(chapter, review)
    chapter["title"] = "Changed"
    assert not review_is_current(chapter, review)
