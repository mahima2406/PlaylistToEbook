"""Render: verified text -> Quarto book (PDF via LaTeX) + evaluation report.

Chapter layout: opener -> "At a glance" box -> sections (diagrams after the
paragraph they illustrate) -> "Key takeaways" box. Reads only verified text,
the outline, extraction inventories, diagrams and plant results; never plant text. Each paragraph gets one margin source key, e.g.
"L08 1:06-1:38, 43:14", whose times link to that second of the video. The book
is marked DRAFT, with the reasons listed, until every release condition holds.

Reading layout: each chapter opens with one "Based on" line naming its lectures;
paragraphs carry no inline references. Sentence-level citations stay in the data
(and are what the checker judged); the Sources appendix lists, per section, the
lecture time ranges it draws on, linked to the video.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from . import runner
from .core import read, write
from .stages.outline import approval_is_current

ESCAPE = set("\\`*_{}[]<>#$~^|@")


def md(text):
    return "".join("\\" + ch if ch in ESCAPE else ch for ch in text)


def clock(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def source_key(cites, lines, label):
    """Group cited lines per lecture and merge times within 60 s into ranges."""
    per_video = {}
    for cite in cites:
        line = lines.get(cite)
        if line:
            per_video.setdefault(line["video_id"], []).append(line)
    parts = []
    for video_id, video_lines in per_video.items():
        video_lines.sort(key=lambda x: x["start"])
        ranges = [[video_lines[0], video_lines[0]]]
        for line in video_lines[1:]:
            if line["start"] - ranges[-1][1]["start"] <= 60:
                ranges[-1][1] = line
            else:
                ranges.append([line, line])
        links = []
        for first, last in ranges:
            text = clock(first["start"]) + ("" if last is first else f"–{clock(last['start'])}")
            links.append(f"[{text}](https://www.youtube.com/watch?v={video_id}&t={int(first['start'])}s)")
        parts.append(f"{label[video_id]} " + ", ".join(links))
    return " · ".join(parts)


def collect(root, outline):
    """Verified units keyed by id: sections, 'intro', '<ch>.open', '<ch>.take'."""
    units = {s["id"]: runner.load(root, "verify", s["id"]) for c in outline["chapters"] for s in c["sections"]}
    missing = [k for k, v in units.items() if v is None]
    if missing:
        raise ValueError(f"Sections not verified yet: {missing[:5]}")
    for key, stage, item in [("intro", "frame", "intro")] + [
            (f"{c['id']}.{kind}", stage, c["id"]) for c in outline["chapters"]
            for kind, stage in (("open", "frame"), ("take", "takeaways"))]:
        unit = runner.load(root, stage, item)
        if unit:
            units[key] = unit
    plants = [runner.load(root, "plants", c["id"]) for c in outline["chapters"]]
    diagrams = {c["id"]: runner.load(root, "diagrams", c["id"]) for c in outline["chapters"]}
    extracts = {v: runner.load(root, "extract", v) for v in outline["lectures"]}
    return units, [p for p in plants if p], {k: v for k, v in diagrams.items() if v}, extracts


def metrics(sections, plants, extracts, outline, diagrams=None):
    factual_final = [v for s in sections.values() for k, v in s["verdicts"].items()
                     if v["verdict"] in ("supported", "partial", "unsupported")]
    factual_first = [v for s in sections.values() for v in s["first_pass"].values()
                     if v["verdict"] in ("supported", "partial", "unsupported")]
    queue = [q for s in sections.values() for q in s["queue"]]
    points = [p for e in extracts.values() for p in e["points"]]
    placed = {i for c in outline["chapters"] for s in c["sections"] for i in s["point_ids"]}
    by_type = {}
    for chapter in plants:
        for t, n in chapter["by_type"].items():
            by_type.setdefault(t, {"planted": 0, "caught": 0})
            by_type[t]["planted"] += n["planted"]
            by_type[t]["caught"] += n["caught"]
    words = sum(len(x["text"].split()) for s in sections.values() for p in s["paragraphs"] for x in p["sentences"])
    return {
        "words": words,
        "sections": len(sections),
        "factual_sentences": len(factual_final),
        "support_rate_first_pass": _rate(factual_first),
        "support_rate_final": _rate(factual_final),
        "paragraphs_rewritten": sum(len(s["rewritten"]) for s in sections.values()),
        "review_queue_open": sum(q["status"] == "open" for q in queue),
        "plants_planted": sum(c["planted"] for c in plants),
        "plants_caught": sum(c["caught"] for c in plants),
        "plants_by_type": by_type,
        "plant_misses": [{"type": p["type"], "text": p["text"], "confidence": p["confidence"]}
                         for c in plants for p in c["plants"] if not p["caught"]],
        "real_sentences_flagged_in_plant_run": sum(c["decoys_flagged"] for c in plants),
        "real_sentences_in_plant_run": sum(len(c["decoys"]) for c in plants),
        "points_extracted": len(points),
        "points_placed": len(placed),
        "points_dropped": len(outline["dropped"]),
        "points_auto_placed": len(outline.get("auto_placed", [])),
        "core_points_dropped": sum(1 for d in outline["dropped"]
                                   if next(p for p in points if p["id"] == d["point_id"])["importance"] == 3),
        "chunks_without_points": [i["chunk"] for e in extracts.values() for i in e["inventory"] if i["flag"]],
        "diagrams_kept": sum(len(d["diagrams"]) for d in (diagrams or {}).values()),
        "diagrams_dropped": sum(len(d["dropped"]) for d in (diagrams or {}).values()),
    }


def _rate(verdicts):
    return round(sum(v["verdict"] == "supported" for v in verdicts) / len(verdicts), 4) if verdicts else None


def draft_reasons(root, m, missing_lectures):
    reasons = []
    if not approval_is_current(root):
        reasons.append("the outline has not been approved by a reviewer")
    if m["review_queue_open"]:
        reasons.append(f"{m['review_queue_open']} sentences are waiting in the review queue")
    if (m.get("code_run") or {}).get("checks_failed"):
        reasons.append(f"{m['code_run']['checks_failed']} numbers in the text disagree with running the code")
    if m.get("reference_conflicts_open"):
        reasons.append(f"{m['reference_conflicts_open']} conflicts with the reference are waiting for the reviewer")
    if m["plants_planted"] == 0:
        reasons.append("the planted-claim test has not been run")
    evaluation = runner.load(root, "evaluation", "book")
    if evaluation is None:
        reasons.append("the evaluator agent has not run")
    elif not evaluation["passed"]:
        failed = [k.replace("_", " ") for k, ok in evaluation["checks"].items() if not ok]
        reasons.append("evaluator agent checks failed: " + ", ".join(failed))
    if missing_lectures:
        reasons.append(f"{len(missing_lectures)} lectures of the playlist are not covered")
    return reasons


def paragraph_md(paragraph):
    from .stages.write import clean_text
    return " ".join(md(clean_text(s["text"])) for s in paragraph["sentences"])


def unit_cites(*units):
    return [c for u in units if u for p in u["paragraphs"] for s in p["sentences"] for c in s["cites"]]


def based_on(cites, lines, titles, label):
    videos = []
    for cite in cites:
        line = lines.get(cite)
        if line and line["video_id"] not in videos:
            videos.append(line["video_id"])
    videos.sort(key=lambda v: label[v])
    return "; ".join(f"[{label[v]}: {md(titles[v])}](https://www.youtube.com/watch?v={v})" for v in videos)


def box(title, paragraphs):
    items = [f"- {paragraph_md(p)}" for p in paragraphs]
    return [f"::: {{.callout-note appearance=\"simple\" icon=false}}", f"## {title} {{.unnumbered .unlisted}}", "", *items, ":::", ""]


def figure(diagram, figures_dir):
    """Book sources always reference figures/<hash>.pdf and keep the Mermaid source next to it;
    the PDF step draws the vector file. Sources are therefore identical on every machine."""
    from .core import digest
    name = digest(diagram["mermaid"].strip())[:16]
    if figures_dir:
        Path(figures_dir).mkdir(parents=True, exist_ok=True)
        (Path(figures_dir) / f"{name}.mmd").write_text(diagram["mermaid"].strip())
    label_id = "fig-" + diagram["id"].replace(".", "-")
    return [f"![{md(diagram['caption'])}](figures/{name}.pdf){{#{label_id} width=85%}}", ""]


def listing_md(listing, pack, number, run=None):
    note = " (excerpt)" if listing["truncated"] else ""
    out = [f"*Listing {number}{note}: {md(listing['caption'])} Source: {md(pack.get('name', 'reference'))}, "
           f"`{listing['path']}`, {md(pack.get('license', ''))}, commit {pack.get('commit', '')[:7]}.*", "",
           "```python", listing["code"], "```", ""]
    if run and run["status"] == "ran":
        if run["output"]:
            out += ["*Output (executed):*", "", "```text", "\n".join(run["output"].splitlines()[-15:]), "```", ""]
        for c in run["checks"]:
            mark = "✓" if c["passed"] else "✗"
            out.append(f"- {mark} *Checked by running the code:* `{c['expression']}` = {c['value']:g} "
                       f"(the text says {c['expected']:g})" if c["value"] is not None else
                       f"- ✗ *Check could not run:* `{c['expression']}`")
        out += [""] if run["checks"] else []
    elif run:
        out += [f"*Not executed: {run['status']}.*", ""]
    return out


def notes_md(paragraph):
    notes = [s["note"] for s in paragraph["sentences"] if s.get("note")]
    return [f"> **Note.** The course's reference code differs here: {md(n)}" for n in notes] + ([""] if notes else [])


QUOTE_WORDS = 25  # private data mode: at most this many words of caption text per popover


def source_note(paragraph, lines, label):
    """HTML popover body: timestamped links for the cited lines plus a short quote (when captions are local)."""
    cites = [c for s in paragraph["sentences"] for c in s["cites"]]
    if not cites:
        return None
    key = source_key(cites, lines, label)
    words, quoted = [], []
    for c in cites:
        text = (lines.get(c) or {}).get("text")
        if not text or c in quoted:
            continue
        quoted.append(c)
        words += text.split()
        if len(words) >= QUOTE_WORDS:
            break
    quote = " ".join(words[:QUOTE_WORDS])
    return key + (f" — “{md(quote)}{'…' if len(words) > QUOTE_WORDS else ''}”" if quote else "")


def board_md(frame, label, web, figures_dir):
    """A figure redrawn from the lecture's screen/whiteboard, captioned with its moment."""
    when = f"{label.get(frame['video_id'], '')} {clock(frame['seconds'])}"
    link = f"https://www.youtube.com/watch?v={frame['video_id']}&t={frame['seconds']}s"
    caption = f"{md(frame['caption'])} Redrawn from the board in [{when}]({link})."
    if frame["kind"] == "equation":
        return ["$$", frame["latex"].strip(), "$$", "", f"*{caption}*", ""]
    if web:
        return ["```{mermaid}", f'%%| fig-cap: "{md(frame["caption"]).replace(chr(34), chr(39))} (redrawn from the board, {when})"',
                frame["mermaid"].strip(), "```", ""]
    return figure({"id": "board-" + frame["point_id"].replace(":", "-"), "mermaid": frame["mermaid"],
                   "caption": f"{frame['caption']} Redrawn from the board in {when}."}, figures_dir)


