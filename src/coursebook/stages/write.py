"""Stage 5: one outline section -> tagged, cited sentences.

Sentence tags (citation contract):
    F  factual     must cite >= 1 caption line from the supplied source lines
    T  technical   like F, may also cite the reference pack (`ref:<path>#L<a>-<b>`)
    C  connective  no claim of its own; no citations (the judge checks this)
    R  roadmap     describes this book's structure; no citations; judged against
                   the outline (allowed only in framing text: intro, openers)
Source lines given to the writer = every 30 s window that contains a line cited
by one of the section's points, in lecture order, tagged with full line IDs.
"""
import re
from pathlib import Path
from ..core import digest
from ..llm import TruncatedOutput
from .. import runner
from .segment import format_lines

PROMPT = Path("prompts/write.txt")
TAGS = {"F", "T", "C", "R"}


def validate_section(obj, allowed_ids, roadmap=False, lenient_cites=False):
    """Structural and tag rules. With lenient_cites, citations outside allowed_ids are
    not errors here; `keep_valid_cites` removes them afterwards and counts them."""
    errors = []
    paragraphs = obj.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        return ["'paragraphs' must be a non-empty list"]
    for p, paragraph in enumerate(paragraphs):
        sentences = paragraph.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            errors.append(f"paragraph {p}: no sentences")
            continue
        for s, sentence in enumerate(sentences):
            where = f"paragraph {p} sentence {s}"
            tag, cites = sentence.get("type"), sentence.get("cites")
            if not str(sentence.get("text", "")).strip():
                errors.append(f"{where}: empty text")
            if tag not in TAGS or (tag == "R" and not roadmap):
                errors.append(f"{where}: type must be F, T or C" + (" or R" if roadmap else ""))
            if not isinstance(cites, list):
                errors.append(f"{where}: cites must be a list")
                continue
            if tag in ("C", "R") and cites:
                errors.append(f"{where}: {'connective' if tag == 'C' else 'roadmap'} sentences must not cite")
            if tag in ("F", "T") and not cites and not lenient_cites:
                errors.append(f"{where}: {tag} sentence needs at least one citation")
            unknown = [c for c in cites if c not in allowed_ids and not str(c).startswith("ref:")]
            if unknown and not lenient_cites:
                errors.append(f"{where}: citations not in the supplied lines: {unknown[:3]}")
            if tag == "F" and any(str(c).startswith("ref:") for c in cites):
                errors.append(f"{where}: F sentences cite captions only; use T for reference-pack claims")
    return errors


def source_lines(segments, line_ids):
    """All lines in the windows that contain any of `line_ids`, in lecture order."""
    wanted, lines = set(line_ids), []
    for video_id in sorted({i.split("@")[0] for i in line_ids}, key=list(segments).index):
        segmented = segments[video_id]
        by_line = {x["id"]: x for x in segmented["lines"]}
        for window in segmented["windows"]:
            if wanted & set(window["line_ids"]):
                lines += [by_line[i] for i in window["line_ids"]]
    return lines


def section_messages(config, chapter, section, neighbours, points, lines):
    point_text = "\n".join(f"- ({p['kind']}, importance {p['importance']}) {p['text']}" for p in points)
    context = (f"Book: {config['title']}\nReader: {config['reader']}\n"
               f"Chapter: {chapter['title']} ({chapter['summary']})\n"
               f"This section: {section['title']}\n"
               f"Previous section: {neighbours[0] or '(start of chapter)'}\n"
               f"Next section: {neighbours[1] or '(end of chapter)'}")
    return [{"role": "system", "content": PROMPT.read_text()},
            {"role": "user", "content": f"{context}\n\nTeaching points to cover:\n{point_text}\n\n"
                                        f"Source caption lines:\n{format_lines(lines, full_ids=True)}"}]


