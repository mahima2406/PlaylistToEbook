"""End-to-end pipeline against a scripted fake provider: no network, no credentials.

The fake reads each request's prompt to decide which stage is calling and answers
with minimal valid JSON derived from the request itself, so every stage, the
runner cache, offline replay, plant exclusion and the release gate are exercised.
"""
import json
import re
import httpx
import pytest
from coursebook.core import digest, read, write, snapshot, normalize_manifest, evidence_from_segments
from coursebook.llm import Gateway, CacheMiss
from coursebook import runner
from coursebook.pipeline import run
from coursebook.render import build_book, source_key, md
from coursebook.stages.segment import make_lines, run_segment
from coursebook.stages.outline import approve, approval_is_current
from coursebook.stages.write import validate_section

SETTINGS = {"base": "https://fake.example/v1", "key": "k", "header": "api-key",
            "roles": {"writer": "writer-dep", "judge": "judge-dep"}}
CONFIG = {"title": "Fixture Book", "reader": "A programmer.", "playlist_url": "https://example.com/list",
          "verify": {"confidence_cutoff": 0.7}, "llm": {"concurrency": 2}}
PLANT_MARK = "PLANTEDFALSEHOOD"


def answer(body):
    system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
    if system.startswith("You extract teaching points"):
        keys = re.findall(r"^\[(\w+)\]", user, re.M)
        return {"points": [{"kind": "definition", "text": f"Point from line {k}.", "lines": [k], "importance": 3}
                           for k in keys[:2]]}
    if system.startswith("You are the editor"):
        refs = re.findall(r"^(P\d+) \|", user, re.M)
        return {"chapters": [{"title": "Fixture chapter", "summary": "Learn the fixture.",
                              "sections": [{"title": "Only section", "points": refs}]}], "dropped": []}
    if system.startswith("You write one section"):
        first = re.findall(r"^\[([\w-]+@\w+)\]", user, re.M)[0]
        return {"paragraphs": [{"sentences": [{"text": "Next, a fact.", "type": "C", "cites": []},
                                              {"text": "A fictional fact.", "type": "F", "cites": [first]}]}]}
    if system.startswith("You are a strict fact-checker"):
        verdicts = []
        for sid, kind, text in re.findall(r"^(S\d+) \[(\w+)\] (.*)$", user, re.M):
            if kind == "CONNECTIVE":
                verdicts.append({"id": sid, "verdict": "ok", "confidence": 0.9, "reason": ""})
            else:
                bad = PLANT_MARK in text
                verdicts.append({"id": sid, "verdict": "unsupported" if bad else "supported",
                                 "confidence": 0.9, "reason": "planted" if bad else ""})
        return {"verdicts": verdicts}
    if system.startswith("You help test a fact-checker"):
        ids = re.findall(r"^(X\d+) \|", user, re.M)
        return {"plants": [{"id": i, "type": "number", "text": f"{PLANT_MARK} {i}"} for i in ids]}
    raise AssertionError("unexpected prompt: " + system[:60])


def provider(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={"model": body["model"] + "-v1", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                                     "choices": [{"finish_reason": "stop",
                                                  "message": {"content": json.dumps(answer(body))}}]})


def fixture_data(tmp_path, n_lines=6):
    raw = {"title": "Fixture playlist", "entries": [{"id": "vidA", "title": "Lecture A", "duration": 60}]}
    write(tmp_path / "manifest.json", {"source_snapshot": snapshot(tmp_path, "playlist", raw),
                                       "source_hash": digest(raw), "entries": normalize_manifest(raw)})
    captions = {"segments": [{"text": f"caption line {n}", "start": n * 10.0, "duration": 4.0} for n in range(n_lines)]}
    write(tmp_path / "evidence" / "vidA.json",
          {"snapshot": snapshot(tmp_path, "captions", captions), "source_hash": digest(captions),
           "items": evidence_from_segments("vidA", captions["segments"])})


def live_gateway(tmp_path, offline=False):
    client = None if offline else httpx.Client(transport=httpx.MockTransport(provider))
    return Gateway(tmp_path, SETTINGS, client=client, offline=offline, run_id="t", sleep=lambda s: None)


@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.chdir(__import__("pathlib").Path(__file__).parents[1])  # prompts/ are read relative to the repo
    fixture_data(tmp_path)
    outline = run(tmp_path, CONFIG, live_gateway(tmp_path), log=lambda *_: None)
    return tmp_path, outline