def chapter_md(chapter, units, diagrams, lines, label, titles, figures_dir=None, listings=None, pack=None, web=False,
               runs=None, boards=None):
    """One chapter. web=True: each paragraph gets a hover footnote with its sources; Mermaid drawn in the browser."""
    out = [f"# {md(chapter['title'])}", ""]

    def para(paragraph):
        text = paragraph_md(paragraph)
        note = source_note(paragraph, lines, label) if web else None
        if not note:
            return [text, ""]
        ref = "src-" + paragraph["id"].replace(".", "-")
        return [f"{text}[^{ref}]", "", f"[^{ref}]: {note}", ""]
    sources = based_on(unit_cites(*[units[s["id"]] for s in chapter["sections"]]), lines, titles, label)
    if sources:
        out += [f"*Based on {sources}.*", ""]
    opener = units.get(f"{chapter['id']}.open")
    if opener:
        out += [paragraph_md(p) + "\n" for p in opener["opener"]]
        out += box("At a glance", opener["at_a_glance"])
    else:
        out += [f"*{md(chapter['summary'])}*", ""]
    figures = {}
    for d in (diagrams.get(chapter["id"]) or {}).get("diagrams", []):
        figures.setdefault(d["after_paragraph"], []).append(d)
    for section in chapter["sections"]:
        out += [f"## {md(section['title'])}", ""]
        for paragraph in units[section["id"]]["paragraphs"]:
            out += para(paragraph)
            out += notes_md(paragraph)
            for frame in (boards or {}).get(paragraph["id"], []):
                out += board_md(frame, label, web, figures_dir)
            for d in figures.get(paragraph["id"], []):
                out += (["```{mermaid}", f"%%| label: fig-{d['id'].replace('.', '-')}",
                         f'%%| fig-cap: "{md(d["caption"]).replace(chr(34), chr(39))}"', d["mermaid"].strip(), "```", ""]
                        if web else figure(d, figures_dir))
        for k, listing in enumerate((listings or {}).get(section["id"], []), 1):
            out += listing_md(listing, pack or {}, f"{section['id'].replace('ch', '').replace('.s', '.')}.{k}",
                              (runs or {}).get(listing["id"]))
    takeaways = units.get(f"{chapter['id']}.take")
    if takeaways:
        out += box("Key takeaways", takeaways["paragraphs"])
    return "\n".join(out)


