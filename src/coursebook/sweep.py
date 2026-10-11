"""Book-wide independent grounding sweep, and caption-faithful fixes checked by the same evaluator.

    every final factual sentence ──evaluator (grounding prompt)──> supported? material? reason
    each one not supported ──writer proposes a narrower rewording──> evaluator re-checks it
        still not supported ──second attempt with the evaluator's new reason──> re-check
        still not supported ──> propose removal (high risk: the reviewer reads it)
    data/reviews/sweep.json (verdicts), data/reviews/sweep-recs.json (proposals)
The reviewer decides every proposal (`coursebook sweep --apply --by ...` takes them as recorded decisions).
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import runner
from .core import digest, read, write
from .review import decide, load_decisions, sentence_hash, _path
from .stages.evaluator import BATCH, audit_grounding, final_units
from .stages.verify import LineIndex

REWORD = Path("prompts/sweep_reword.txt")


def _setup(root):
    outline = runner.load(root, "outline", "book")
    decisions = load_decisions(root)
    units = final_units(root, outline, decisions)
    raw = {}
    for c in outline["chapters"]:
        for sec in c["sections"]:
            for p in runner.load(root, "verify", sec["id"])["paragraphs"]:
                for s in p["sentences"]:
                    conflict = decisions.get("conflict:" + s["id"])  # mirror apply_decisions: conflict edits come first
                    if conflict and conflict["sentence_hash"] == sentence_hash(s) and conflict["decision"] == "edit":
                        s = {**s, "text": conflict["text"], "reviewed": True}
                    raw[s["id"]] = s
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    return outline, units, raw, LineIndex(segments)


def sweep(root, gateway, workers=8, votes=1, tag="sweep"):
    """Judge every final factual sentence; with votes > 1, each sentence is judged in `votes`
    differently shuffled runs and the majority verdict counts (the evaluator is not self-consistent)."""
    import random
    _, units, _, index = _setup(root)
    factual = [s for u in units.values() for p in u["paragraphs"] for s in p["sentences"] if s["type"] == "F"]
    runs = []
    for k in range(votes):
        order = factual[:]
        if votes > 1:
            random.Random(f"{tag}:vote{k}").shuffle(order)
        chunks = [order[i:i + BATCH] for i in range(0, len(order), BATCH)]
        label = tag if votes == 1 else f"{tag}:vote{k}"
        with ThreadPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(lambda c, k=k: audit_grounding(gateway, c, index, label, vote=k), chunks))
        runs.append({v["sentence_id"]: v for part in parts for v in part})
    verdicts = []
    for s in factual:
        votes_for = [r[s["id"]] for r in runs]
        ok = sum(v["verdict"] == "supported" for v in votes_for)
        worst = next((v for v in votes_for if v["verdict"] != "supported"), votes_for[0])
        verdict = "supported" if ok * 2 > len(votes_for) else worst["verdict"]
        verdicts.append({**(votes_for[0] if verdict == "supported" else worst), "verdict": verdict,
                         "votes": [v["verdict"] for v in votes_for]})
    supported = sum(v["verdict"] == "supported" for v in verdicts)
    result = {"sentences": len(verdicts), "supported": supported, "rate": round(supported / len(verdicts), 4),
              "votes": votes, "self_disagreement": round(sum(len(set(v["votes"])) > 1 for v in verdicts) / len(verdicts), 4),
              "verdicts": verdicts}
    write(Path(root) / "reviews" / "sweep.json", result)
    return result


def _check(gateway, index, sentence, text, attempt, votes=3):
    """A proposed rewording counts as supported only if most of `votes` independent evaluator runs say so."""
    runs = [audit_grounding(gateway, [{**sentence, "id": f"{sentence['id']}:sweep{attempt}", "text": text}], index,
                            f"sweep-fix{attempt}" + (f":vote{k}" if k else ""), vote=k)[0] for k in range(votes)]
    ok = sum(r["verdict"] == "supported" for r in runs)
    worst = next((r for r in runs if r["verdict"] != "supported"), runs[0])
    return {**worst, "verdict": "supported" if ok * 2 > votes else worst["verdict"], "votes": [r["verdict"] for r in runs]}


def propose_fixes(root, gateway, workers=8):
    _, units, raw, index = _setup(root)
    current = {s["id"]: (s, p) for u in units.values() for p in u["paragraphs"] for s in p["sentences"]}
    flagged = [v for v in read(Path(root) / "reviews" / "sweep.json")["verdicts"] if v["verdict"] != "supported"]

    def one(v):
        sentence, paragraph = current[v["sentence_id"]]
        cited = [index.lines[c]["text"] for c in sentence["cites"] if c in index.lines]
        context = " ".join(s["text"] for s in paragraph["sentences"] if s["id"] != sentence["id"])[:700]
        reason, attempts = v["reason"], []
        for attempt in (1, 2):
            reply = gateway.call_json("writer", [{"role": "system", "content": REWORD.read_text()},
                                                 {"role": "user", "content": f"SENTENCE: {sentence['text']}\n\nWHY IT WAS NOT ACCEPTED: {reason}\n\n"
                                                                             f"PARAGRAPH CONTEXT: {context}\n\nCITED CAPTIONS:\n" + "\n".join(cited)}],
                                      stage="sweep", input_id=f"{sentence['id']}#{attempt}", max_completion_tokens=3000,
                                      validate=lambda o: [] if str(o.get("text", "")).strip() or o.get("remove") is True
                                      else ["give text or remove: true"])["parsed"]
            if reply.get("remove") is True:
                break
            text = " ".join(str(reply["text"]).split())
            check = _check(gateway, index, sentence, text, attempt)
            attempts.append({"text": text, "verdict": check["verdict"], "reason": check["reason"]})
            if check["verdict"] == "supported":
                return v["sentence_id"], {"decision": "edit", "text": text, "risk": "low", "evaluator": "supported",
                                          "was": sentence["text"], "why": v["reason"], "attempts": attempts,
                                          "sentence_hash": sentence_hash(raw[v["sentence_id"]])}
            reason = check["reason"]
        return v["sentence_id"], {"decision": "remove", "risk": "high", "was": sentence["text"], "why": v["reason"],
                                  "attempts": attempts, "sentence_hash": sentence_hash(raw[v["sentence_id"]])}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        recs = dict(pool.map(one, flagged))
    write(Path(root) / "reviews" / "sweep-recs.json", recs)
    return recs


def apply_fixes(root, reviewer, only=None):
    """Record the sweep proposals as the reviewer's decisions (only: a set of sentence ids, or None for all)."""
    _, _, raw, _ = _setup(root)
    recs = read(Path(root) / "reviews" / "sweep-recs.json")
    made = 0
    for sid, rec in recs.items():
        if only is not None and sid not in only:
            continue
        if sid not in raw or sentence_hash(raw[sid]) != rec["sentence_hash"]:
            continue  # the underlying sentence changed since the proposal
        decide(root, {"sentence_id": sid, "sentence": raw[sid]}, rec["decision"], reviewer, rec.get("text"),
               {"verdict": rec.get("evaluator", "not supported"), "by": "evaluator sweep"})
        made += 1
    decisions = load_decisions(root)
    for sid in recs:
        if sid in decisions and decisions[sid].get("reviewer") == reviewer:
            decisions[sid]["via"] = "book-wide evaluator sweep"
    write(_path(root), decisions)
    return made
