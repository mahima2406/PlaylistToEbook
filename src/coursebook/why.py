"""`coursebook why <sentence-or-paragraph-id>`: the full trail behind any piece of the book.

    sentence → where it sits (chapter, section) → caption lines it cites (lecture, time, words, link)
             → teaching points behind those lines → judge verdict (first pass, final, rewritten?)
             → reviewer decision → reference cross-check → evaluator agent sample (if drawn)
Read-only; no model calls.
"""
from pathlib import Path
from . import runner
from .core import read
from .review import load_decisions, sentence_hash

UNIT_STAGES = ("verify", "frame", "takeaways")


def _clock(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def find(root, item_id):
    for stage in UNIT_STAGES:
        base = Path(root) / "stages" / stage
        for path in sorted(base.glob("*.json")) if base.exists() else []:
            unit = read(path)["output"]
            for p in unit["paragraphs"]:
                if p["id"] == item_id:
                    return stage, unit, p, p["sentences"]
                for s in p["sentences"]:
                    if s["id"] == item_id:
                        return stage, unit, p, [s]
    return None


def trail(root, item_id):
    found = find(root, item_id)
    if not found:
        raise ValueError(f"No sentence or paragraph with id {item_id!r}; ids look like ch02.s03.p01 or ch02.s03.p01.02")
    stage, unit, paragraph, sentences = found
    outline = runner.load(root, "outline", "book")
    manifest = read(Path(root) / "manifest.json")
    label = {e["video_id"]: f"L{e['playlist_index']:02d}" for e in manifest["entries"] if e["video_id"]}
    lines = {}
    for v in {c.split("@")[0] for s in sentences for c in s["cites"]}:
        seg = runner.load(root, "segment", v)
        lines.update({x["id"]: x for x in (seg or {"lines": []})["lines"]})
    points = {}
    for v in outline["lectures"]:
        for p in runner.load(root, "extract", v)["points"]:
            points[p["id"]] = p
    where = "framing" if stage != "verify" else "?"
    section = None
    for c in outline["chapters"]:
        for sec in c["sections"]:
            if sec["id"] == unit["section_id"]:
                where, section = f"{c['id']} · {c['title']} → {sec['title']}", sec
    if stage != "verify":
        where = f"{unit['section_id']} ({'chapter opener / at a glance' if '.open' in unit['section_id'] else 'takeaways' if '.take' in unit['section_id'] else 'introduction'})"
    decisions = load_decisions(root)
    cross = runner.load(root, "crosscheck", unit["section_id"]) if stage == "verify" else None
    cross_by = {r["sentence_id"]: r for r in (cross or {}).get("results", [])}
    evaluation = runner.load(root, "evaluation", "book")
    eval_by = {g["sentence_id"]: g for g in (evaluation or {}).get("grounding", [])}
    out = [f"WHERE      {where}", f"PARAGRAPH  {paragraph['id']}" + ("  (rewritten once after the check)" if paragraph["id"] in unit.get("rewritten", []) else ""), ""]
    for s in sentences:
        out += [f"── {s['id']}  [{s['type']}]", f"   {s['text']}"]
        for c in s["cites"]:
            line = lines.get(c)
            if line:
                out.append(f"   cites {label.get(line['video_id'], line['video_id'])} {_clock(line['start'])}  “{line.get('text', '(caption text not in this package)')}”")
                out.append(f"         https://www.youtube.com/watch?v={line['video_id']}&t={int(line['start'])}s")
        behind = [p for p in points.values() if section and p["id"] in section["point_ids"] and set(p["line_ids"]) & set(s["cites"])]
        for p in behind[:3]:
            out.append(f"   point  {p['id']} ({p['kind']}, importance {p['importance']}): {p['text']}")
        first, final = unit.get("first_pass", {}).get(s["id"]), unit.get("verdicts", {}).get(s["id"])
        if first:
            out.append(f"   judge  first pass: {first['verdict']} ({first['confidence']:.2f})")
        if final:
            out.append(f"   judge  final: {final['verdict']} ({final['confidence']:.2f}) {final.get('reason', '')}".rstrip())
        d = decisions.get(s["id"])
        if d and d["sentence_hash"] == sentence_hash(s):
            out.append(f"   review {d['decision']} by {d['reviewer']} at {d['at']}" + (f": “{d['text']}”" if d.get("text") else ""))
        cd = decisions.get("conflict:" + s["id"])
        if s["id"] in cross_by:
            r = cross_by[s["id"]]
            out.append(f"   reference {r['verdict']} ({', '.join(r['refs'][:2])})" + (f": {r['reason']}" if r["reason"] else ""))
        if cd and cd["sentence_hash"] == sentence_hash(s):
            out.append(f"   conflict decision: {cd['decision']} by {cd['reviewer']}")
        if s["id"] in eval_by:
            g = eval_by[s["id"]]
            out.append(f"   evaluator agent sample: {g['verdict']}" + (f" ({g['reason']})" if g.get("reason") else ""))
        out.append("")
    return "\n".join(out)
