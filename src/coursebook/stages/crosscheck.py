"""Cross-check: compare the book's technical sentences with the reference pack.

    final factual sentence ──search──> best reference passages (score ≥ min_score)
        ──judge──> agrees | contradicts | not_covered (+ material?)
    material contradictions → conflicts for the reviewer:
        keep  (follow the lecture, no note) · note (show both: a note is printed) · edit (rewrite)
Faithful to the lecture stays the rule; this layer catches where the lecture (or the
book's reading of it) disagrees with the course's own reference. Open conflicts block release.
"""
from pathlib import Path
from ..core import digest
from ..reference import load_index, Search, pack_hash
from .. import runner

PROMPT = Path("prompts/crosscheck.txt")
PASSAGES = 3
BATCH = 12


def _validate(obj, n):
    verdicts = obj.get("verdicts")
    if not isinstance(verdicts, list):
        return ["'verdicts' must be a list"]
    ids = {v.get("id") for v in verdicts}
    errors = [f"missing S{k}" for k in range(1, n + 1) if f"S{k}" not in ids]
    errors += [f"{v.get('id')}: bad verdict" for v in verdicts if v.get("verdict") not in ("agrees", "contradicts", "not_covered")]
    return errors


def crosscheck_section(gateway, search, unit, min_score):
    candidates = []
    for p in unit["paragraphs"]:
        for s in p["sentences"]:
            if s["type"] != "F":
                continue
            hits = [(score, c) for score, c in search.top(s["text"], PASSAGES) if score >= min_score]
            if hits:
                candidates.append((s, [c for _, c in hits]))
    results = []
    for start in range(0, len(candidates), BATCH):
        batch = candidates[start:start + BATCH]
        blocks = [f"S{n}: {s['text']}\n" + "\n".join(f"  [{c['id']}] {c['text'][:600]}" for c in passages)
                  for n, (s, passages) in enumerate(batch, 1)]
        verdicts = gateway.call_json("judge", [{"role": "system", "content": PROMPT.read_text()},
                                               {"role": "user", "content": "\n\n".join(blocks)}],
                                     stage="crosscheck", input_id=f"{unit['section_id']}#{start // BATCH}",
                                     validate=lambda o, k=len(batch): _validate(o, k), max_completion_tokens=16000)["parsed"]["verdicts"]
        by_id = {v["id"]: v for v in verdicts}
        for n, (s, passages) in enumerate(batch, 1):
            v = by_id[f"S{n}"]
            results.append({"sentence_id": s["id"], "text": s["text"], "refs": [c["id"] for c in passages],
                            "verdict": v["verdict"], "material": bool(v.get("material")), "reason": v.get("reason", "")})
    conflicts = [r for r in results if r["verdict"] == "contradicts" and r["material"]]
    return {"section_id": unit["section_id"], "checked": len(results),
            "counts": {k: sum(r["verdict"] == k for r in results) for k in ("agrees", "contradicts", "not_covered")},
            "results": results, "conflicts": conflicts}


def run_crosscheck(root, gateway, config, outline, workers=4):
    pack = config.get("reference_pack") or {}
    if not pack.get("enabled"):
        return []
    index = load_index(root, pack)
    search = Search(index["chunks"])
    min_score = pack.get("crosscheck_min_score", 0.18)
    sections = [s for c in outline["chapters"] for s in c["sections"]]

    def job(section):
        unit = runner.load(root, "verify", section["id"])
        inputs = {"pack": pack_hash(index), "verify": runner.output_hash(root, "verify", section["id"]),
                  "prompt": digest(PROMPT.read_text()), "min_score": min_score, "v": 1}
        return runner.run(root, "crosscheck", section["id"], inputs, lambda: crosscheck_section(gateway, search, unit, min_score))

    return gateway.map(job, sections, workers=workers)
