"""Human review of queued sentences: accept, edit (re-checked) or remove.

    queue (verify / frame / takeaways)  ──>  data/reviews/decisions.json
        {sentence_id: {decision, text?, reviewer, at, sentence_hash, check?}}
A decision applies only while `sentence_hash` matches the sentence it was made
on; if the pipeline rewrites that sentence, the decision is stale and the item
reopens. Edited text is judged again against the same citations, and the result
is shown and stored; the reviewer may keep an edit the checker doubts, and that
override is recorded (the human decides, the record shows it).
"""
import time
from pathlib import Path
from . import runner
from .core import digest, read, write

STAGES = ("verify", "frame", "takeaways")


def _path(root):
    return Path(root) / "reviews" / "decisions.json"


def load_decisions(root):
    path = _path(root)
    return read(path) if path.exists() else {}


def sentence_hash(sentence):
    return digest({"text": sentence["text"], "cites": sentence["cites"]})


def queue_items(root):
    """Every queued sentence, with the unit it lives in and its paragraph."""
    items = []
    for stage in STAGES:
        base = Path(root) / "stages" / stage
        for path in sorted(base.glob("*.json")) if base.exists() else []:
            unit = read(path)["output"]
            paragraphs = {s["id"]: p for p in unit["paragraphs"] for s in p["sentences"]}
            for q in unit["queue"]:
                paragraph = paragraphs.get(q["sentence_id"])
                if paragraph is None:
                    continue
                sentence = next(s for s in paragraph["sentences"] if s["id"] == q["sentence_id"])
                items.append({**q, "stage": stage, "unit": unit["section_id"], "sentence": sentence,
                              "paragraph": paragraph})
    return items


def after_conflict(sentence, decisions):
    """The sentence as apply_decisions sees it when its sentence-level decision is checked
    (a reviewer's conflict edit is applied first)."""
    conflict = decisions.get("conflict:" + sentence["id"])
    if conflict and conflict["sentence_hash"] == sentence_hash(sentence) and conflict["decision"] == "edit":
        return {**sentence, "text": conflict["text"], "reviewed": True}
    return sentence


def is_decided(item, decisions):
    decision = decisions.get(item["sentence_id"])
    return bool(decision) and decision["sentence_hash"] in (sentence_hash(item["sentence"]),
                                                            sentence_hash(after_conflict(item["sentence"], decisions)))


def open_items(root):
    decisions = load_decisions(root)
    return [i for i in queue_items(root) if not is_decided(i, decisions)]


def conflict_items(root):
    """Material lecture-vs-reference contradictions found by the cross-check stage."""
    items = []
    base = Path(root) / "stages" / "crosscheck"
    for path in sorted(base.glob("*.json")) if base.exists() else []:
        record = read(path)["output"]
        unit = read(Path(root) / "stages" / "verify" / path.name)["output"]
        sentences = {s["id"]: s for p in unit["paragraphs"] for s in p["sentences"]}
        for c in record["conflicts"]:
            if c["sentence_id"] in sentences:
                items.append({**c, "sentence": sentences[c["sentence_id"]], "key": "conflict:" + c["sentence_id"]})
    return items


def open_conflicts(root):
    decisions = load_decisions(root)
    return [c for c in conflict_items(root)
            if decisions.get(c["key"], {}).get("sentence_hash") != sentence_hash(c["sentence"])]


def decide_conflict(root, item, decision, reviewer, text=None, note=None):
    """keep = follow the lecture; note = show both (note printed); edit = reviewer rewrites the sentence."""
    if decision not in ("keep", "note", "edit"):
        raise ValueError("decision must be keep, note or edit")
    if decision == "edit" and not (text or "").strip():
        raise ValueError("an edit needs the new text")
    decisions = load_decisions(root)
    decisions[item["key"]] = {"decision": decision, "reviewer": reviewer, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "sentence_hash": sentence_hash(item["sentence"]), "original": item["sentence"]["text"],
                              "refs": item["refs"], **({"text": " ".join(text.split())} if decision == "edit" else {}),
                              **({"note": " ".join((note or item["reason"]).split())} if decision == "note" else {})}
    write(_path(root), decisions)
    return decisions[item["key"]]


