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
            "roles": {"writer": "writer-dep", "judge": "judge-dep", "evaluator": "eval-dep"}}
CONFIG = {"title": "Fixture Book", "reader": "A programmer.", "playlist_url": "https://example.com/list",
          "verify": {"confidence_cutoff": 0.7}, "llm": {"concurrency": 2}}
PLANT_MARK = "PLANTEDFALSEHOOD"


def answer(body):
    system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
    if system.startswith("You extract teaching points"):
        keys = re.findall(r"^\[(\w+)\]", user, re.M)
        return {"points": [{"kind": "definition", "text": f"Point from line {k}.", "lines": [k], "importance": 3}
                           for k in keys[:2]]}
    if system.startswith("You infer the intended reader"):
        line = re.findall(r"^\[([\w-]+@\w+)\]", user, re.M)[0]
        item = {"value": "A programmer.", "status": "inferred", "evidence": [line]}
        return {"primary_learning_outcome": item, "reader_profile": item, "known_prior_skills": [item],
                "unknown_prior_skills": [{"value": "Calculus", "status": "unknown", "evidence": []}],
                "instructional_modes": [item], "representations_to_preserve": [],
                "uncertainties_to_validate": ["math level"], "editorial_rules": ["define terms first"]}
    if system.startswith("You are an independent auditor of a technical book"):
        n = len(re.findall(r"^S\d+:", user, re.M))
        return {"verdicts": [{"id": f"S{k}", "verdict": "supported", "material": False, "reason": ""} for k in range(1, n + 1)]}
    if system.startswith("You are an independent auditor checking"):
        return {"ideas": [{"idea": "an idea", "core": True, "in_book": True}]}
    if system.startswith("You are an independent reviewer of one chapter"):
        return {"scores": {c: {"score": 4, "evidence": "ok"} for c in
                           ["clarity", "flow", "book_voice", "definitions_first", "concision", "reader_fit", "title_fit"]},
                "improvements": ["more examples"]}
    if system.startswith("You turn numbers stated"):
        sid = re.findall(r"^(\S+) \|", user, re.M)[0]
        return {"checks": [{"sentence_id": sid, "expected": 3, "expression": "len(ids)", "tolerance": 0}]}
    if system.startswith("You choose code listings"):
        ref = re.findall(r"^(ref:\S+) \(under heading", user, re.M)[0]
        return {"listings": [{"ref": ref, "caption": "Encodes text into IDs."}]}
    if system.startswith("You check whether a code excerpt"):
        return {"verdict": "matches", "reason": ""}
    if system.startswith("You compare sentences from a book"):
        n = len(re.findall(r"^S\d+:", user, re.M))
        return {"verdicts": [{"id": f"S{k}", "verdict": "contradicts" if k == 1 else "agrees", "material": k == 1,
                              "reason": "reference uses a different value"} for k in range(1, n + 1)]}
    if "Group the lectures" in system:
        numbers = [int(n) for n in re.findall(r"^Lecture (\d+):", user, re.M)]
        half = len(numbers) // 2
        return {"chapters": [{"title": "Part one", "summary": "First.", "lectures": numbers[:half]},
                             {"title": "Part two", "summary": "Second.", "lectures": numbers[half:]}]}
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


def fixture_data(tmp_path, n_lines=6, videos=("vidA",)):
    raw = {"title": "Fixture playlist", "entries": [{"id": v, "title": f"Lecture {v[-1]}", "duration": 60} for v in videos]}
    write(tmp_path / "manifest.json", {"source_snapshot": snapshot(tmp_path, "playlist", raw),
                                       "source_hash": digest(raw), "entries": normalize_manifest(raw)})
    for video in videos:
        captions = {"segments": [{"text": f"{video} caption line {n}", "start": n * 10.0, "duration": 4.0}
                                 for n in range(n_lines)]}
        write(tmp_path / "evidence" / f"{video}.json",
              {"snapshot": snapshot(tmp_path, "captions", captions), "source_hash": digest(captions),
               "items": evidence_from_segments(video, captions["segments"])})


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
    assert "the evaluator agent has not run" in report_after["draft_reasons"]


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


