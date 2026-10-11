"""Planted-claim test: does the judge catch false sentences it has not seen before?

Per chapter: pick up to 20 supported factual sentences (seeded), have the writer
produce one false variant each (4 x 5 types), keep the original citations, then
judge plants mixed with an equal number of real supported sentences, shuffled,
with the normal judge prompt (the judge is not told which are plants).
A plant is caught when its verdict is not "supported" or its confidence is below
the cutoff (it would reach the review queue). Plants live only under
stages/plants; the renderer never reads them, and a test checks their text never
reaches book output.
"""
import random
from pathlib import Path
from ..core import digest
from .. import runner
from .verify import judge, LineIndex

PROMPT = Path("prompts/plant.txt")
TYPES = ["number", "term_swap", "reversed_cause", "unsupported_addition", "wrong_attribution"]
PER_CHAPTER = 20


def validate_plants(obj, expected):
    plants = obj.get("plants")
    if not isinstance(plants, list):
        return ["'plants' must be a list"]
    ids = {p.get("id") for p in plants}
    errors = [f"missing plant {i}" for i in expected if i not in ids]
    errors += [f"{p.get('id')}: empty text" for p in plants if not str(p.get("text", "")).strip()]
    return errors


def plant_chapter(gateway, chapter, verified, index, cutoff, seed=0):
    real = [s for section in verified for p in section["paragraphs"] for s in p["sentences"]
            if s["type"] == "F" and section["verdicts"].get(s["id"], {}).get("verdict") == "supported"]
    rng = random.Random(f"{seed}:{chapter['id']}")
    chosen = rng.sample(real, min(PER_CHAPTER, len(real)))
    requests = [{"id": f"X{n}", "type": TYPES[(n - 1) % len(TYPES)], "source": s} for n, s in enumerate(chosen, 1)]
    listing = "\n".join(f"{r['id']} | {r['type']} | {r['source']['text']}" for r in requests)
    result = gateway.call_json("writer", [{"role": "system", "content": PROMPT.read_text()},
                                          {"role": "user", "content": listing}],
                               stage="plant", input_id=chapter["id"],
                               validate=lambda o: validate_plants(o, [r["id"] for r in requests]))
    texts = {p["id"]: " ".join(p["text"].split()) for p in result["parsed"]["plants"]}
    plants = [{"id": f"{chapter['id']}.plant{r['id'][1:]}", "type": r["type"], "text": texts[r["id"]],
               "type_requested": r["type"], "cites": r["source"]["cites"], "original_id": r["source"]["id"]}
              for r in requests]
    decoys = rng.sample([s for s in real if s not in chosen], min(len(plants), len(real) - len(chosen)))
    mixed = [{"id": p["id"], "type": "F", "text": p["text"], "cites": p["cites"]} for p in plants] + decoys
    rng.shuffle(mixed)
    verdicts = judge(gateway, mixed, index, chapter["id"] + ":plants")
    for plant in plants:
        v = verdicts[plant["id"]]
        plant.update(verdict=v["verdict"], confidence=v["confidence"], reason=v["reason"],
                     caught=v["verdict"] != "supported" or v["confidence"] < cutoff)
    decoy_results = [{"id": d["id"], **verdicts[d["id"]]} for d in decoys]
    by_type = {t: {"planted": sum(p["type"] == t for p in plants), "caught": sum(p["type"] == t and p["caught"] for p in plants)}
               for t in TYPES}
    return {"chapter": chapter["id"], "plants": plants, "by_type": by_type,
            "caught": sum(p["caught"] for p in plants), "planted": len(plants),
            "decoys": decoy_results,
            "decoys_flagged": sum(d["verdict"] != "supported" or d["confidence"] < cutoff for d in decoy_results)}


def run_plants(root, gateway, config, outline, workers=4):
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    index = LineIndex(segments)
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)

    def job(chapter):
        verified = [runner.load(root, "verify", s["id"]) for s in chapter["sections"]]
        inputs = {"verify": [runner.output_hash(root, "verify", s["id"]) for s in chapter["sections"]],
                  "prompt": digest(PROMPT.read_text()), "judge": digest(Path("prompts/judge.txt").read_text()),
                  "cutoff": cutoff, "v": 1}
        return runner.run(root, "plants", chapter["id"], inputs,
                          lambda: plant_chapter(gateway, chapter, verified, index, cutoff))

    return gateway.map(job, outline["chapters"], workers=workers)
