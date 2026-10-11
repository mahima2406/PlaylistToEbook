"""Stage 6: judge every sentence against its cited lines; one rewrite pass; queue the rest.

    section sentences --judge--> verdicts
        all supported/ok and confident  -> done
        otherwise -> rewrite that paragraph (writer) -> judge again
            still failing or low confidence -> review queue (human)
The judge is a different deployment from the writer (plan D11). Confidence routes
work to a person; it is not proof of correctness (cutoff calibrated with plants).
"""
from pathlib import Path
from ..core import digest
from .. import runner
from .segment import format_lines
from .write import validate_section, source_lines, clean_text, keep_valid_cites

JUDGE_PROMPT = Path("prompts/judge.txt")
REWRITE_PROMPT = Path("prompts/rewrite.txt")
FACT_VERDICTS = {"supported", "partial", "unsupported"}
NO_CITE_VERDICTS = {"C": {"ok", "claim_in_connective"}, "R": {"ok", "roadmap_mismatch"}}
CONTEXT_LINES = 2


class LineIndex:
    """Look up caption lines and their neighbours across several lectures."""
    def __init__(self, segments):
        self.lines, self.position = {}, {}
        for segmented in segments.values():
            for n, line in enumerate(segmented["lines"]):
                self.lines[line["id"]] = line
                self.position[line["id"]] = (segmented["video_id"], n, segmented["lines"])

    def context(self, line_ids):
        out, seen = [], set()
        for line_id in line_ids:
            if line_id not in self.position:
                continue
            _, n, lines = self.position[line_id]
            for line in lines[max(0, n - CONTEXT_LINES): n + CONTEXT_LINES + 1]:
                if line["id"] not in seen:
                    seen.add(line["id"])
                    out.append(line)
        return out


def judge_messages(sentences, index, outline_text=None):
    blocks = [f"Book outline (for ROADMAP sentences):\n{outline_text}"] if outline_text else []
    for n, sentence in enumerate(sentences, 1):
        if sentence["type"] in ("C", "R"):
            blocks.append(f"S{n} [{'CONNECTIVE' if sentence['type'] == 'C' else 'ROADMAP'}] {sentence['text']}")
            continue
        cited = [index.lines[c] for c in sentence["cites"] if c in index.lines]
        context = [x for x in index.context(sentence["cites"]) if x["id"] not in set(sentence["cites"])]
        blocks.append(f"S{n} [FACTUAL] {sentence['text']}\n  cited lines:\n{_indent(format_lines(cited, True))}"
                      + (f"\n  context lines:\n{_indent(format_lines(context, True))}" if context else ""))
    return [{"role": "system", "content": JUDGE_PROMPT.read_text()},
            {"role": "user", "content": "\n\n".join(blocks)}]


def _indent(text):
    return "\n".join("    " + line for line in text.splitlines())


def validate_verdicts(obj, sentences):
    verdicts = obj.get("verdicts")
    if not isinstance(verdicts, list):
        return ["'verdicts' must be a list"]
    errors, seen = [], set()
    expected = {f"S{n}": s for n, s in enumerate(sentences, 1)}
    for verdict in verdicts:
        sid = verdict.get("id")
        if sid not in expected:
            errors.append(f"unknown sentence id {sid}")
            continue
        seen.add(sid)
        allowed = NO_CITE_VERDICTS.get(expected[sid]["type"], FACT_VERDICTS)
        if verdict.get("verdict") not in allowed:
            errors.append(f"{sid}: verdict must be one of {sorted(allowed)}")
        confidence = verdict.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"{sid}: confidence must be a number from 0 to 1")
    missing = sorted(set(expected) - seen)
    if missing:
        errors.append(f"missing verdicts for {missing[:10]}")
    return errors


JUDGE_BATCH = 15  # larger batches made gpt-5.2 exceed the 300 s request timeout


def judge(gateway, sentences, index, item, outline_text=None):
    """Verdict per sentence id, judged in batches of JUDGE_BATCH."""
    out = {}
    for start in range(0, len(sentences), JUDGE_BATCH):
        batch = sentences[start:start + JUDGE_BATCH]
        result = gateway.call_json("judge", judge_messages(batch, index, outline_text), stage="judge",
                                   input_id=f"{item}#{start // JUDGE_BATCH}",
                                   validate=lambda o, b=batch: validate_verdicts(o, b), max_completion_tokens=32000)
        by_n = {v["id"]: v for v in result["parsed"]["verdicts"]}
        out.update({s["id"]: {"verdict": by_n[f"S{n}"]["verdict"], "confidence": float(by_n[f"S{n}"]["confidence"]),
                              "reason": by_n[f"S{n}"].get("reason", "")}
                    for n, s in enumerate(batch, 1)})
    return out