def test_full_pipeline_produces_cited_verified_sections(built):
    root, outline = built
    assert [c["title"] for c in outline["chapters"]] == ["Fixture chapter"]
    verified = runner.load(root, "verify", "ch01.s01")
    assert verified["queue"] == []
    assert all(v["verdict"] in ("supported", "ok") for v in verified["verdicts"].values())
    plants = runner.load(root, "plants", "ch01")
    assert plants["caught"] == plants["planted"] > 0


def test_offline_replay_rebuilds_identically_without_network(built, tmp_path):
    root, _ = built
    before = {p.name: p.read_text() for p in (root / "stages").rglob("*.json")}
    for path in (root / "stages").rglob("*.json"):  # force recompute from the model cache only
        path.unlink()
    run(root, CONFIG, live_gateway(root, offline=True), log=lambda *_: None)
    after = {p.name: p.read_text() for p in (root / "stages").rglob("*.json")}
    assert before == after


def test_offline_replay_fails_loudly_on_cache_miss(built):
    root, _ = built
    for path in (root / "cache").glob("*.json"):
        path.unlink()
    for path in (root / "stages" / "write").glob("*.json"):
        path.unlink()
    with pytest.raises(CacheMiss):
        run(root, CONFIG, live_gateway(root, offline=True), log=lambda *_: None)


def test_unchanged_inputs_skip_model_calls(built):
    root, _ = built
    calls = []
    gateway = live_gateway(root)
    gateway.complete = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("model called"))
    run(root, CONFIG, gateway, log=lambda *_: None)
    assert calls == []


def test_planted_text_never_reaches_book_chapters(built):
    root, _ = built
    book, status, metrics = build_book(root, CONFIG, root / "out")
    chapters = "".join(p.read_text() for p in book.glob("ch*.qmd"))
    assert PLANT_MARK not in chapters and "A fictional fact." in chapters
    assert metrics["plants_caught"] == metrics["plants_planted"]


def test_book_is_draft_until_outline_is_approved(built):
    root, _ = built
    _, status, _ = build_book(root, CONFIG, root / "out")
    assert status == "DRAFT"
    report = read(root / "out" / "evaluation_report.json")
    assert "the outline has not been approved by a reviewer" in report["draft_reasons"]
    approve(root, "Reviewer")
    assert approval_is_current(root)
    report_after = build_book(root, CONFIG, root / "out") and read(root / "out" / "evaluation_report.json")
    assert "the outline has not been approved by a reviewer" not in report_after["draft_reasons"]
    assert "the blinded audit has not been run" in report_after["draft_reasons"]


def test_tampered_caption_snapshot_is_rejected(built):
    root, _ = built
    packet = read(root / "evidence" / "vidA.json")
    packet["items"][0]["text"] = "Invented fact"
    write(root / "evidence" / "vidA.json", packet)
    with pytest.raises(ValueError, match="evidence differs"):
        run_segment(root, "vidA")


def test_line_ids_are_unique_within_a_second():
    items = [{"id": f"v:{n}", "start": s, "end": s + 1, "text": "x", "url": "u"} for n, s in enumerate([5.1, 5.7, 3700.0])]
    assert [x["id"] for x in make_lines("v", items)] == ["v@5", "v@5b", "v@3700"]


def test_sentence_tag_rules():
    allowed = {"v@1"}
    ok = {"paragraphs": [{"sentences": [{"text": "Fact.", "type": "F", "cites": ["v@1"]},
                                        {"text": "Next.", "type": "C", "cites": []}]}]}
    assert validate_section(ok, allowed) == []
    bad = {"paragraphs": [{"sentences": [{"text": "Fact.", "type": "F", "cites": []},
                                         {"text": "Next.", "type": "C", "cites": ["v@1"]},
                                         {"text": "Made up.", "type": "F", "cites": ["v@99"]}]}]}
    errors = " ".join(validate_section(bad, allowed))
    assert "needs at least one citation" in errors and "must not cite" in errors and "not in the supplied" in errors


def test_source_key_merges_nearby_lines_and_links_seconds():
    lines = {f"v@{s}": {"video_id": "v", "start": float(s)} for s in (10, 40, 300)}
    key = source_key(["v@40", "v@10", "v@300"], lines, {"v": "L01"})
    assert key == ("L01 [0:10–0:40](https://www.youtube.com/watch?v=v&t=10s), "
                   "[5:00](https://www.youtube.com/watch?v=v&t=300s)")


def test_markdown_escaping_keeps_text_literal():
    assert md("a_b *c* $5 [x]") == "a\\_b \\*c\\* \\$5 \\[x\\]"