def build_book(root, config, destination):
    root, destination = Path(root), Path(destination)
    outline = runner.load(root, "outline", "book")
    if outline is None:
        raise ValueError("No outline; run the pipeline first")
    manifest = read(root / "manifest.json")
    from .review import load_decisions, apply_decisions, open_items, queue_items
    units, plants, diagrams, extracts = collect(root, outline)
    listings = {s["id"]: (runner.load(root, "listings", s["id"]) or {}).get("listings", [])
                for c in outline["chapters"] for s in c["sections"]}
    crosschecks = [runner.load(root, "crosscheck", s["id"]) for c in outline["chapters"] for s in c["sections"]]
    crosschecks = [c for c in crosschecks if c]
    runcode = runner.load(root, "runcode", "book")
    frames_summary = runner.load(root, "frames_summary", "book")
    boards = {}
    for f in (frames_summary or {}).get("frames", []):
        if f.get("status") == "kept" and f.get("placement"):
            boards.setdefault(f["placement"][1], []).append(f)
    decisions = load_decisions(root)
    units = {k: apply_decisions(v, decisions) for k, v in units.items()}
    label = {e["video_id"]: f"L{e['playlist_index']:02d}" for e in manifest["entries"] if e["video_id"]}
    titles = {e["video_id"]: e["title"] for e in manifest["entries"] if e["video_id"]}
    segment_ids = set(outline["lectures"]) | {c.split("@")[0] for u in units.values()
                                              for p in u["paragraphs"] for s in p["sentences"] for c in s["cites"]}
    lines = {x["id"]: x for v in segment_ids if runner.load(root, "segment", v)
             for x in runner.load(root, "segment", v)["lines"]}
    covered = set(outline["lectures"])
    missing = [e for e in manifest["entries"] if e["video_id"] not in covered]
    m = metrics(units, plants, extracts, outline, diagrams)
    evaluation = runner.load(root, "evaluation", "book")
    if evaluation:
        em = evaluation["metrics"]
        m["evaluator"] = (f"{'passed' if evaluation['passed'] else 'failed'}: support {em['independent_support']}, "
                          f"material errors {em['material_errors_per_100']}/100, core ideas missed {em['core_ideas_missed']}, "
                          f"quality {em['quality_average']}/5")
        m["evaluator_metrics"] = em
    queued = queue_items(root)
    from .review import open_conflicts
    m["review_queue_open"] = len(open_items(root))
    m["listings"] = sum(len(v) for v in listings.values())
    m["crosscheck"] = {k: sum(c["counts"][k] for c in crosschecks) for k in ("agrees", "contradicts", "not_covered")} if crosschecks else None
    m["reference_conflicts_open"] = len(open_conflicts(root))
    if frames_summary:
        m["board_figures"] = {"looked_at": frames_summary["looked_at"], "kept": frames_summary["kept"]}
    if runcode:
        runs = runcode["listings"].values()
        all_checks = [c for r in runs for c in r["checks"]]
        m["code_run"] = {"listings_ran": sum(r["status"] == "ran" for r in runs), "listings": len(runcode["listings"]),
                         "checks_passed": sum(c["passed"] is True for c in all_checks),
                         "checks_failed": sum(c["passed"] is False for c in all_checks), "torch": runcode["torch"]}
    m["review_decisions"] = {d: sum(1 for i in queued if decisions.get(i["sentence_id"], {}).get("decision") == d)
                             for d in ("accept", "edit", "remove")}
    reasons = draft_reasons(root, m, missing)
    status = "DRAFT" if reasons else "REVIEWED RELEASE"

    book = destination / "book"
    for web in (False, True):
        project = destination / ("web" if web else "book")
        if project.exists():
            shutil.rmtree(project)
        project.mkdir(parents=True)
        chapter_files = []
        if "intro" in units:
            intro = ["# Introduction {.unnumbered}", ""] + [paragraph_md(p) + "\n" for p in units["intro"]["paragraphs"]]
            (project / "intro.qmd").write_text("\n".join(intro))
            chapter_files.append("intro.qmd")
        for chapter in outline["chapters"]:
            name = f"{chapter['id']}.qmd"
            (project / name).write_text(chapter_md(chapter, units, diagrams, lines, label, titles, project / "figures",
                                                   listings, config.get("reference_pack"), web=web,
                                                   runs=(runcode or {}).get("listings"), boards=boards))
            chapter_files.append(name)
        (project / "index.qmd").write_text(front_matter(config, manifest, outline, m, reasons, status, missing, label))
        (project / "sources.qmd").write_text(sources_appendix(manifest, outline, extracts, label, units, lines,
                                                              project / "figures", web=web))
        (project / "report.qmd").write_text(report_appendix(m, reasons, status))
        formats = ({"html": {"theme": {"light": "cosmo", "dark": "darkly"}, "toc": True, "number-sections": True,
                             "footnotes-hover": True, "reference-location": "margin", "code-copy": True,
                             "smooth-scroll": True}} if web else
                   {"pdf": {"documentclass": "scrbook", "classoption": ["oneside", "numbers=noendperiod"], "papersize": "a4",
                            "toc": True, "number-sections": True, "colorlinks": True, "fontsize": "11pt", "fig-width": 5.5}})
        yml = {"project": {"type": "book", "output-dir": "_book"},
               "book": {"title": config["title"], "subtitle": status.title() if reasons else None,
                        "chapters": ["index.qmd", *chapter_files], "appendices": ["sources.qmd", "report.qmd"]},
               "format": formats}
        yml["book"] = {k: v for k, v in yml["book"].items() if v is not None}
        (project / "_quarto.yml").write_text(json.dumps(yml, indent=2))  # JSON is valid YAML
    from .brief import write_brief
    gates = {"capture": f"{len(covered)} of {len(manifest['entries'])} lectures available",
             "reader profile": "inferred" if runner.load(root, "reader", "book") else "missing",
             "outline approval": "current" if approval_is_current(root) else "missing or stale",
             "review queue": f"{m['review_queue_open']} open",
             "evaluator agent": m.get("evaluator", "not run"),
             "release": status}
    m["brief"] = write_brief(root, config, destination, manifest, outline, label, m, reasons, gates)
    write(destination / "evaluation_report.json", {"status": status, "draft_reasons": reasons, **m,
                                                   "lectures_covered": sorted(label[v] for v in covered),
                                                   "lectures_missing": [label[e["video_id"]] for e in missing if e["video_id"]]})
    return book, status, m


