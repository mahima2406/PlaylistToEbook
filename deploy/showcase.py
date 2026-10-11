"""Build a read-only static showcase of the app with every finished book, for static hosting (Vercel).

    deploy/showcase/            published as-is
      index.html                the app, in showcase mode (no builds)
      api/books.json, api/books/<id>.json, api/books/sample.json, api/books/config.json
      books/<id>/book.pdf, books/<id>/web/..., books/<id>/studio/...
      vercel.json               maps the app's API paths onto the JSON files
Run from the repo root:  uv run python deploy/showcase.py
"""
import json
import shutil
from pathlib import Path

from coursebook.app.jobs import Library
from coursebook.app.server import STATIC, book_detail, book_summary, sample

OUT = Path("deploy/showcase")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "api" / "books").mkdir(parents=True)
    books = [b for b in Library(".").books() if (b.out / "evaluation_report.json").exists() and (b.out / "book.pdf").exists()]
    summaries = []
    for book in books:
        summaries.append({**book_summary(book), "static": True})
        detail = {**book_detail(book), "static": True, "activity": book_detail(book)["activity"]}
        (OUT / "api" / "books" / f"{book.id}.json").write_text(json.dumps(detail))
        target = OUT / "books" / book.id
        target.mkdir(parents=True)
        shutil.copy(book.out / "book.pdf", target / "book.pdf")
        for name, folder in (("web", book.out / "html"), ("studio", book.out / "studio")):
            if folder.exists():
                shutil.copytree(folder, target / name)
    (OUT / "api" / "books.json").write_text(json.dumps(summaries))
    first = next((b for b in books if b.id == "main"), books[0] if books else None)
    (OUT / "api" / "books" / "sample.json").write_text(json.dumps((sample(first) if first else None) or {}))
    (OUT / "api" / "books" / "config.json").write_text(json.dumps({"build_code_required": False, "static": True}))
    shutil.copy(STATIC / "index.html", OUT / "index.html")
    (OUT / "vercel.json").write_text(json.dumps({
        "cleanUrls": False, "trailingSlash": False,
        "rewrites": [{"source": "/api/books", "destination": "/api/books.json"},
                     {"source": "/api/books/:id", "destination": "/api/books/:id.json"},
                     {"source": "/books/:id/pdf", "destination": "/books/:id/book.pdf"}]}, indent=2))
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(json.dumps({"books": [b.id for b in books], "files": sum(1 for f in OUT.rglob("*") if f.is_file()),
                      "size_mb": round(size / 1e6, 1)}))


if __name__ == "__main__":
    main()
