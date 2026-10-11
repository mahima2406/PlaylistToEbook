"""Run the book's code: execute reference listings and turn stated numbers into assertions.

    listing + its section's numeric sentences ──writer──> checks {sentence, expected, expression}
        (kept only if the expected number really appears in the sentence; expression is one
         side-effect-free Python expression)
    per notebook: child process runs cells 0..last listing cell (time-limited)
        → listing ran? its printed output · each check: value == expected (± tolerance)?
Failed checks mean the book states a number the code does not produce; they block release.
Needs the optional `listings` dependency group (uv sync --group listings).
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from ..core import digest
from ..reference import load_index, pack_hash, fetch
from .. import runner

PROMPT = Path("prompts/numeric_checks.txt")
FORBIDDEN = re.compile(r"import|__|\bopen\s*\(|\bexec\b|\beval\b|\bcompile\b|\bos\.|\bsys\.|subprocess|[;\n]|\binput\s*\(|globals|locals|getattr|setattr|delattr")
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def numbers_in(text):
    """All numeric values a sentence states, including '124 million' style amounts."""
    values = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion)?", text.replace(" ", " ")):
        value = float(m.group(1).replace(",", ""))
        values.append(value * SCALE.get((m.group(2) or "").lower(), 1))
    return values


def _close(a, b, tol):
    return abs(a - b) <= max(tol * abs(b), 1e-9)


def validate_checks(obj, sentences):
    checks = obj.get("checks")
    if not isinstance(checks, list):
        return ["'checks' must be a list"]
    errors = []
    for n, c in enumerate(checks):
        s = sentences.get(c.get("sentence_id"))
        if s is None:
            errors.append(f"check {n}: unknown sentence_id")
            continue
        if not isinstance(c.get("expected"), (int, float)):
            errors.append(f"check {n}: expected must be a number")
        elif not any(_close(v, float(c["expected"]), 1e-9) for v in numbers_in(s["text"])):
            errors.append(f"check {n}: {c['expected']} does not appear in the sentence")
        expr = str(c.get("expression", ""))
        if not expr.strip() or FORBIDDEN.search(expr):
            errors.append(f"check {n}: expression must be a single side-effect-free expression")
        if not isinstance(c.get("tolerance", 0), (int, float)) or not 0 <= c.get("tolerance", 0) <= 0.05:
            errors.append(f"check {n}: tolerance must be between 0 and 0.05")
    return errors


def last_cell(chunks, listing):
    """Index of the last notebook cell included in an expanded listing (mirrors listings.expand)."""
    ids = [c["id"] for c in chunks]
    n = ids.index(listing["ref"])
    lines, last = len(chunks[n]["text"].rstrip().splitlines()), chunks[n]
    for nxt in chunks[n + 1:]:
        if nxt["path"] != last["path"] or nxt["kind"] != "code" or lines >= 30:
            break
        lines += 1 + len(nxt["text"].rstrip().splitlines())
        last = nxt
    return int(last["id"].split("#cell")[1]), int(listing["ref"].split("#cell")[1])


def propose_checks(gateway, section_id, listing, sentences):
    numeric = {s["id"]: s for s in sentences if s["type"] == "F" and numbers_in(s["text"])}
    if not numeric:
        return []
    listing_text = "\n".join(f"{sid} | {s['text']}" for sid, s in numeric.items())
    result = gateway.call_json("writer", [{"role": "system", "content": PROMPT.read_text()},
                                          {"role": "user", "content": f"Sentences:\n{listing_text}\n\nCode:\n{listing['code']}"}],
                               stage="checks", input_id=listing["id"], max_completion_tokens=8000,
                               validate=lambda o: validate_checks(o, numeric))
    return [{**c, "check_id": f"{listing['id']}.chk{n}", "sentence_text": numeric[c["sentence_id"]]["text"]}
            for n, c in enumerate(result["parsed"]["checks"], 1)]


def execute(repo, notebook, stops, last, timeout):
    with tempfile.TemporaryDirectory() as tmp:
        job, out = Path(tmp) / "job.json", Path(tmp) / "result.json"
        job.write_text(json.dumps({"notebook": str(repo / notebook), "workdir": str((repo / notebook).parent),
                                   "stops": stops, "last_cell": last}))
        try:
            proc = subprocess.run([sys.executable, "-m", "coursebook.nbexec", str(job), str(out)],
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"timeout": True}
        if not out.exists():
            return {"crashed": proc.stderr[-800:]}
        return json.loads(out.read_text())


def run_code(root, gateway, config, outline, timeout=900):
    pack = config.get("reference_pack") or {}
    if not pack.get("enabled"):
        return None
    index = load_index(root, pack)
    repo = fetch(root, pack)
    sections = [s for c in outline["chapters"] for s in c["sections"]]
    listings, checks = [], {}
    for section in sections:
        record = runner.load(root, "listings", section["id"])
        if not record or not record["listings"]:
            continue
        unit = runner.load(root, "verify", section["id"])
        sentences = [s for p in unit["paragraphs"] for s in p["sentences"]]
        for listing in record["listings"]:
            listings.append(listing)
            inputs = {"listing": digest(listing), "sentences": digest(sentences), "prompt": digest(PROMPT.read_text()), "v": 1}
            checks[listing["id"]] = runner.run(root, "checks", listing["id"], inputs,
                                               lambda l=listing, s=sentences: propose_checks(gateway, section["id"], l, s))

    try:
        import torch
        torch_version = torch.__version__
    except ImportError as exc:
        raise ValueError("Running listings needs the optional dependencies: uv sync --group listings") from exc

    def compute():
        by_notebook = {}
        for listing in listings:
            end, start = last_cell(index["chunks"], listing)
            by_notebook.setdefault(listing["path"], []).append((listing, start, end))
        results = {}
        for notebook, items in by_notebook.items():
            stops = {}
            for listing, _, end in items:
                stops.setdefault(str(end), []).extend({"check_id": c["check_id"], "expression": c["expression"]}
                                                      for c in checks[listing["id"]])
            last = max(end for _, _, end in items)
            run = execute(repo, notebook, stops, last, timeout)
            for listing, start, end in items:
                if run.get("timeout") or run.get("crashed"):
                    status = "not run (time limit)" if run.get("timeout") else "not run (crashed)"
                    results[listing["id"]] = {"status": status, "output": "", "checks": []}
                    continue
                err = run.get("error")
                ok = not err or err["cell"] > end
                output = "".join(run["outputs"].get(str(k), "") for k in range(start, end + 1)).strip()
                values = {c["check_id"]: c for c in run["stops"].get(str(end), {}).get("checks", [])}
                rows = []
                for c in checks[listing["id"]]:
                    v = values.get(c["check_id"], {})
                    passed = "value" in v and _close(v["value"], float(c["expected"]), float(c.get("tolerance", 0)))
                    rows.append({**c, "value": v.get("value"), "error": v.get("error"), "passed": passed if ok else None})
                results[listing["id"]] = {"status": "ran" if ok else f"error in cell {err['cell']}",
                                          "error": None if ok else err["error"], "output": output[-1500:], "checks": rows}
        return {"torch": torch_version, "commit": pack["commit"], "listings": results}

    inputs = {"pack": pack_hash(index), "listings": {l["id"]: digest(l) for l in listings},
              "checks": {k: digest(v) for k, v in checks.items()}, "torch": torch_version, "v": 1}
    return runner.run(root, "runcode", "book", inputs, compute)