def decide(root, item, decision, reviewer, text=None, check=None):
    if decision not in ("accept", "edit", "remove"):
        raise ValueError("decision must be accept, edit or remove")
    if decision == "edit" and not (text or "").strip():
        raise ValueError("an edit needs the new text")
    decisions = load_decisions(root)
    decisions[item["sentence_id"]] = {"decision": decision, "reviewer": reviewer,
                                      "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                      "sentence_hash": sentence_hash(item["sentence"]),
                                      "original": item["sentence"]["text"],
                                      **({"text": " ".join(text.split())} if decision == "edit" else {}),
                                      **({"check": check} if check else {})}
    write(_path(root), decisions)
    return decisions[item["sentence_id"]]


def apply_decisions(unit, decisions):
    """Return a copy of a verified unit with current review decisions applied."""
    paragraphs = []
    for paragraph in unit["paragraphs"]:
        sentences = []
        for sentence in paragraph["sentences"]:
            conflict = decisions.get("conflict:" + sentence["id"])
            if conflict and conflict["sentence_hash"] == sentence_hash(sentence):
                if conflict["decision"] == "edit":
                    sentence = {**sentence, "text": conflict["text"], "reviewed": True}
                elif conflict["decision"] == "note":
                    sentence = {**sentence, "note": conflict["note"]}
            decision = decisions.get(sentence["id"])
            if not decision or decision["sentence_hash"] != sentence_hash(sentence):
                sentences.append(sentence)
            elif decision["decision"] == "accept":
                sentences.append(sentence)
            elif decision["decision"] == "edit":
                sentences.append({**sentence, "text": decision["text"], "reviewed": True})
        if sentences:
            paragraphs.append({**paragraph, "sentences": sentences})
    return {**unit, "paragraphs": paragraphs}


def recheck(gateway, root, outline, config, item, text):
    """Judge edited text against the original citations (and outline for roadmap sentences)."""
    from .stages.frame import _context, outline_text
    from .stages.verify import judge
    _, index, _ = _context(root, config, outline)
    sentence = {**item["sentence"], "id": item["sentence_id"] + ":edit", "text": text}
    verdict = judge(gateway, [sentence], index, item["sentence_id"] + ":review",
                    outline_text(outline) if sentence["type"] == "R" else None)
    return verdict[sentence["id"]]


def caption_lines(root, outline, config, sentence):
    from .stages.frame import _context
    _, index, _ = _context(root, config, outline)
    return [index.lines[c] for c in sentence["cites"] if c in index.lines]


def _show_rec(show, rec):
    if not rec:
        return
    extra = (f' -> "{rec["text"]}"' if rec.get("text") else "") + (f' (note: "{rec["note"]}")' if rec.get("note") else "")
    check = f'  [checker on it: {rec["check"]["verdict"]} {rec["check"]["confidence"]:.2f}]' if rec.get("check") else ""
    show(f"\nRECOMMENDED ({rec['risk']} risk): {rec['decision'].upper()}{extra}{check}\n  why: {rec['reason']}")


def take_low_risk(root, reviewer, show=print):
    """Apply every current low-risk recommendation as the reviewer's decision. Returns how many."""
    from .triage import all_open, apply_recommendation, current_recommendation, load_recommendations
    recs, made = load_recommendations(root), 0
    for item in all_open(root):
        rec = current_recommendation(recs, item)
        if rec and rec["risk"] == "low":
            apply_recommendation(root, item, rec, reviewer)
            made += 1
    show(f"Took {made} low-risk recommendations as {reviewer}'s decisions; {len(all_open(root))} items still open.")
    return made


