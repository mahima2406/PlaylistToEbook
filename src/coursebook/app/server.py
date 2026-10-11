"""`coursebook app`: a local web app. Paste a playlist, watch the book being built, read it.

    GET  /                          the app
    GET  /api/books                 library: every book with its status and headline numbers
    POST /api/books                 {playlist_url, reader?, budget?} → create and start building
    GET  /api/books/<id>            live state: step, activity, stage counts, cost, outline, results
    POST /api/books/<id>/build      build again (finished steps are skipped)
    POST /api/books/<id>/approve    approve the current chapter plan
    GET  /books/<id>/pdf            the PDF
    GET  /books/<id>/web/...        the web edition
    GET  /books/<id>/studio/...     the evidence explorer
Standard library only; binds to 127.0.0.1.
"""
import hmac
import json
import mimetypes
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .. import runner
from ..core import read
from .jobs import Library, Worker, STEPS

STATIC = Path(__file__).parent / "static"


def book_summary(book):
    job = book.job()
    report = book.out / "evaluation_report.json"
    metrics = read(report) if report.exists() else {}
    manifest = read(book.root / "manifest.json") if (book.root / "manifest.json").exists() else {}
    covered = len(list((book.root / "evidence").glob("*.json"))) if (book.root / "evidence").exists() else 0
    return {"id": book.id, "title": book.config.get("title"), "playlist": book.config.get("playlist_url"),
            "status": job["status"], "step": job.get("step"), "lectures": len(manifest.get("entries", [])), "captured": covered,
            "words": metrics.get("words"), "supported": metrics.get("support_rate_final"),
            "plants": [metrics.get("plants_caught"), metrics.get("plants_planted")], "release": metrics.get("status"),
            "has_pdf": (book.out / "book.pdf").exists(), "has_web": (book.out / "html" / "index.html").exists(),
            "has_studio": (book.out / "studio" / "index.html").exists(), "code": metrics.get("code_run")}


def sample(book):
    """One real checked sentence and one passed code check, for the product page's figure."""
    from ..stages.runcode import load_code_run
    outline = runner.load(book.root, "outline", "book")
    if not outline:
        return None
    manifest = read(book.root / "manifest.json")
    label = {e["video_id"]: e["playlist_index"] for e in manifest["entries"] if e["video_id"]}
    found = None
    for chapter in outline["chapters"][1:]:
        for section in chapter["sections"]:
            unit = runner.load(book.root, "verify", section["id"]) or {}
            verdicts = unit.get("verdicts", {})
            for s in (s for p in unit.get("paragraphs", []) for s in p["sentences"]):
                v = verdicts.get(s["id"], {})
                if s["type"] == "F" and v.get("verdict") == "supported" and v.get("confidence", 0) >= 0.9 and 70 <= len(s["text"]) <= 150 and s["cites"]:
                    found = (chapter, section, s, v)
                    break
            if found:
                break
        if found:
            break
    if not found:
        return None
    chapter, section, s, v = found
    video = s["cites"][0].split("@")[0]
    line = next((x for x in (runner.load(book.root, "segment", video) or {"lines": []})["lines"] if x["id"] == s["cites"][0]), None)
    start = int(line["start"]) if line else 0
    check = next((c for r in (load_code_run(book.root) or {}).get("listings", {}).values() for c in r["checks"]
                  if c["passed"] is True and len(c["expression"]) <= 32 and abs(c["value"] or 0) >= 100), None)
    return {"text": s["text"], "id": s["id"], "chapter": chapter["title"], "section": section["title"],
            "lecture": label.get(video), "clock": f"{start // 60:02d}:{start % 60:02d}", "lines": len(s["cites"]),
            "confidence": v["confidence"], "url": f"https://www.youtube.com/watch?v={video}&t={start}s",
            "check": {"expression": check["expression"], "value": check["value"]} if check else None}


