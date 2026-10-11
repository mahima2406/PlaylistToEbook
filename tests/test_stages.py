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
    first_id = (re.findall(r"\[([\w-]+@\w+)\]", user) or [None])[0]
    if system.startswith("You write the introduction"):
        return {"paragraphs": [{"sentences": [{"text": "Chapter 1 covers the fixture.", "type": "R", "cites": []},
                                              {"text": "An intro fact.", "type": "F", "cites": [first_id]}]}]}
    if system.startswith("You write the opening"):
        return {"opener": {"paragraphs": [{"sentences": [{"text": "This chapter covers one section.", "type": "R", "cites": []}]}]},
                "at_a_glance": [{"text": f"Glance fact {n}.", "type": "F", "cites": [first_id]} for n in range(3)]}
    if system.startswith('You write the "Key takeaways"'):
        cite = re.findall(r"cites: ([\w-]+@\w+)", user)[0]
        return {"takeaways": [{"text": f"Takeaway {n}.", "type": "F", "cites": [cite]} for n in range(5)]}
    if system.startswith("You design explanatory diagrams"):
        para = re.findall(r"^(ch\d+\.s\d+\.p\d+):", user, re.M)[0]
        sentence = re.findall(r"^  (ch\d+\.s\d+\.p\d+\.\d+) \|", user, re.M)[0]
        return {"diagrams": [{"after_paragraph": para, "title": "Flow", "caption": "Text becomes IDs.",
                              "mermaid": 'flowchart LR\n  A["Text"] -->|"encode"| B["IDs"]',
                              "claims": [{"text": "Text is encoded into IDs.", "sentences": [sentence]}]}]}
    if system.startswith("You are a strict fact-checker"):
        verdicts = []
        for sid, kind, text in re.findall(r"^(S\d+) \[(\w+)\] (.*)$", user, re.M):
            if kind in ("CONNECTIVE", "ROADMAP"):
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
    intro = runner.load(root, "frame", "intro")
    assert intro["queue"] == [] and any(s["type"] == "R" for p in intro["paragraphs"] for s in p["sentences"])
    opener = runner.load(root, "frame", "ch01")
    assert len(opener["at_a_glance"]) == 3 and opener["opener"]
    assert len(runner.load(root, "takeaways", "ch01")["paragraphs"]) == 5
    assert len(runner.load(root, "diagrams", "ch01")["diagrams"]) == 1
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


def test_mermaid_validator_rejects_unsafe_or_malformed_sources():
    from coursebook.stages.diagrams import validate_mermaid
    assert validate_mermaid('flowchart LR\n  A["Text"] -->|"encode"| B["IDs"]') == []
    assert validate_mermaid('graph LR\n A-->B')
    assert validate_mermaid('flowchart LR\n  A["x"] --> B["y"]\n  click A "https://evil"')
    assert validate_mermaid('flowchart LR\n  A["<b>x</b>"] --> B["y"]')
    assert validate_mermaid('flowchart LR\n  A["x] --> B["y"]')


def test_roadmap_sentences_only_allowed_in_framing():
    roadmap = {"paragraphs": [{"sentences": [{"text": "Chapter 2 covers X.", "type": "R", "cites": []}]}]}
    assert validate_section(roadmap, set(), roadmap=True) == []
    assert validate_section(roadmap, set())


def test_chapters_name_their_lectures_once_and_paragraphs_carry_no_inline_keys(built):
    root, _ = built
    book, _, _ = build_book(root, CONFIG, root / "out")
    chapter = (book / "ch01.qmd").read_text()
    assert chapter.count("*Based on [L01: Lecture A]") == 1
    assert ".aside" not in chapter and "watch?v=vidA&t=" not in chapter
    assert "watch?v=vidA&t=" in (book / "sources.qmd").read_text()


def test_review_decisions_apply_and_go_stale_when_the_sentence_changes(built):
    from coursebook.review import queue_items, open_items, decide, apply_decisions, load_decisions
    root, _ = built
    unit_path = root / "stages" / "verify" / "ch01.s01.json"
    record = read(unit_path)
    sentence = record["output"]["paragraphs"][0]["sentences"][1]
    record["output"]["queue"] = [{"sentence_id": sentence["id"], "verdict": "partial", "confidence": 0.5,
                                  "reason": "test", "text": sentence["text"], "cites": sentence["cites"], "status": "open"}]
    write(unit_path, record)
    item = queue_items(root)[0]
    assert len(open_items(root)) == 1
    decide(root, item, "edit", "Reviewer", "A narrower fictional fact.")
    assert open_items(root) == []
    applied = apply_decisions(record["output"], load_decisions(root))
    assert applied["paragraphs"][0]["sentences"][1]["text"] == "A narrower fictional fact."
    decide(root, item, "remove", "Reviewer")
    applied = apply_decisions(record["output"], load_decisions(root))
    assert all(s["id"] != sentence["id"] for p in applied["paragraphs"] for s in p["sentences"])
    record["output"]["paragraphs"][0]["sentences"][1]["text"] = "Pipeline rewrote it."
    write(unit_path, record)
    assert len(open_items(root)) == 1  # decision was made on different text: stale, reopened


def test_interactive_review_records_accept_and_quit(built):
    from coursebook.review import interactive, open_items
    root, _ = built
    unit_path = root / "stages" / "verify" / "ch01.s01.json"
    record = read(unit_path)
    s1 = record["output"]["paragraphs"][0]["sentences"][1]
    record["output"]["queue"] = [{"sentence_id": s1["id"], "verdict": "partial", "confidence": 0.5, "reason": "r",
                                  "text": s1["text"], "cites": s1["cites"], "status": "open"}]
    write(unit_path, record)
    answers = iter(["a"])
    made = interactive(root, CONFIG, live_gateway(root), "Reviewer", ask=lambda _: next(answers), show=lambda *_: None)
    assert made == 1 and open_items(root) == []