def test_large_books_plan_chapters_then_outline_each(tmp_path, monkeypatch):
    monkeypatch.chdir(__import__("pathlib").Path(__file__).parents[1])
    fixture_data(tmp_path, videos=("vidA", "vidB", "vidC", "vidD", "vidE"))
    outline = run(tmp_path, CONFIG, live_gateway(tmp_path), until="outline", log=lambda *_: None)
    assert [c["title"] for c in outline["chapters"]] == ["Part one", "Part two"]
    assert [c["id"] for c in outline["chapters"]] == ["ch01", "ch02"]
    placed = [i for c in outline["chapters"] for s in c["sections"] for i in s["point_ids"]]
    assert len(placed) == len(set(placed)) == 10  # 2 points per lecture, each placed once


def test_plan_must_keep_lectures_in_order_exactly_once():
    from coursebook.stages.outline import validate_plan
    assert validate_plan({"chapters": [{"title": "A", "lectures": [1, 2]}, {"title": "B", "lectures": [4]}]}, [1, 2, 4]) == []
    assert validate_plan({"chapters": [{"title": "A", "lectures": [2, 1]}, {"title": "B", "lectures": [4]}]}, [1, 2, 4])
    assert validate_plan({"chapters": [{"title": "A", "lectures": [1]}, {"title": "B", "lectures": [4]}]}, [1, 2, 4])


def test_extraction_drops_invented_line_ids_and_counts_them():
    from coursebook.stages.extract import keep_valid_lines
    points = [{"lines": ["1", "999"]}, {"lines": ["998"]}, {"lines": [2]}]
    kept, dropped = keep_valid_lines(points, {"1", "2"})
    assert [p["lines"] for p in kept] == [["1"], ["2"]] and dropped == 1


def test_forgotten_points_are_placed_next_to_their_neighbour():
    from coursebook.stages.outline import place_missing
    parsed = {"chapters": [{"sections": [{"points": ["P1", "P2"]}, {"points": ["P4"]}]}], "dropped": [{"point": "P5"}]}
    assert place_missing(parsed, ["P1", "P2", "P3", "P4", "P5"]) == ["P3"]
    assert parsed["chapters"][0]["sections"][0]["points"] == ["P1", "P2", "P3"]


def test_writer_drops_invented_citations_and_uncited_facts():
    from coursebook.stages.write import keep_valid_cites
    paragraphs = [{"sentences": [{"text": "a", "type": "F", "cites": ["v@1", "v@99"]},
                                 {"text": "b", "type": "F", "cites": ["v@98"]},
                                 {"text": "c", "type": "C", "cites": []}]}]
    kept, dropped = keep_valid_cites(paragraphs, {"v@1"})
    assert [s["text"] for s in kept[0]["sentences"]] == ["a", "c"] and kept[0]["sentences"][0]["cites"] == ["v@1"]
    assert dropped == 1


def test_reader_profile_is_evidence_linked_and_can_feed_prompts(built):
    from coursebook.stages.reader import reader_for_prompts, reader_markdown
    root, _ = built
    record = runner.load(root, "reader", "book")
    assert record["contract"]["reader_profile"]["evidence"]
    assert reader_for_prompts(root, CONFIG) == CONFIG["reader"]  # off by default
    enabled = {**CONFIG, "reader_profile": {"enabled": True}}
    assert reader_for_prompts(root, enabled).startswith("# reader.md")
    assert "Calculus" in reader_markdown(record) and "[unknown]" in reader_markdown(record)