def interactive(root, config, gateway, reviewer, ask=input, show=print, only_high=False):
    """Walk through open items one by one (Enter takes the recommendation). Returns the number of decisions made."""
    from .stages.verify import passes
    from .triage import apply_recommendation, current_recommendation, load_recommendations, open_numeric
    recs = load_recommendations(root)
    outline = runner.load(root, "outline", "book")
    items = open_items(root)
    if only_high:
        items = [i for i in items if (current_recommendation(recs, i) or {}).get("risk") != "low"]
    if not items and not open_conflicts(root) and not open_numeric(root):
        show("Review queue is empty.")
        return 0
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)
    made = 0
    for n, item in enumerate(items, 1):
        sentence = item["sentence"]
        show("\n" + "=" * 78)
        show(f"[{n}/{len(items)}] {item['sentence_id']}  ({item['stage']}, checker: {item['verdict']}, "
             f"confidence {item['confidence']:.2f})")
        show(f"\nSENTENCE: {sentence['text']}")
        show(f"\nWHY FLAGGED: {item['reason'] or '-'}")
        others = [s["text"] for s in item["paragraph"]["sentences"] if s["id"] != sentence["id"]]
        if others:
            show("\nPARAGRAPH CONTEXT: " + " ".join(others)[:600])
        lines = caption_lines(root, outline, config, sentence)
        if lines:
            show("\nCITED CAPTIONS:")
            for line in lines:
                show(f"  {int(line['start']) // 60}:{int(line['start']) % 60:02d}  {line['text']}")
            show(f"  video: https://www.youtube.com/watch?v={lines[0]['video_id']}&t={int(lines[0]['start'])}s")
        rec = current_recommendation(recs, item)
        _show_rec(show, rec)
        while True:
            choice = ask(f"\n{'[Enter] take recommendation  ' if rec else ''}[a]ccept  [e]dit  [r]emove  [s]kip  [q]uit > ").strip().lower()[:1]
            if choice == "q":
                return made
            if choice == "s":
                break
            if choice == "" and rec:
                apply_recommendation(root, item, rec, reviewer)
            elif choice == "a":
                decide(root, item, "accept", reviewer)
            elif choice == "r":
                decide(root, item, "remove", reviewer)
            elif choice == "e":
                text = ask("New sentence: ").strip()
                if not text:
                    continue
                check = recheck(gateway, root, outline, config, item, text)
                show(f"checker on your edit: {check['verdict']} ({check['confidence']:.2f}) {check['reason']}")
                if not passes(check, cutoff) and ask("Keep this edit anyway? [y/N] ").strip().lower() != "y":
                    continue
                decide(root, item, "edit", reviewer, text, check)
            else:
                continue
            made += 1
            break
    conflicts = open_conflicts(root)
    if only_high:
        conflicts = [c for c in conflicts if (current_recommendation(recs, c) or {}).get("risk") != "low"]
    for n, item in enumerate(conflicts, 1):
        show("\n" + "=" * 78)
        show(f"[conflict {n}/{len(conflicts)}] {item['sentence_id']}: the reference disagrees")
        show(f"\nBOOK SAYS: {item['sentence']['text']}\n\nWHY IT CONFLICTS: {item['reason']}")
        show("\nREFERENCE: " + ", ".join(item["refs"]))
        rec = current_recommendation(recs, item)
        _show_rec(show, rec)
        while True:
            choice = ask(f"\n{'[Enter] take recommendation  ' if rec else ''}[k]eep lecture  [n]ote both  [e]dit  [s]kip  [q]uit > ").strip().lower()[:1]
            if choice == "q":
                return made
            if choice == "s":
                break
            if choice == "" and rec:
                apply_recommendation(root, item, rec, reviewer)
            elif choice == "k":
                decide_conflict(root, item, "keep", reviewer)
            elif choice == "n":
                note = ask("Note to print (Enter = checker's reason): ").strip()
                decide_conflict(root, item, "note", reviewer, note=note or None)
            elif choice == "e":
                text = ask("New sentence: ").strip()
                if not text:
                    continue
                decide_conflict(root, item, "edit", reviewer, text=text)
            else:
                continue
            made += 1
            break
    from .triage import decide_numeric
    for n, item in enumerate(open_numeric(root), 1):
        show("\n" + "=" * 78)
        show(f"[number {n}] {item['sentence_id']}: the text disagrees with the executed reference code")
        show(f"\nBOOK SAYS: {item['sentence']['text']}")
        for c in item["checks"]:
            show(f"  code: {c['expression']} = {c['value']:g}   (text says {c['expected']:g})")
        rec = current_recommendation(recs, item)
        _show_rec(show, rec)
        while True:
            choice = ask(f"\n{'[Enter] take recommendation  ' if rec else ''}[e]dit  [d]ismiss check  [s]kip  [q]uit > ").strip().lower()[:1]
            if choice == "q":
                return made
            if choice == "s":
                break
            if choice == "" and rec:
                apply_recommendation(root, item, rec, reviewer)
            elif choice == "e":
                text = ask("New sentence: ").strip()
                if not text:
                    continue
                decide_numeric(root, item, "edit", reviewer, text, recheck(gateway, root, outline, config, item, text))
            elif choice == "d":
                reason = ask("Why the check does not apply: ").strip()
                if not reason:
                    continue
                decide_numeric(root, item, "dismiss", reviewer, reason=reason)
            else:
                continue
            made += 1
            break
    remaining = len(open_items(root)) + len(open_conflicts(root)) + len(open_numeric(root))
    show(f"\nDone: {made} decisions; {remaining} still open.")
    return made