def book_detail(book):
    from ..llm import Gateway
    from ..review import open_items, open_conflicts
    from ..stages.outline import approval_is_current
    summary = book_summary(book)
    job = book.job()
    counts = runner.counts(book.root) if book.root.exists() else {}
    outline = runner.load(book.root, "outline", "book") if book.root.exists() else None
    plants = [runner.load(book.root, "plants", c["id"]) for c in (outline or {}).get("chapters", [])]
    points = sum(len((runner.load(book.root, "extract", v) or {"points": []})["points"]) for v in (outline or {}).get("lectures", []))
    report = read(book.out / "evaluation_report.json") if (book.out / "evaluation_report.json").exists() else {}
    ev = runner.load(book.root, "evaluation", "book") if book.root.exists() else None
    evaluation = {"met": sum(ev["checks"].values()), "total": len(ev["checks"]), "passed": ev["passed"],
                  "metrics": ev["metrics"]} if ev else None
    try:
        reviews = {"queue": len(open_items(book.root)), "conflicts": len(open_conflicts(book.root))} if outline else None
    except Exception:  # noqa: BLE001 - partially built books may lack some stage files
        reviews = None
    return {**summary, "error": job.get("error"), "activity": job.get("activity", [])[-60:],
            "steps": [{"key": k, "label": label} for k, label in STEPS], "counts": counts,
            "cost": round(Gateway(book.root, run_id="app").spent_usd(), 2) if book.root.exists() else 0,
            "budget": book.config.get("llm", {}).get("budget_usd"),
            "ideas": points or None,
            "plants_live": [sum(p["caught"] for p in plants if p), sum(p["planted"] for p in plants if p)] if any(plants) else None,
            "outline": [{"title": c["title"], "summary": c["summary"], "sections": [s["title"] for s in c["sections"]]}
                        for c in (outline or {}).get("chapters", [])],
            "approved": bool(outline) and approval_is_current(book.root),
            "reviews": reviews, "evaluation": evaluation, "report": {k: report.get(k) for k in
                ("status", "draft_reasons", "words", "support_rate_final", "plants_caught", "plants_planted",
                 "points_placed", "points_dropped", "diagrams_kept", "listings", "evaluator")}}


class Handler(BaseHTTPRequestHandler):
    library = None
    worker = None

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        path = Path(path)
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _safe(self, base, rel):
        base = Path(base).resolve()
        target = (base / (rel or "index.html")).resolve()
        return target if str(target).startswith(str(base)) else None

    def do_GET(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if not parts:
            return self._file(STATIC / "index.html")
        if parts[:2] == ["api", "books"]:
            if len(parts) == 2:
                return self._json([book_summary(b) for b in self.library.books()])
            if parts[2:] == ["config"]:
                return self._json({"build_code_required": bool(os.environ.get("COURSEBOOK_BUILD_CODE"))})
            if parts[2:] == ["sample"]:
                done = next((b for b in self.library.books() if (b.out / "evaluation_report.json").exists()), None)
                return self._json((sample(done) if done else None) or {})
            book = self.library.get(parts[2])
            return self._json(book_detail(book)) if book else self._json({"error": "no such book"}, 404)
        if parts[0] == "books" and len(parts) >= 3:
            book = self.library.get(parts[1])
            if not book:
                return self._json({"error": "no such book"}, 404)
            if parts[2] == "pdf":
                return self._file(book.out / "book.pdf")
            folder = {"web": book.out / "html", "studio": book.out / "studio"}.get(parts[2])
            target = self._safe(folder, "/".join(parts[3:])) if folder else None
            return self._file(target) if target else self._json({"error": "not found"}, 404)
        target = self._safe(STATIC, "/".join(parts))
        return self._file(target) if target else self._json({"error": "not found"}, 404)

    def _allowed(self):
        """Starting or changing a build needs the access code when COURSEBOOK_BUILD_CODE is set (public deployments)."""
        code = os.environ.get("COURSEBOOK_BUILD_CODE")
        return not code or hmac.compare_digest(self.headers.get("X-Build-Code", ""), code)

    def do_POST(self):
        parts = [p for p in self.path.split("/") if p]
        if not self._allowed():
            return self._json({"error": "This deployment needs an access code to build. Ask the owner for one."}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return self._json({"error": "send JSON"}, 400)
        try:
            if parts == ["api", "books"]:
                book = self.library.create(body.get("playlist_url", ""), body.get("reader"), body.get("budget"))
                self.worker.submit(book)
                return self._json(book_summary(book), 201)
            if len(parts) == 4 and parts[:2] == ["api", "books"]:
                book = self.library.get(parts[2])
                if not book:
                    return self._json({"error": "no such book"}, 404)
                if parts[3] == "build":
                    self.worker.submit(book)
                    return self._json(book_summary(book))
                if parts[3] == "approve":
                    from ..stages.outline import approve
                    approve(book.root, body.get("by") or "Reviewer")
                    return self._json(book_detail(book))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"error": "not found"}, 404)


def serve(base=".", port=8800):
    library = Library(base)
    Handler.library, Handler.worker = library, Worker(library)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Coursebook is running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