def render_html(destination="output"):
    """Render the web edition built by build_book: hover any paragraph's marker for its sources."""
    quarto = shutil.which("quarto")
    if not quarto:
        raise ValueError("Quarto is not installed; see README")
    web = Path(destination) / "web"
    result = subprocess.run([quarto, "render", str(web), "--to", "html"], capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError("Quarto HTML render failed:\n" + result.stderr[-3000:])
    target = Path(destination) / "html"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(web / "_book", target)
    return str(target / "index.html")


def render(root, config, destination="output", html=True):
    book, status, m = build_book(root, config, destination)
    from .figures import render_vector, svg_to_pdf
    for svg in sorted((book / "figures").glob("*.svg")):
        if not svg_to_pdf(svg):
            raise ValueError("Drawing figures needs Google Chrome or Chromium (set COURSEBOOK_CHROME)")
    for source in sorted((book / "figures").glob("*.mmd")):
        if not render_vector(source.read_text(), book / "figures"):
            raise ValueError("Drawing diagrams needs Google Chrome or Chromium (set COURSEBOOK_CHROME), "
                             "or set diagrams.enabled to false")
    quarto = shutil.which("quarto")
    if not quarto:
        raise ValueError("Quarto is not installed; see README (quarto + quarto install tinytex)")
    result = subprocess.run([quarto, "render", str(book), "--to", "pdf"], capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError("Quarto render failed:\n" + result.stderr[-3000:])
    pdf = next((book / "_book").glob("*.pdf"))
    target = Path(destination) / "book.pdf"
    shutil.copyfile(pdf, target)
    outputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [target, Path(destination) / "evaluation_report.json", *sorted(book.glob("*.qmd"))]}
    write(Path(destination) / "run_manifest.json", {"status": status, "outputs": outputs})
    web = render_html(destination) if html else None
    return {"status": status, "pdf": str(target), "html": web, **{k: m[k] for k in
            ("words", "support_rate_final", "review_queue_open", "plants_caught", "plants_planted")}}


def front_matter(config, manifest, outline, m, reasons, status, missing, label):
    covered = ", ".join(sorted(label[v] for v in outline["lectures"]))
    lines = ["# About this book {.unnumbered}", "",
             f"This book is generated from the lecture playlist [{md(manifest.get('title') or 'source playlist')}]"
             f"({config['playlist_url']}) and covers lectures {covered}.", "",
             "## How claims are grounded {.unnumbered}", "",
             "Every factual sentence in the chapters was written from the automatic captions of the lectures "
             "and cites the caption lines it relies on. Each chapter names the lectures it is based on, and "
             "the Sources appendix lists, for every section, the minutes of each lecture it draws on, linked "
             "to that moment in the video. A separate model then checked "
             "every sentence against the lines it cites; unsupported text was rewritten once, and anything "
             "still uncertain was sent to a human reviewer.", "",
             f"Measured for this edition: {m['support_rate_final']:.1%} of {m['factual_sentences']} factual sentences "
             f"were judged supported by their cited captions; the checker caught {m['plants_caught']} of "
             f"{m['plants_planted']} deliberately planted false sentences. "
             "This is a measured rate, not a guarantee of zero errors; see the evaluation report appendix.", ""]
    if reasons:
        lines += [f"## Status: {status} {{.unnumbered}}", "", "This edition is a draft because:", ""]
        lines += [f"- {md(r)}" for r in reasons] + [""]
    if missing:
        lines += ["## Lectures not covered {.unnumbered}", "",
                  "These playlist lectures are not part of this edition (for example, members-only videos "
                  "whose captions are not publicly available):", "",
                  ", ".join(label.get(e["video_id"], f"#{e['playlist_index']}") for e in missing), ""]
    return "\n".join(lines)


def heatmap_svg(outline, extracts, label):
    """Lecture × chapter grid shaded by how many teaching points flowed from each lecture into each chapter."""
    points = {p["id"]: p for e in extracts.values() for p in e["points"]}
    lectures = sorted(outline["lectures"], key=lambda v: label[v])
    counts = {(v, c["id"]): 0 for v in lectures for c in outline["chapters"]}
    for c in outline["chapters"]:
        for s in c["sections"]:
            for i in s["point_ids"]:
                if i in points:
                    counts[(points[i]["video_id"], c["id"])] += 1
    peak = max(counts.values()) or 1
    cw, ch, left, top = 56, 20, 52, 26
    width, height = left + cw * len(outline["chapters"]) + 10, top + ch * len(lectures) + 10
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="11">']
    for j, c in enumerate(outline["chapters"]):
        out.append(f'<text x="{left + j * cw + cw / 2}" y="16" text-anchor="middle" fill="#1d2733">{c["id"]}</text>')
    for i, v in enumerate(lectures):
        y = top + i * ch
        out.append(f'<text x="{left - 6}" y="{y + 14}" text-anchor="end" fill="#1d2733">{label[v]}</text>')
        for j, c in enumerate(outline["chapters"]):
            n = counts[(v, c["id"])]
            shade = 0 if not n else 0.15 + 0.85 * n / peak
            out.append(f'<rect x="{left + j * cw + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="2" '
                       f'fill="#2a62c9" fill-opacity="{shade:.2f}" stroke="#d6dcda"/>')
            if n:
                out.append(f'<text x="{left + j * cw + cw / 2}" y="{y + 14}" text-anchor="middle" '
                           f'fill="{"#ffffff" if shade > 0.55 else "#1d2733"}">{n}</text>')
    out.append("</svg>")
    return "\n".join(out)


def sources_appendix(manifest, outline, extracts, label, units, lines, figures_dir=None, web=False):
    lines_md = ["# Sources and coverage", ""]
    if figures_dir is not None:
        Path(figures_dir).mkdir(parents=True, exist_ok=True)
        (Path(figures_dir) / "coverage.svg").write_text(heatmap_svg(outline, extracts, label))
        ext = "svg" if web else "pdf"
        lines_md += ["## Coverage map", "", "How many teaching points each lecture (rows) contributes to each chapter (columns).", "",
                     f"![Teaching points by lecture and chapter.](figures/coverage.{ext}){{#fig-coverage width=70%}}", ""]
    titles = {e["video_id"]: e["title"] for e in manifest["entries"]}
    for video_id in outline["lectures"]:
        e = extracts[video_id]
        lines_md += [f"**{label[video_id]}**: [{md(titles[video_id])}](https://www.youtube.com/watch?v={video_id}), "
                     f"automatic captions; {len(e['points'])} teaching points extracted.", ""]
    lines_md += ["## Where each section comes from", "",
                 "Every factual sentence cites specific caption lines; these are the lecture time ranges "
                 "each section draws on (links open the video at that moment).", ""]
    for chapter in outline["chapters"]:
        lines_md += [f"**{md(chapter['title'])}**", ""]
        for section in chapter["sections"]:
            key = source_key(unit_cites(units[section["id"]]), lines, label)
            lines_md.append(f"- {md(section['title'])}: {key}")
        lines_md.append("")
    if outline["dropped"]:
        lines_md += ["## Points not included", "", "Teaching points the outline left out, with the editor's reason:", ""]
        points = {p["id"]: p for e in extracts.values() for p in e["points"]}
        for d in outline["dropped"]:
            lines_md.append(f"- {md(points[d['point_id']]['text'])} *({md(d['reason'])})*")
        lines_md.append("")
    return "\n".join(lines_md)


def report_appendix(m, reasons, status):
    rows = [("Words", m["words"]), ("Sections", m["sections"]),
            ("Factual sentences", m["factual_sentences"]),
            ("Supported on first check", f"{m['support_rate_first_pass']:.1%}"),
            ("Supported after one rewrite", f"{m['support_rate_final']:.1%}"),
            ("Paragraphs rewritten", m["paragraphs_rewritten"]),
            ("Open review-queue sentences", m["review_queue_open"]),
            ("Reviewer decisions (accepted / edited / removed)",
             " / ".join(str(m.get("review_decisions", {}).get(d, 0)) for d in ("accept", "edit", "remove"))),
            ("Planted false sentences caught", f"{m['plants_caught']} / {m['plants_planted']}"),
            ("Real sentences flagged in the plant run", f"{m['real_sentences_flagged_in_plant_run']} / {m['real_sentences_in_plant_run']}"),
            ("Teaching points extracted / placed / dropped", f"{m['points_extracted']} / {m['points_placed']} / {m['points_dropped']}"),
            ("Core points dropped", m["core_points_dropped"]),
            ("Diagrams kept / dropped by the checker", f"{m['diagrams_kept']} / {m['diagrams_dropped']}"),
            ("Code listings from the reference", m.get("listings", 0)),
            ("Cross-check vs reference (agrees / contradicts / not covered)",
             " / ".join(str((m.get("crosscheck") or {}).get(k, 0)) for k in ("agrees", "contradicts", "not_covered"))),
            ("Open conflicts with the reference", m.get("reference_conflicts_open", 0)),
            ("Board frames read / figures kept after checking against speech",
             f"{m['board_figures']['looked_at']} / {m['board_figures']['kept']}" if m.get("board_figures") else "not run"),
            ("Listings executed / numeric claims checked by running code",
             (f"{m['code_run']['listings_ran']} of {m['code_run']['listings']} ran; "
              f"{m['code_run']['checks_passed']} passed, {m['code_run']['checks_failed']} failed")
             if m.get("code_run") else "not run"),
            ("Evaluator agent", m.get("evaluator", "not run"))]
    out = ["# Evaluation report", "", f"Status: **{status}**.", "", "| Measure | Value |", "|---|---|"]
    out += [f"| {a} | {b} |" for a, b in rows]
    out += ["", "## Planted claims by type", "", "| Type | Caught / planted |", "|---|---|"]
    out += [f"| {t.replace('_', ' ')} | {v['caught']} / {v['planted']} |" for t, v in m["plants_by_type"].items()]
    if m["plant_misses"]:
        out += ["", "## Planted claims the checker missed", ""]
        out += [f"- ({p['type'].replace('_', ' ')}) {md(p['text'])}" for p in m["plant_misses"]]
    return "\n".join(out) + "\n"