def test_evaluator_agent_scores_book_and_gates_release(built):
    from coursebook.stages.evaluator import run_evaluator
    root, _ = built
    config = {**CONFIG, "evaluation": {"grounding_sample": 5, "coverage_clips": 2, "clip_seconds": 30,
                                       "thresholds": {"independent_support": 0.95, "material_errors_per_100": 2,
                                                      "core_ideas_missed": 0.1, "quality_min_average": 3.5}}}
    result = run_evaluator(root, live_gateway(root), config)
    assert result["passed"] and result["metrics"]["independent_support"] == 1.0
    assert result["metrics"]["agreement_with_judge"] == 1.0 and result["metrics"]["quality_average"] == 4.0
    _, _, metrics = build_book(root, config, root / "out")
    report = read(root / "out" / "evaluation_report.json")
    assert "the evaluator agent has not run" not in report["draft_reasons"]
    assert sorted(metrics["brief"]) == ["concept_map.md", "coverage.md", "learning_path.md",
                                        "pipeline.md", "rationale.md", "reader.md"]
    assert "Independent support rate" in (root / "out" / "brief" / "rationale.md").read_text()


PACK = {"enabled": True, "name": "demo/ref", "repo": "https://example.com/ref", "commit": "abc1234", "license": "MIT",
        "include": ["*.ipynb"], "listings_per_section": 1, "crosscheck_min_score": 0.0}


def fake_reference(root):
    chunks = [{"id": "ref:nb.ipynb#cell1", "path": "nb.ipynb", "kind": "code", "heading": "Fixture",
               "text": "ids = tokenizer.encode(text)  # fixture fact caption line"},
              {"id": "ref:nb.ipynb#cell2", "path": "nb.ipynb", "kind": "code", "heading": "Fixture", "text": "print(ids)"},
              {"id": "ref:nb.ipynb#cell3", "path": "nb.ipynb", "kind": "text", "heading": "Fixture", "text": "A fictional fact explained."}]
    write(root / "reference" / "index.json", {"repo": PACK["repo"], "commit": PACK["commit"], "license": "MIT",
                                              "name": PACK["name"], "include": PACK["include"], "chunks": chunks})


def test_listings_are_verbatim_reference_code_and_rendered_with_source(built):
    from coursebook.stages.listings import run_listings
    root, outline = built
    fake_reference(root)
    # give the section a code point so it asks for listings
    rec = read(root / "stages" / "extract" / "vidA.json")
    rec["output"]["points"][0]["kind"] = "code"
    write(root / "stages" / "extract" / "vidA.json", rec)
    config = {**CONFIG, "reference_pack": PACK}
    result = run_listings(root, live_gateway(root), config, outline)
    listing = result[0]["listings"][0]
    assert listing["code"].startswith("ids = tokenizer.encode(text)") and "print(ids)" in listing["code"]
    book, _, metrics = build_book(root, config, root / "out")
    chapter = (book / "ch01.qmd").read_text()
    assert "```python" in chapter and "demo/ref" in chapter and "MIT" in chapter and metrics["listings"] == 1


def test_reference_conflicts_reach_reviewer_and_notes_render(built):
    from coursebook.stages.crosscheck import run_crosscheck
    from coursebook.review import open_conflicts, decide_conflict
    root, outline = built
    fake_reference(root)
    config = {**CONFIG, "reference_pack": PACK}
    checked = run_crosscheck(root, live_gateway(root), config, outline)
    assert checked[0]["conflicts"]
    _, _, metrics = build_book(root, config, root / "out")
    report = read(root / "out" / "evaluation_report.json")
    assert any("conflicts with the reference" in r for r in report["draft_reasons"])
    item = open_conflicts(root)[0]
    decide_conflict(root, item, "note", "Reviewer", note="the reference uses a different value")
    assert open_conflicts(root) == []
    book, _, _ = build_book(root, config, root / "out")
    assert "The course's reference code differs here: the reference uses a different value" in (book / "ch01.qmd").read_text()


