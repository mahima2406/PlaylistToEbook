"""Studio: a browsable product view of a built book (`coursebook studio`).

Writes output/studio/{index.html, data.json}. data.json is assembled from stored
results only (no model calls): course and lectures, metrics, pipeline counts and
cost, the book with every sentence's evidence trail, the review queue, coverage,
board figures, listings, the 6W brief. Caption quotes are capped per sentence
(private-data mode), so the Studio can be shared like the book itself.
"""
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from .stages.runcode import load_code_run
from . import runner
from .stages.write import clean_text
from .core import read
from .review import load_decisions, apply_decisions, queue_items, open_items, sentence_hash

QUOTE_WORDS = 25
TEMPLATE = Path(__file__).parent / "studio_template" / "index.html"


def _clock(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cites(cites, lines, label):
    out, words = [], 0
    for c in cites:
        line = lines.get(c)
        if not line:
            continue
        text = line.get("text", "")
        take = text.split()[: max(0, QUOTE_WORDS - words)]
        words += len(take)
        out.append({"l": label.get(line["video_id"], ""), "t": _clock(line["start"]),
                    "u": f"https://www.youtube.com/watch?v={line['video_id']}&t={int(line['start'])}s",
                    "q": " ".join(take)})
    return out


def _sentences(paragraph, unit, lines, label, decisions, cross):
    out = []
    for s in paragraph["sentences"]:
        v = unit.get("verdicts", {}).get(s["id"], {})
        f = unit.get("first_pass", {}).get(s["id"], {})
        d = decisions.get(s["id"])
        d = d if d and d.get("sentence_hash") == sentence_hash(s) else None
        out.append({"id": s["id"], "type": s["type"], "text": clean_text(s["text"]), "cites": _cites(s["cites"], lines, label),
                    "v": v.get("verdict"), "c": round(v.get("confidence", 0), 2) if v else None, "why": v.get("reason", ""),
                    "first": f.get("verdict"), "review": d and {"decision": d["decision"], "by": d["reviewer"]},
                    "ref": cross.get(s["id"]), "note": s.get("note")})
    return out


def studio_data(root, config):
    from .render import build_book
    root = Path(root)
    outline = runner.load(root, "outline", "book")
    manifest = read(root / "manifest.json")
    label = {e["video_id"]: f"L{e['playlist_index']:02d}" for e in manifest["entries"] if e["video_id"]}
    with tempfile.TemporaryDirectory() as tmp:
        _, status, m = build_book(root, config, Path(tmp) / "out")
        brief = {p.name: p.read_text() for p in sorted((Path(tmp) / "out" / "brief").glob("*.md"))}
        report = read(Path(tmp) / "out" / "evaluation_report.json")
    lines = {}
    for v in set(outline["lectures"]):
        seg = runner.load(root, "segment", v)
        lines.update({x["id"]: x for x in (seg or {"lines": []})["lines"]})
    decisions = load_decisions(root)
    points = {p["id"]: p for v in outline["lectures"] for p in runner.load(root, "extract", v)["points"]}
    boards = {}
    for f in (runner.load(root, "frames_summary", "book") or {}).get("frames", []):
        if f.get("status") == "kept" and f.get("placement"):
            boards.setdefault(f["placement"][1], []).append(
                {"kind": f["kind"], "caption": f["caption"], "mermaid": f.get("mermaid", ""), "latex": f.get("latex", ""),
                 "at": f"{label.get(f['video_id'], '')} {_clock(f['seconds'])}",
                 "u": f"https://www.youtube.com/watch?v={f['video_id']}&t={f['seconds']}s"})
    runs = (load_code_run(root) or {}).get("listings", {})

    def unit_view(unit, kind):
        if not unit:
            return None
        unit = apply_decisions(unit, decisions)
        return [{"id": p["id"], "rewritten": p["id"] in unit.get("rewritten", []),
                 "s": _sentences(p, unit, lines, label, decisions, {}), "boards": boards.get(p["id"], [])}
                for p in (unit.get(kind) if kind else unit["paragraphs"])]

    chapters = []
    for c in outline["chapters"]:
        sections = []
        for sec in c["sections"]:
            unit = runner.load(root, "verify", sec["id"])
            if not unit:
                continue
            cross = {r["sentence_id"]: {"verdict": r["verdict"], "reason": r["reason"]}
                     for r in (runner.load(root, "crosscheck", sec["id"]) or {}).get("results", [])}
            unit = apply_decisions(unit, decisions)
            paragraphs = [{"id": p["id"], "rewritten": p["id"] in unit.get("rewritten", []),
                           "s": _sentences(p, unit, lines, label, decisions, cross), "boards": boards.get(p["id"], [])}
                          for p in unit["paragraphs"]]
            listings = [{"caption": l["caption"], "path": l["path"], "code": l["code"],
                         "run": runs.get(l["id"])} for l in (runner.load(root, "listings", sec["id"]) or {}).get("listings", [])]
            feeds = Counter(label[points[i]["video_id"]] for i in sec["point_ids"] if i in points)
            sections.append({"id": sec["id"], "title": sec["title"], "p": paragraphs, "listings": listings,
                             "from": sorted(feeds)})
        opener = runner.load(root, "frame", c["id"])
        take = runner.load(root, "takeaways", c["id"])
        chapters.append({"id": c["id"], "title": c["title"], "summary": c["summary"], "sections": sections,
                         "opener": unit_view(opener, "opener") or [], "glance": unit_view(opener, "at_a_glance") or [],
                         "takeaways": unit_view(take, None) or []})
    intro = runner.load(root, "frame", "intro")

    queue = []
    for item in open_items(root):
        queue.append({"id": item["sentence_id"], "text": item["sentence"]["text"], "verdict": item["verdict"],
                      "conf": round(item["confidence"], 2), "reason": item["reason"],
                      "cites": _cites(item["sentence"]["cites"], lines, label),
                      "context": " ".join(s["text"] for s in item["paragraph"]["sentences"] if s["id"] != item["sentence_id"])[:500]})

    lectures = []
    covered = set(outline["lectures"])
    for e in manifest["entries"]:
        ex = runner.load(root, "extract", e["video_id"]) if e["video_id"] in covered else None
        lectures.append({"label": label.get(e["video_id"], f"#{e['playlist_index']}"), "title": e["title"],
                         "minutes": round((e.get("duration") or 0) / 60), "covered": e["video_id"] in covered,
                         "points": len(ex["points"]) if ex else 0})
    matrix = {}
    for c in outline["chapters"]:
        for sec in c["sections"]:
            for i in sec["point_ids"]:
                if i in points:
                    key = f"{label[points[i]['video_id']]}|{c['id']}"
                    matrix[key] = matrix.get(key, 0) + 1
    dropped = [{"text": points[d["point_id"]]["text"], "reason": d["reason"], "l": label[points[d["point_id"]]["video_id"]]}
               for d in outline["dropped"] if d["point_id"] in points]

    calls = []
    for path in sorted((root / "runs").glob("*.jsonl")):
        calls += [json.loads(l) for l in path.read_text().splitlines()]
    stage_cost = {}
    for c in calls:
        b = stage_cost.setdefault(c.get("stage"), {"calls": 0, "cost": 0.0, "hits": 0})
        b["calls"] += 1
        b["cost"] += c.get("cost_usd") or 0
        b["hits"] += c.get("cache") == "hit"
    reader = runner.load(root, "reader", "book")
    plants = [runner.load(root, "plants", c["id"]) for c in outline["chapters"]]
    plant_misses = [{"type": p["type"], "text": p["text"]} for c in plants if c for p in c["plants"] if not p["caught"]]
    return {
        "course": {"title": config["title"], "playlist": config["playlist_url"], "status": status,
                   "reasons": report.get("draft_reasons", []), "reader": config["reader"]},
        "lectures": lectures,
        "metrics": {k: report.get(k) for k in ("words", "sections", "factual_sentences", "support_rate_first_pass",
                                               "support_rate_final", "paragraphs_rewritten", "review_queue_open",
                                               "plants_caught", "plants_planted", "plants_by_type",
                                               "real_sentences_flagged_in_plant_run", "real_sentences_in_plant_run",
                                               "points_extracted", "points_placed", "points_dropped", "points_auto_placed",
                                               "diagrams_kept", "diagrams_dropped", "listings", "crosscheck",
                                               "reference_conflicts_open", "code_run", "board_figures",
                                               "evaluator_metrics", "review_decisions")},
        "pipeline": {"stages": runner.counts(root), "cost": stage_cost,
                     "total_cost": round(sum(b["cost"] for b in stage_cost.values()), 2),
                     "budget": config.get("llm", {}).get("budget_usd")},
        "intro": unit_view(intro, None) or [],
        "chapters": chapters, "queue": queue, "plant_misses": plant_misses,
        "coverage": {"chapters": [c["id"] for c in outline["chapters"]], "titles": {c["id"]: c["title"] for c in outline["chapters"]},
                     "lectures": sorted({label[v] for v in outline["lectures"]}), "matrix": matrix, "dropped": dropped},
        "reader_contract": reader and reader["contract"],
        "brief": brief,
        "evaluation": runner.load(root, "evaluation", "book"),
    }


def build_studio(root, config, destination="output/studio", single_file=False):
    """index.html + data.json, or (single_file) one self-contained studio.html that opens from disk."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    data = studio_data(root, config)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if single_file:
        inline = payload.replace("</", "<\\/")
        page = TEMPLATE.read_text().replace("<script>\n(function", f"<script>window.__STUDIO_DATA = {inline};</script>\n<script>\n(function", 1)
        (destination / "studio.html").write_text(page)
        return {"path": str(destination / "studio.html"), "size_mb": round(len(page) / 1e6, 2)}
    (destination / "data.json").write_text(payload)
    shutil.copyfile(TEMPLATE, destination / "index.html")
    return {"path": str(destination / "index.html"), "data_mb": round((destination / "data.json").stat().st_size / 1e6, 2),
            "chapters": len(data["chapters"]), "queue": len(data["queue"])}
