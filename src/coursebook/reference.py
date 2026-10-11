"""Reference pack: an optional, pinned outside source (for example the course's companion
code repository) used for code listings and for cross-checking technical claims.

    config.reference_pack = {repo, commit, license, name, include: [globs]}
    fetch   -> data/reference/repo at exactly `commit` (git)
    index   -> one chunk per notebook cell / Python file: {id, path, kind, heading, text}
               id = "ref:<path>#cell<N>" (notebooks) or "ref:<path>" (scripts)
    search  -> TF-IDF cosine over identifier-aware tokens (no extra dependencies)
The lectures stay the only source of teaching; the reference supplies code shown
verbatim and a second opinion on facts. Nothing here calls a model.
"""
import fnmatch
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path
from .core import digest, read, write

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")


def tokens(text):
    out = []
    for word in TOKEN.findall(text):
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", word).replace("_", " ").split()
        out += [p.lower() for p in parts if len(p) > 1]
    return out


def fetch(root, pack):
    if pack.get("path"):  # a local folder instead of a git repository
        return Path(pack["path"])
    repo = Path(root) / "reference" / "repo"
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", pack["repo"], str(repo)], check=True)
    current = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if current != pack["commit"]:
        subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin", pack["commit"]], check=False)
        subprocess.run(["git", "-C", str(repo), "checkout", "--quiet", pack["commit"]], check=True)
    return repo


def _notebook_chunks(path, rel):
    cells = json.loads(path.read_text()).get("cells", [])
    heading, chunks = "", []
    for n, cell in enumerate(cells):
        text = "".join(cell.get("source", []))
        if not text.strip():
            continue
        if cell.get("cell_type") == "markdown":
            first = next((l.strip("# ").strip() for l in text.splitlines() if l.startswith("#")), None)
            heading = first or heading
            text = re.sub(r"<img[^>]*>", "", text).strip()
            if not text:
                continue
        chunks.append({"id": f"ref:{rel}#cell{n}", "path": rel, "kind": "code" if cell.get("cell_type") == "code" else "text",
                       "heading": heading, "text": text})
    return chunks


def build_index(root, pack):
    repo = fetch(root, pack)
    chunks = []
    files = sorted(p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)
    for path in files:
        rel = str(path.relative_to(repo))
        if not any(fnmatch.fnmatch(rel, g) for g in pack.get("include", [])):
            continue
        if path.suffix == ".ipynb":
            chunks += _notebook_chunks(path, rel)
        elif path.suffix == ".py":
            chunks.append({"id": f"ref:{rel}", "path": rel, "kind": "code", "heading": path.stem, "text": path.read_text()})
    index = {"repo": pack["repo"], "commit": pack["commit"], "license": pack.get("license"), "name": pack.get("name"),
             "include": pack.get("include", []), "chunks": chunks}
    write(Path(root) / "reference" / "index.json", index)
    return index


def load_index(root, pack):
    path = Path(root) / "reference" / "index.json"
    if path.exists():
        index = read(path)
        if index["commit"] == pack["commit"] and index["include"] == pack.get("include", []):
            return index
    return build_index(root, pack)


class Search:
    def __init__(self, chunks):
        self.chunks = chunks
        self.vectors = [Counter(tokens(c["heading"] + " " + c["text"])) for c in chunks]
        df = Counter(t for v in self.vectors for t in v)
        self.idf = {t: math.log((1 + len(chunks)) / (1 + n)) + 1 for t, n in df.items()}
        self.norms = [math.sqrt(sum((n * self.idf[t]) ** 2 for t, n in v.items())) or 1.0 for v in self.vectors]

    def top(self, query, k=5, kind=None):
        q = Counter(tokens(query))
        qn = math.sqrt(sum((n * self.idf.get(t, 0)) ** 2 for t, n in q.items())) or 1.0
        scored = []
        for chunk, vec, norm in zip(self.chunks, self.vectors, self.norms):
            if kind and chunk["kind"] != kind:
                continue
            dot = sum(n * self.idf.get(t, 0) * vec[t] * self.idf.get(t, 0) for t, n in q.items() if t in vec)
            if dot:
                scored.append((dot / (qn * norm), chunk))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]


def pack_hash(index):
    return digest({"commit": index["commit"], "include": index["include"]})
