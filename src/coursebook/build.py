"""Offline replay; draft output is never represented as a reviewed release."""
from pathlib import Path
from xml.sax.saxutils import escape
from .core import read, write, digest, validate_chapter, review_is_current


def build(root, destination, config, release=False):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_LEFT
    root, destination = Path(root), Path(destination)
    manifest = read(root / "manifest.json")
    if digest(read(root / manifest["source_snapshot"])) != manifest["source_hash"]:
        raise ValueError("Playlist snapshot changed")
    chapters, issues = [], []
    for entry in manifest["entries"]:
        vid = entry["video_id"]
        path = root / "chapters" / f"{vid}.json"
        if not path.exists():
            issues.append(f"Missing chapter at playlist position {entry['playlist_index']}")
            continue
        packet = read(root / "evidence" / f"{vid}.json")
        raw = read(root / packet["snapshot"])
        if digest(raw) != packet["source_hash"]:
            raise ValueError("Caption snapshot changed")
        from .core import evidence_from_segments
        if packet["items"] != evidence_from_segments(vid, raw["segments"]):
            raise ValueError("Evidence differs from source snapshot")
        saved = read(path)
        if saved["source_hash"] != packet["source_hash"]:
            raise ValueError("Chapter source changed; regenerate or re-review")
        chapter = saved["chapter"]
        errors = validate_chapter(chapter, packet["items"])
        if errors:
            raise ValueError("; ".join(errors))
        review_path = root / "reviews" / f"{vid}.json"
        review = read(review_path) if review_path.exists() else {}
        if not (review_is_current(chapter, review) and review.get("source_hash") == packet["source_hash"]
                and review.get("support_review") == "passed" and review.get("reviewer")
                and review.get("visual_review") == "passed" and review.get("source_coverage_review") == "passed"):
            issues.append(f"{vid}: current source, claim and visual review required")
        if chapter.get("gaps"):
            issues.append(f"{vid}: unresolved chapter gaps")
        chapters.append((entry, chapter, packet))
    if not chapters:
        raise ValueError("No chapters available; capture and draft first")
    if release and issues:
        raise ValueError("Release blocked: " + "; ".join(issues))
    destination.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 10.5
    styles["BodyText"].leading = 15
    styles["BodyText"].alignment = TA_LEFT
    status = "REVIEWED RELEASE" if not issues else "DRAFT - REVIEW INCOMPLETE"
    story = [Paragraph(escape(config["title"]), styles["Title"]), Spacer(1, 20), Paragraph(status, styles["Heading2"])]
    markdown = ["# " + config["title"], "", status, ""]
    for entry, chapter, packet in chapters:
        story += [PageBreak(), Paragraph(escape(chapter["title"]), styles["Title"])]
        markdown += ["# " + chapter["title"], ""]
        evidence = {x["id"]: x for x in packet["items"]}
        for section in chapter["sections"]:
            story.append(Paragraph(escape(section["heading"]), styles["Heading2"]))
            markdown += ["## " + section["heading"], ""]
            for paragraph in section["paragraphs"]:
                text = paragraph["text"]
                story += [Paragraph(escape(text), styles["BodyText"]), Spacer(1, 8)]
                citations = []
                for ref in paragraph["evidence_ids"]:
                    item = evidence[ref]
                    citations.append(f'[{ref}]({item["url"]})')
                markdown += [text, "", "Sources: " + ", ".join(citations), ""]
                story.append(Paragraph("Sources: " + ", ".join(
                    f'<link href="{escape(evidence[r]["url"])}">{escape(r)}</link>' for r in paragraph["evidence_ids"]), styles["Normal"]))
        if chapter.get("gaps"):
            story.append(Paragraph("Editorial gaps", styles["Heading2"]))
            for gap in chapter["gaps"]:
                story.append(Paragraph(escape(gap), styles["BodyText"]))
            markdown += ["## Editorial gaps", *chapter["gaps"], ""]
    (destination / "book.md").write_text("\n".join(markdown))
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(48, 28, status)
        canvas.drawRightString(547, 28, str(doc.page))
    SimpleDocTemplate(str(destination / "book.pdf"), pagesize=(595, 842),
                      leftMargin=48, rightMargin=48, topMargin=50, bottomMargin=48,
                      title=config["title"], invariant=1).build(story, onFirstPage=footer, onLaterPages=footer)
    report = {"status": status, "release_ready": not issues, "issues": issues,
              "chapters": len(chapters), "playlist_entries": len(manifest["entries"]),
              "claim_support": "human review required; ID validation is not semantic verification",
              "coverage_percentage": None}
    write(destination / "evaluation_report.json", report)
    import hashlib
    write(destination / "run_manifest.json", {"mode": "offline_replay", "config_hash": digest(config),
          "source_manifest_hash": digest(manifest),
          "chapters": [{"video_id": e["video_id"], "chapter_hash": digest(c), "source_hash": p["source_hash"]} for e,c,p in chapters],
          "outputs": {n: hashlib.sha256((destination / n).read_bytes()).hexdigest() for n in ("book.md", "book.pdf", "evaluation_report.json")}})
    return report