def test_exported_package_has_no_caption_text_and_rebuilds_identically(built, tmp_path):
    from coursebook.export import export_package, verify_package
    root, _ = built
    target = tmp_path / "book-data"
    result = export_package(root, CONFIG, target)
    assert result["files"] > 0
    everything = "".join(p.read_text() for p in target.rglob("*.json*"))
    assert "vidA caption line 1" not in everything  # caption text never leaves data/
    assert not (target / "cache").exists() and not (target / "evidence").exists()
    assert verify_package(CONFIG, target)["ok"]
    rec = next((target / "stages" / "verify").glob("*.json"))
    rec.write_text(rec.read_text().replace("A fictional fact.", "A tampered fact."))
    checked = verify_package(CONFIG, target)
    assert not checked["ok"] and any("changed" in p for p in checked["problems"])


def test_web_edition_has_hover_sources_with_short_quotes(built):
    root, _ = built
    build_book(root, CONFIG, root / "out")
    web = (root / "out" / "web" / "ch01.qmd").read_text()
    pdf = (root / "out" / "book" / "ch01.qmd").read_text()
    assert "[^src-ch01-s01-p01]" in web and "watch?v=vidA&t=" in web and "“vidA caption line" in web
    assert "[^src-" not in pdf  # the printed book stays clean
    import json as _json
    assert _json.loads((root / "out" / "web" / "_quarto.yml").read_text())["format"]["html"]["footnotes-hover"]


def test_listings_execute_and_stated_numbers_become_checks(built, tmp_path):
    from coursebook.stages.listings import run_listings
    from coursebook.stages.runcode import run_code, numbers_in, validate_checks
    root, outline = built
    repo = tmp_path / "refrepo"
    repo.mkdir()
    nb = {"cells": [{"cell_type": "code", "source": ["ids = [1, 2, 3]  # fixture fact caption line\n", "print(ids)"]}]}
    (repo / "nb.ipynb").write_text(json.dumps(nb))
    pack = {**PACK, "path": str(repo)}
    config = {**CONFIG, "reference_pack": pack}
    from coursebook.reference import build_index
    build_index(root, pack)
    rec = read(root / "stages" / "extract" / "vidA.json")
    rec["output"]["points"][0]["kind"] = "code"
    write(root / "stages" / "extract" / "vidA.json", rec)
    run_listings(root, live_gateway(root), config, outline)
    vrec = read(root / "stages" / "verify" / "ch01.s01.json")
    vrec["output"]["paragraphs"][0]["sentences"][1]["text"] = "The list holds 3 token IDs."
    write(root / "stages" / "verify" / "ch01.s01.json", vrec)
    result = run_code(root, live_gateway(root), config, outline, timeout=60)
    run = next(iter(result["listings"].values()))
    assert run["status"] == "ran" and "[1, 2, 3]" in run["output"]
    assert run["checks"][0]["passed"] is True and run["checks"][0]["value"] == 3
    book, _, metrics = build_book(root, config, root / "out")
    assert "Checked by running the code" in (book / "ch01.qmd").read_text()
    assert metrics["code_run"]["checks_passed"] == 1
    assert numbers_in("about 124 million parameters and 50,257 tokens") == [124e6, 50257.0]
    bad = validate_checks({"checks": [{"sentence_id": "s", "expected": 9, "expression": "__import__('os')", "tolerance": 0}]},
                          {"s": {"text": "There are 3 IDs."}})
    assert any("does not appear" in e for e in bad) and any("side-effect-free" in e for e in bad)


def test_why_prints_the_full_trail_and_heatmap_is_drawn(built):
    from coursebook.why import trail
    root, _ = built
    text = trail(root, "ch01.s01.p01")
    assert "ch01 · Fixture chapter" in text and "cites L01 0:00" in text and "“vidA caption line" in text
    assert "judge  final: supported" in text and "watch?v=vidA&t=0s" in text
    with pytest.raises(ValueError):
        trail(root, "ch09.s01.p01")
    book, _, _ = build_book(root, CONFIG, root / "out")
    assert (book / "figures" / "coverage.svg").read_text().count("<rect") == 1
    assert "figures/coverage.pdf" in (book / "sources.qmd").read_text()
    assert "figures/coverage.svg" in (root / "out" / "web" / "sources.qmd").read_text()
