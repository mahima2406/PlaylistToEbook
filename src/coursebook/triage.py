"""Pre-sort the review: a proposed decision, with its reason, for every open item.

    open queue sentences ─┐
    open reference conflicts ─┼─ writer proposes {decision, text?, note?, reason, risk}
    open numeric disagreements ┘   edits are re-judged against the same cited captions
                                   └─> data/reviews/recommendations.json
The reviewer still decides every item (`coursebook review`): Enter takes the proposal,
any other key overrides it. A proposal is tied to the sentence hash it was made on and is
ignored once that sentence changes. Numeric disagreements are resolved by an edit (the
executed value replaces the stated one) or a dismissal with its reason; both are recorded.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import runner
from .core import digest, read, write
from .review import (_path, caption_lines, decide, decide_conflict, load_decisions, open_conflicts, open_items,
                     recheck, sentence_hash)

PROMPT = Path("prompts/triage.txt")
ALLOWED = {"queue": {"accept", "edit", "remove"}, "conflict": {"keep", "note", "edit"}, "numeric": {"edit", "dismiss"}}


def _recs_path(root):
    return Path(root) / "reviews" / "recommendations.json"


def load_recommendations(root):
    path = _recs_path(root)
    return read(path) if path.exists() else {}


def numeric_items(root):
    """Sentences whose stated numbers disagree with the executed reference code (judge-confirmed)."""
    from .stages.runcode import load_code_run
    run = load_code_run(root) or {"listings": {}}
    failed = {}
    for listing_id, result in run["listings"].items():
        for check in result["checks"]:
            if check["passed"] is False:
                failed.setdefault(check["sentence_id"], []).append({**check, "listing": listing_id})
    items = []
    for sentence_id, checks in sorted(failed.items()):
        unit = runner.load(root, "verify", sentence_id.split(".p")[0])
        sentence = next((s for p in (unit or {"paragraphs": []})["paragraphs"] for s in p["sentences"]
                         if s["id"] == sentence_id), None)
        if sentence:
            items.append({"key": "numeric:" + sentence_id, "sentence_id": sentence_id, "sentence": sentence, "checks": checks})
    return items


def open_numeric(root):
    decisions = load_decisions(root)
    return [i for i in numeric_items(root) if decisions.get(i["key"], {}).get("sentence_hash") != sentence_hash(i["sentence"])]


def decide_numeric(root, item, decision, reviewer, text=None, check=None, reason=None):
    if decision not in ("edit", "dismiss"):
        raise ValueError("decision must be edit or dismiss")
    if decision == "edit":
        decide(root, item, "edit", reviewer, text, check)
    decisions = load_decisions(root)
    decisions[item["key"]] = {"decision": decision, "reviewer": reviewer, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "sentence_hash": sentence_hash(item["sentence"]), "original": item["sentence"]["text"],
                              "evidence": [f"{c['expression']} = {c['value']:g} (text: {c['expected']:g})" for c in item["checks"]],
                              **({"reason": " ".join((reason or "").split())} if decision == "dismiss" else {})}
    write(_path(root), decisions)
    return decisions[item["key"]]


def _kind(item):
    return "numeric" if item.get("key", "").startswith("numeric:") else "conflict" if item.get("key", "").startswith("conflict:") else "queue"


def _key(item):
    return item.get("key") or item["sentence_id"]


def _evidence(root, config, outline, item, ref_text):
    sentence = item["sentence"]
    parts = [f"KIND: {_kind(item).upper()}", f"SENTENCE: {sentence['text']}"]
    if item.get("paragraph"):
        others = [s["text"] for s in item["paragraph"]["sentences"] if s["id"] != sentence["id"]]
        parts.append("PARAGRAPH CONTEXT: " + " ".join(others)[:900])
    if item.get("reason"):
        parts.append(f"WHY FLAGGED: {item['reason']}")
    lines = caption_lines(root, outline, config, sentence)
    parts.append("CITED CAPTIONS:\n" + "\n".join(f"  {line['text']}" for line in lines))
    if _kind(item) == "conflict":
        parts.append("REFERENCE:\n" + "\n---\n".join(ref_text.get(r, r)[:1200] for r in item["refs"]))
    if _kind(item) == "numeric":
        parts.append("EXECUTED REFERENCE CODE:\n" + "\n".join(
            f"  {c['expression']} = {c['value']:g} (the sentence states {c['expected']:g}); judge: {c.get('confirmed_by_judge', '')}"
            for c in item["checks"]))
    return "\n\n".join(parts)


def propose(gateway, root, config, outline, item, ref_text):
    kind = _kind(item)

    def valid(obj):
        errors = []
        if obj.get("decision") not in ALLOWED[kind]:
            errors.append(f"decision must be one of {sorted(ALLOWED[kind])}")
        if obj.get("decision") == "edit" and not str(obj.get("text", "")).strip():
            errors.append("an edit needs text")
        if obj.get("decision") == "note" and not str(obj.get("note", "")).strip():
            errors.append("a note needs note text")
        if obj.get("risk") not in ("low", "high"):
            errors.append("risk must be low or high")
        return errors
    result = gateway.call_json("writer", [{"role": "system", "content": PROMPT.read_text()},
                                          {"role": "user", "content": _evidence(root, config, outline, item, ref_text)}],
                               stage="triage", input_id=_key(item), max_completion_tokens=4000, validate=valid)
    rec = {k: result["parsed"].get(k) for k in ("decision", "text", "note", "reason", "risk")}
    rec = {k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in rec.items() if v}
    if rec["decision"] == "edit":
        rec["check"] = recheck(gateway, root, outline, config, item, rec["text"])
        if rec["check"]["verdict"] not in ("supported", "ok") and kind != "numeric":
            rec["risk"] = "high"  # the checker doubts the proposed edit: the reviewer must look
    return {**rec, "kind": kind, "sentence_hash": sentence_hash(item["sentence"])}


def all_open(root):
    return list(open_items(root)) + list(open_conflicts(root)) + list(open_numeric(root))


def run_triage(root, config, gateway, workers=8):
    from .reference import load_index
    outline = runner.load(root, "outline", "book")
    pack = config.get("reference_pack") or {}
    ref_text = {c["id"]: c["text"] for c in load_index(root, pack)["chunks"]} if pack.get("enabled") else {}
    items = all_open(root)

    def one(item):
        inputs = {"item": digest({"s": item["sentence"], "r": item.get("reason"), "refs": item.get("refs"),
                                  "checks": [(c["expression"], c["value"]) for c in item.get("checks", [])]}),
                  "prompt": digest(PROMPT.read_text()), "v": 1}
        return _key(item), runner.run(root, "triage", _key(item).replace(":", "_"), inputs,
                                      lambda: propose(gateway, root, config, outline, item, ref_text))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        recs = dict(pool.map(one, items))
    write(_recs_path(root), recs)
    return recs


def apply_recommendation(root, item, rec, reviewer):
    """Record the proposal as the reviewer's own decision (the reviewer chose to take it)."""
    kind = _kind(item)
    if kind == "queue":
        return decide(root, item, rec["decision"], reviewer, rec.get("text"), rec.get("check"))
    if kind == "conflict":
        return decide_conflict(root, item, rec["decision"], reviewer, text=rec.get("text"), note=rec.get("note"))
    return decide_numeric(root, item, rec["decision"], reviewer, rec.get("text"), rec.get("check"), rec.get("reason"))


def current_recommendation(recs, item):
    rec = recs.get(_key(item))
    return rec if rec and rec.get("sentence_hash") == sentence_hash(item["sentence"]) else None


def summary(recs):
    counts = {}
    for rec in recs.values():
        counts.setdefault(rec["kind"], {}).setdefault(f"{rec['decision']} ({rec['risk']})", 0)
        counts[rec["kind"]][f"{rec['decision']} ({rec['risk']})"] += 1
    return json.loads(json.dumps(counts))
