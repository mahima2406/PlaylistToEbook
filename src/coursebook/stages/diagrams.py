"""Concept diagrams: Mermaid flowcharts proposed from fact-checked chapter text.

    verified paragraphs ──writer──> {after_paragraph, title, caption, mermaid, claims[]}
        mermaid passes the safety/shape validator?
        every claim (one per arrow or grouping) judged "supported" against its cites?
            yes -> kept, rendered as a vector figure after that paragraph
            no  -> dropped, with the failing claims recorded in the report
Each claim names the checked sentences it restates; its citations are copied
from those sentences, never chosen by the model. Failing claims get one repair
pass (the generator removes or narrows them), then the diagram is judged again.
Diagrams may only show what the checked prose already supports (reverse
validation: the picture is turned back into sentences and judged).
"""
import json
import re
from pathlib import Path
from ..core import digest
from .. import runner
from .verify import LineIndex, judge, passes, JUDGE_PROMPT

PROMPT = Path("prompts/diagram.txt")
MAX_NODES = 12
FORBIDDEN = re.compile(r"%%|click\s|<|>(?!\|)|style\s|classDef|linkStyle|javascript:", re.I)


def validate_mermaid(source):
    lines = [l for l in str(source).strip().splitlines() if l.strip()]
    if not lines or not re.fullmatch(r"flowchart (LR|TD|TB|RL)", lines[0].strip()):
        return ['mermaid must start with "flowchart LR" or "flowchart TD"']
    errors = []
    for n, line in enumerate(lines[1:], 2):
        body = line.replace("-->", "").replace("---", "").replace("-.->", "")
        if FORBIDDEN.search(body):
            errors.append(f"mermaid line {n}: styling, HTML, comments or click handlers are not allowed")
        if line.count('"') % 2:
            errors.append(f"mermaid line {n}: unbalanced double quotes")
    nodes = set(re.findall(r"\b([A-Za-z]\w*)\s*[\[\(\{]", source))
    if len(nodes) > MAX_NODES:
        errors.append(f"mermaid has {len(nodes)} nodes; at most {MAX_NODES}")
    if not nodes:
        errors.append("mermaid defines no labelled nodes")
    return errors


def validate_diagrams(obj, paragraph_ids, sentence_ids, limit):
    diagrams = obj.get("diagrams")
    if not isinstance(diagrams, list):
        return ["'diagrams' must be a list"]
    errors = [f"at most {limit} diagrams"] if len(diagrams) > limit else []
    for n, d in enumerate(diagrams):
        where = f"diagram {n}"
        if d.get("after_paragraph") not in paragraph_ids:
            errors.append(f"{where}: after_paragraph must be one of the supplied paragraph IDs")
        if not str(d.get("title", "")).strip() or not str(d.get("caption", "")).strip():
            errors.append(f"{where}: title and caption are required")
        errors += [f"{where}: {e}" for e in validate_mermaid(d.get("mermaid", ""))]
        claims = d.get("claims")
        if not isinstance(claims, list) or not claims:
            errors.append(f"{where}: list every relationship the diagram shows in 'claims'")
            continue
        for c in claims:
            if not c.get("sentences") or not set(c["sentences"]) <= sentence_ids:
                errors.append(f"{where}: claim '{str(c.get('text'))[:40]}' must name supplied sentence IDs")
    return errors


def diagram_chapter(gateway, chapter, verified, index, cutoff, limit):
    paragraphs = [p for v in verified for p in v["paragraphs"]]
    sentences = {s["id"]: s for p in paragraphs for s in p["sentences"] if s["type"] == "F"}
    listing = "\n\n".join(f"{p['id']}:\n" + "\n".join(f"  {s['id']} | {s['text']}" for s in p["sentences"] if s["type"] == "F")
                          for p in paragraphs)
    base = [{"role": "system", "content": PROMPT.read_text().replace("{max}", str(limit))},
            {"role": "user", "content": f"Chapter: {chapter['title']}\n\nSentences:\n{listing}"}]
    check = lambda o, n=limit: validate_diagrams(o, {p["id"] for p in paragraphs}, set(sentences), n)
    proposed = gateway.call_json("writer", base, stage="diagram", input_id=chapter["id"],
                                 max_completion_tokens=16000, validate=check)["parsed"]["diagrams"]
    kept, dropped = [], []
    for n, proposal in enumerate(proposed, 1):
        did = f"{chapter['id']}.fig{n}"
        record = _judge_diagram(gateway, did, proposal, sentences, index, cutoff)
        if not record["passed"]:
            failing = [c for c in record["claims"] if not passes(c, cutoff)]
            ask = base + [{"role": "assistant", "content": json.dumps({"diagrams": [proposal]})},
                          {"role": "user", "content": "Revise this diagram after the fact-check. Failing claims:\n"
                           + "\n".join(f"- {c['text']}: {c['verdict']} ({c['reason']})" for c in failing)}]
            revised = gateway.call_json("writer", ask, stage="diagram", input_id=did + ":repair",
                                        max_completion_tokens=16000, validate=lambda o: check(o, 1))["parsed"]["diagrams"]
            if revised:
                record = {**_judge_diagram(gateway, did, revised[0], sentences, index, cutoff), "repaired": True,
                          "first_attempt": record["claims"]}
        (kept if record["passed"] else dropped).append(record)
    return {"chapter": chapter["id"], "diagrams": kept, "dropped": dropped}


def _judge_diagram(gateway, did, proposal, sentences, index, cutoff):
    claims = [{"id": f"{did}.c{k}", "type": "F", "text": c["text"], "sentences": c["sentences"],
               "cites": sorted({cite for sid in c["sentences"] for cite in sentences[sid]["cites"]})}
              for k, c in enumerate(proposal["claims"], 1)]
    verdicts = judge(gateway, claims, index, did)
    claims = [{**c, **verdicts[c["id"]]} for c in claims]
    return {"id": did, "after_paragraph": proposal["after_paragraph"], "title": proposal["title"],
            "caption": proposal["caption"], "mermaid": proposal["mermaid"].strip(), "claims": claims,
            "passed": all(passes(c, cutoff) for c in claims)}


def run_diagrams(root, gateway, config, outline, workers=4):
    settings = config.get("diagrams", {})
    if not settings.get("enabled", True):
        return []
    limit = settings.get("per_chapter", 3)
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)
    index = LineIndex({v: runner.load(root, "segment", v) for v in outline["lectures"]})

    def job(chapter):
        verified = [runner.load(root, "verify", s["id"]) for s in chapter["sections"]]
        inputs = {"verify": [runner.output_hash(root, "verify", s["id"]) for s in chapter["sections"]],
                  "prompt": digest(PROMPT.read_text()), "judge": digest(JUDGE_PROMPT.read_text()),
                  "limit": limit, "cutoff": cutoff, "v": 2}
        return runner.run(root, "diagrams", chapter["id"], inputs,
                          lambda: diagram_chapter(gateway, chapter, verified, index, cutoff, limit))

    return gateway.map(job, outline["chapters"], workers=workers)
