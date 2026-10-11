"""Books and the build worker behind `coursebook app`.

    workspaces/<book-id>/            one per playlist
        config.json                  derived from the repo config (playlist, reader, budget)
        data/  output/               the same layout the CLI uses
        job.json                     build state: queued | running | done | failed, current step, activity
One worker thread builds one book at a time (keeps within API rate limits):
    inventory → capture → pipeline (reader … cross-check) → evaluator agent → render → studio
Every step is the CLI's own code; finished steps are skipped on a rerun.
"""
import json
import queue
import re
import shutil
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from ..core import read, write

STEPS = [("inventory", "Read the playlist"), ("capture", "Collect captions"), ("pipeline", "Write and check the book"),
         ("evaluate", "Independent evaluation"), ("render", "Typeset PDF and web edition"), ("studio", "Build the evidence explorer")]
OPTIONAL_FOR_NEW = {"reference_pack", "lectures", "lectures_note", "chapters_target", "edition", "author", "date"}


class Book:
    def __init__(self, book_id, root, out, config_path, workspace):
        self.id, self.root, self.out, self.config_path, self.workspace = book_id, Path(root), Path(out), Path(config_path), Path(workspace)

    @property
    def config(self):
        return read(self.config_path)

    @property
    def job_path(self):
        return self.workspace / "job.json"

    def job(self):
        if self.job_path.exists():
            return read(self.job_path)
        built = (self.out / "evaluation_report.json").exists()
        return {"status": "done" if built else "idle", "step": None, "activity": [], "error": None}

    def save_job(self, job):
        write(self.job_path, job)


class Library:
    def __init__(self, base):
        self.base = Path(base)
        self.workspaces = self.base / "workspaces"
        self.workspaces.mkdir(exist_ok=True)

    def books(self):
        found = []
        if (self.base / "data" / "manifest.json").exists():  # the repository's own book
            found.append(Book("main", self.base / "data", self.base / "output", self.base / "config.json", self.base / "workspaces" / "_main"))
        for ws in sorted(p for p in self.workspaces.iterdir() if p.is_dir() and not p.name.startswith("_")):
            if (ws / "config.json").exists():
                found.append(Book(ws.name, ws / "data", ws / "output", ws / "config.json", ws))
        return found

    def get(self, book_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", book_id or ""):
            return None
        return next((b for b in self.books() if b.id == book_id), None)

    def create(self, url, reader=None, budget=None):
        list_id = parse_qs(urlparse(url).query).get("list", [None])[0]
        if not list_id or not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", list_id):
            raise ValueError("Paste a YouTube playlist link (it contains ?list=...)")
        book_id = list_id[-16:]
        ws = self.workspaces / book_id
        if ws.exists() and (ws / "config.json").exists():
            return self.get(book_id)
        base = read(self.base / "config.json")
        config = {k: v for k, v in base.items() if k not in OPTIONAL_FOR_NEW}
        config["playlist_url"] = f"https://www.youtube.com/playlist?list={list_id}"
        config["title"] = "Untitled course"
        config["reader"] = (reader or "").strip() or "A curious learner new to this subject. Introduce prerequisites when the course supports it; flag gaps."
        config["llm"] = {**base.get("llm", {}), "budget_usd": float(budget) if budget else base.get("llm", {}).get("budget_usd", 50)}
        config["reader_profile"] = {"enabled": False}
        ws.mkdir(parents=True)
        write(ws / "config.json", config)
        book = self.get(book_id)
        book.save_job({"status": "queued", "step": None, "activity": [_line("Queued")], "error": None, "created": time.time()})
        return book


def _line(text):
    return {"t": time.strftime("%H:%M:%S"), "text": text}


class Worker:
    """Builds queued books one at a time in a background thread."""

    def __init__(self, library):
        self.library = library
        self.queue = queue.Queue()
        self.current = None
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, book):
        job = book.job()
        if job["status"] in ("queued", "running") and self.current == book.id:
            return
        job.update(status="queued", error=None)
        job.setdefault("activity", []).append(_line("Queued"))
        book.save_job(job)
        self.queue.put(book.id)

    def _loop(self):
        while True:
            book_id = self.queue.get()
            book = self.library.get(book_id)
            if book is None:
                continue
            self.current = book_id
            try:
                self._build(book)
            finally:
                self.current = None

    def _build(self, book):
        job = book.job()
        job.update(status="running", started=time.time(), error=None)

        def say(text, step=None):
            if step:
                job["step"] = step
            job.setdefault("activity", []).append(_line(text))
            job["activity"] = job["activity"][-200:]
            book.save_job(job)

        try:
            from ..core import inventory, capture
            from ..llm import gateway_from_config
            from ..pipeline import run
            say("Reading the playlist", "inventory")
            config = book.config
            manifest = inventory(book.root, config)
            if config.get("title") in (None, "", "Untitled course") and manifest.get("title"):
                config["title"] = manifest["title"]
                write(book.config_path, config)
            say(f"Found {len(manifest['entries'])} lectures in “{manifest.get('title') or 'playlist'}”")
            say("Collecting captions", "capture")
            reports = capture(book.root, config, len(manifest["entries"]))
            got = sum(r["status"] == "captured" for r in reports)
            say(f"Captions for {got} of {len(reports)} lectures" + (f"; {len(reports) - got} unavailable (listed as gaps)" if got < len(reports) else ""))
            if not got:
                raise ValueError("No lecture in this playlist has public captions")
            say("Writing and checking the book", "pipeline")
            gateway = gateway_from_config(book.root, config)
            run(book.root, config, gateway, log=lambda text: say(text[:300]))
            say("Independent evaluation", "evaluate")
            try:
                from ..stages.evaluator import run_evaluator
                ev = run_evaluator(book.root, gateway, config)
                say(f"Evaluator agent: {'passed' if ev['passed'] else 'not passed'}; facts backed {ev['metrics']['independent_support']}, reading score {ev['metrics']['quality_average']}/5")
            except Exception as exc:  # noqa: BLE001 - evaluation failure is reported, the book still renders
                say(f"Evaluator agent did not finish: {exc}"[:300])
            say("Typesetting the PDF and the web edition", "render")
            from ..render import build_book, render
            if shutil.which("quarto"):
                result = render(book.root, config, book.out)
                say(f"Book ready: {result['words']:,} words; {result['status'].lower()}")
            else:
                build_book(book.root, config, book.out)
                say("Quarto is not installed, so the PDF and web edition were skipped (sources are in output/book)")
            say("Building the evidence explorer", "studio")
            from ..studio import build_studio
            build_studio(book.root, config, book.out / "studio")
            job.update(status="done", step=None, finished=time.time())
            say("Done")
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user with its message
            job.update(status="failed", error=str(exc)[:600])
            say(f"Stopped: {exc}"[:400])
            traceback.print_exc()