def passes(verdict, cutoff):
    return verdict["verdict"] in ("supported", "ok") and verdict["confidence"] >= cutoff


def rewrite_paragraph(gateway, paragraph, verdicts, lines, item, outline_text=None):
    allowed = {x["id"] for x in lines}
    listing = "\n".join(f"- [{s['type']}] {s['text']} | cites: {', '.join(s['cites']) or '-'} | "
                        f"verdict: {verdicts[s['id']]['verdict']} {verdicts[s['id']]['reason']}"
                        for s in paragraph["sentences"])
    messages = [{"role": "system", "content": REWRITE_PROMPT.read_text()},
                {"role": "user", "content": (f"Book outline:\n{outline_text}\n\n" if outline_text else "")
                                            + f"Paragraph with fact-check results:\n{listing}\n\n"
                                            f"Source caption lines:\n{format_lines(lines, full_ids=True)}"}]
    result = gateway.call_json("writer", messages, stage="rewrite", input_id=item, max_completion_tokens=16000,
                               validate=lambda o: validate_section(o, allowed, roadmap=bool(outline_text), lenient_cites=True))
    paragraphs, _ = keep_valid_cites(result["parsed"]["paragraphs"], allowed)
    sentences = [s for p in paragraphs for s in p["sentences"]]
    return {"id": paragraph["id"], "sentences": [
        {"id": f"{paragraph['id']}.r{n:02d}", "text": clean_text(s["text"]), "type": s["type"], "cites": s["cites"]}
        for n, s in enumerate(sentences, 1)]}


def verify_section(gateway, written, segments, index, cutoff, outline_text=None):
    """Judge, rewrite failing paragraphs once, re-judge, queue what still fails.
    `outline_text` is supplied for framing text that may contain ROADMAP sentences."""
    section_id = written["section_id"]
    all_sentences = [s for p in written["paragraphs"] for s in p["sentences"]]
    verdicts = judge(gateway, all_sentences, index, section_id, outline_text)
    lines = source_lines(segments, sorted({c for s in all_sentences for c in s["cites"] if c in index.lines},
                                          key=lambda c: (list(segments).index(c.split("@")[0]), index.lines[c]["start"])))
    final, rewritten, queue, first_pass = [], [], [], dict(verdicts)
    for paragraph in written["paragraphs"]:
        if all(passes(verdicts[s["id"]], cutoff) for s in paragraph["sentences"]):
            final.append(paragraph)
            continue
        revised = rewrite_paragraph(gateway, paragraph, verdicts, lines, paragraph["id"], outline_text)
        revised_verdicts = judge(gateway, revised["sentences"], index, paragraph["id"] + ":rejudge", outline_text)
        verdicts.update(revised_verdicts)
        rewritten.append(paragraph["id"])
        final.append(revised)
        for sentence in revised["sentences"]:
            v = revised_verdicts[sentence["id"]]
            if not passes(v, cutoff):
                queue.append({"sentence_id": sentence["id"], "text": sentence["text"], "cites": sentence["cites"],
                              **v, "status": "open"})
    final_ids = {s["id"] for p in final for s in p["sentences"]}
    return {"section_id": section_id, "paragraphs": final,
            "verdicts": {k: v for k, v in verdicts.items() if k in final_ids},
            "first_pass": first_pass, "rewritten": rewritten, "queue": queue}


def run_verify(root, gateway, config, outline, only=None, workers=4):
    segments = {v: runner.load(root, "segment", v) for v in outline["lectures"]}
    index = LineIndex(segments)
    cutoff = config.get("verify", {}).get("confidence_cutoff", 0.7)
    prompts = {"judge": digest(JUDGE_PROMPT.read_text()), "rewrite": digest(REWRITE_PROMPT.read_text())}
    sections = [s for c in outline["chapters"] for s in c["sections"] if not only or s["id"].startswith(only)]

    def job(section):
        written = runner.load(root, "write", section["id"])
        if written is None:
            raise ValueError(f"{section['id']}: run write first")
        inputs = {"write": runner.output_hash(root, "write", section["id"]), "prompts": prompts,
                  "cutoff": cutoff, "v": 1}
        return runner.run(root, "verify", section["id"], inputs,
                          lambda: verify_section(gateway, written, segments, index, cutoff))

    return gateway.map(job, sections, workers=workers)