def write_section(gateway, config, chapter, section, neighbours, points, segments):
    lines = source_lines(segments, [i for p in points for i in p["line_ids"]])
    allowed = {x["id"] for x in lines}
    messages = section_messages(config, chapter, section, neighbours, points, lines)
    try:
        result = gateway.call_json("writer", messages, stage="write", input_id=section["id"], max_completion_tokens=32000,
                                   validate=lambda o: validate_section(o, allowed, lenient_cites=True))
        paragraphs, invalid = keep_valid_cites(result["parsed"]["paragraphs"], allowed)
    except TruncatedOutput:
        if len(points) < 2:
            raise
        half = len(points) // 2
        first = write_section(gateway, config, chapter, {**section, "id": section["id"] + "a"}, neighbours, points[:half], segments)
        second = write_section(gateway, config, chapter, {**section, "id": section["id"] + "b"}, neighbours, points[half:], segments)
        paragraphs = first["paragraphs"] + second["paragraphs"]
        invalid = first.get("invalid_citation_sentences", 0) + second.get("invalid_citation_sentences", 0)
    return {"section_id": section["id"], "paragraphs": assign_ids(paragraphs, section["id"]),
            "invalid_citation_sentences": invalid}


TAG_IN_TEXT = re.compile(r"^\s*\[(?:F|T|C|R)\]\s*")
CITE_IN_TEXT = re.compile(r"\s*\[(?:[A-Za-z0-9_-]{6,}@\d+(?:\s*,\s*[A-Za-z0-9_-]{6,}@\d+)*|ref:[^\]]+)\]")  # a citation id typed into the prose


def clean_text(text):
    """Collapse whitespace and drop tags or citation ids the model wrote into the text itself ("[F] ...", "[vid@12]")."""
    return CITE_IN_TEXT.sub("", TAG_IN_TEXT.sub("", " ".join(str(text).split())))


def keep_valid_cites(paragraphs, allowed_ids):
    """Remove invented citations; drop factual sentences left with none. Returns (paragraphs, dropped_count)."""
    out, dropped = [], 0
    for paragraph in paragraphs:
        sentences = []
        for s in paragraph["sentences"]:
            cites = [c for c in s["cites"] if c in allowed_ids or str(c).startswith("ref:")]
            if s["type"] in ("F", "T") and not cites:
                dropped += 1
                continue
            sentences.append({**s, "cites": cites})
        if sentences:
            out.append({**paragraph, "sentences": sentences})
    return out, dropped


def assign_ids(paragraphs, prefix):
    """Stable IDs: <prefix>.pNN for paragraphs and <prefix>.pNN.NN for sentences."""
    out = []
    for p, paragraph in enumerate(paragraphs, 1):
        pid = f"{prefix}.p{p:02d}"
        out.append({"id": pid, "sentences": [
            {"id": f"{pid}.{n:02d}", "text": clean_text(x["text"]), "type": x["type"], "cites": x["cites"]}
            for n, x in enumerate(paragraph["sentences"], 1)]})
    return out


def run_write(root, gateway, config, outline, only=None, workers=4):
    segments, points = {}, {}
    for video_id in outline["lectures"]:
        segments[video_id] = runner.load(root, "segment", video_id)
        for point in runner.load(root, "extract", video_id)["points"]:
            points[point["id"]] = point
    prompt_hash = digest(PROMPT.read_text())
    jobs = []
    for chapter in outline["chapters"]:
        titles = [s["title"] for s in chapter["sections"]]
        for n, section in enumerate(chapter["sections"]):
            if only and not section["id"].startswith(only):
                continue
            neighbours = (titles[n - 1] if n else None, titles[n + 1] if n + 1 < len(titles) else None)
            jobs.append((chapter, section, neighbours))

    def job(args):
        chapter, section, neighbours = args
        section_points = [points[i] for i in section["point_ids"]]
        inputs = {"points": digest(section_points), "section": section, "chapter": chapter["title"],
                  "neighbours": neighbours, "segments": {v: runner.output_hash(root, "segment", v) for v in segments},
                  "prompt": prompt_hash, "title": config["title"], "reader": config["reader"], "v": 1}
        return runner.run(root, "write", section["id"], inputs,
                          lambda: write_section(gateway, config, chapter, section, neighbours, section_points, segments))

    return gateway.map(job, jobs, workers=workers)
