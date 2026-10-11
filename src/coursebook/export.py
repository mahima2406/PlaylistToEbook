"""Shareable book data: rebuild and verify the book without the raw captions.

    data/ (local, private)              book-data/ (committable)
    ├─ raw/, evidence/  (captions)  ─✗  not copied
    ├─ cache/           (prompts with caption text) ─✗ not copied
    ├─ stages/segment   ─────────────►  line IDs and timings only (no caption text)
    ├─ stages/<other>   ─────────────►  copied as stored
    ├─ approvals/, reviews/, runs/ ──►  copied
    └─ manifest.json, playlist snapshot ► copied
    + PACKAGE.json: sha256 of every file, and the fingerprints of the rebuilt book
`verify_package` checks every file against PACKAGE.json, rebuilds the book sources
from the package (no model calls, no captions) and compares the result.
"""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from .core import read, write

COPY_DIRS = ["approvals", "reviews", "runs"]
SKIP_STAGES = {"segment"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _strip_segment(record):
    out = record["output"]
    lines = [{k: x[k] for k in ("id", "key", "video_id", "start", "end")} for x in out["lines"]]
    return {**record, "output": {**out, "lines": lines}, "redacted": "caption text removed"}


def book_fingerprints(book_dir, destination):
    files = sorted(Path(book_dir).glob("*.qmd")) + [Path(destination) / "evaluation_report.json"]
    files += sorted((Path(destination) / "brief").glob("*.md"))
    return {p.name if p.parent.name != "brief" else f"brief/{p.name}": _sha(p) for p in files}


def export_package(root, config, target="book-data"):
    from .render import build_book
    root, target = Path(root), Path(target)
    if target.exists():
        shutil.rmtree(target)
    (target / "stages").mkdir(parents=True)
    manifest = read(root / "manifest.json")
    write(target / "manifest.json", manifest)
    shutil.copytree(root / "raw" / "playlist", target / "raw" / "playlist")
    for stage_dir in sorted((root / "stages").iterdir()):
        dest = target / "stages" / stage_dir.name
        dest.mkdir()
        for path in sorted(stage_dir.glob("*.json")):
            record = read(path)
            write(dest / path.name, _strip_segment(record) if stage_dir.name in SKIP_STAGES else record)
    for name in COPY_DIRS:
        if (root / name).exists():
            shutil.copytree(root / name, target / name)
    with tempfile.TemporaryDirectory() as tmp:
        book, status, _ = build_book(target, config, Path(tmp) / "out")
        fingerprints = book_fingerprints(book, Path(tmp) / "out")
    files = {str(p.relative_to(target)): _sha(p) for p in sorted(target.rglob("*")) if p.is_file()}
    write(target / "PACKAGE.json", {"note": "Rebuild with: coursebook verify-package", "status": status,
                                    "files": files, "book": fingerprints})
    return {"files": len(files), "status": status,
            "size_mb": round(sum(p.stat().st_size for p in target.rglob('*') if p.is_file()) / 1e6, 2)}


def verify_package(config, package="book-data", pdf=False, keep=None):
    from .render import build_book, render
    package = Path(package)
    spec = read(package / "PACKAGE.json")
    problems = []
    actual = {str(p.relative_to(package)): _sha(p) for p in sorted(package.rglob("*")) if p.is_file() and p.name != "PACKAGE.json"}
    for name, sha in spec["files"].items():
        if actual.get(name) != sha:
            problems.append(f"changed or missing: {name}")
    problems += [f"unexpected file: {n}" for n in actual if n not in spec["files"]]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(keep) if keep else Path(tmp) / "out"
        if pdf:
            render(package, config, out)
            book = out / "book"
        else:
            book, _, _ = build_book(package, config, out)
        rebuilt = book_fingerprints(book, out)
    for name, sha in spec["book"].items():
        if rebuilt.get(name) != sha:
            problems.append(f"rebuilt output differs: {name}")
    return {"ok": not problems, "problems": problems, "files_checked": len(spec["files"]), "outputs_checked": len(spec["book"])}
