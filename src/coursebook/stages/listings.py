"""Code listings from the reference pack (shown verbatim, never written by a model).

    section points (code / procedure kinds) ──search──> candidate code cells
        ──writer picks ≤ N──> each pick ──judge: "matches"?──> kept listing
A listing is the chosen notebook cell plus the code cells that directly follow it
(up to MAX_LINES), labelled with its file, commit and licence.
"""
from pathlib import Path
from ..core import digest
from ..reference import load_index, Search, pack_hash
from .. import runner

PROMPT = Path("prompts/listing.txt")
CHECK = Path("prompts/listing_check.txt")
CANDIDATES = 8
MAX_LINES = 30
CODE_KINDS = {"code", "procedure", "equation"}


def expand(index_chunks, chunk):
    """Chosen cell + following code cells of the same notebook, until a text cell or MAX_LINES."""
    ids = [c["id"] for c in index_chunks]
    n = ids.index(chunk["id"])
    lines = chunk["text"].rstrip().splitlines()
    for nxt in index_chunks[n + 1:]:
        if nxt["path"] != chunk["path"] or nxt["kind"] != "code" or len(lines) >= MAX_LINES:
            break
        lines += [""] + nxt["text"].rstrip().splitlines()
    truncated = len(lines) > MAX_LINES
    return "\n".join(lines[:MAX_LINES]), truncated


def _validate_picks(obj, allowed, limit):
    picks = obj.get("listings")
    if not isinstance(picks, list):
        return ["'listings' must be a list"]
    errors = [f"at most {limit} listings"] if len(picks) > limit else []
    errors += [f"unknown ref {p.get('ref')}" for p in picks if p.get("ref") not in allowed]
    errors += ["each listing needs a caption" for p in picks if not str(p.get("caption", "")).strip()]
    return errors


def section_listings(gateway, index, search, section, points, verified, limit):
    code_points = [p for p in points if p["kind"] in CODE_KINDS]
    if not code_points:
        return {"section_id": section["id"], "listings": [], "rejected": []}
    query = section["title"] + " " + " ".join(p["text"] for p in code_points)
    candidates = [c for _, c in search.top(query, CANDIDATES, kind="code")]
    if not candidates:
        return {"section_id": section["id"], "listings": [], "rejected": []}
    teaches = "\n".join(f"- {p['text']}" for p in code_points)
    summary = " ".join(s["text"] for p in verified["paragraphs"][:3] for s in p["sentences"])[:1200]
    listing = "\n\n".join(f"{c['id']} (under heading: {c['heading']})\n{c['text'][:1200]}" for c in candidates)
    picks = gateway.call_json("writer", [{"role": "system", "content": PROMPT.read_text().replace("{max}", str(limit))},
                                         {"role": "user", "content": f"Section: {section['title']}\nTeaches:\n{teaches}\n\n"
                                                                     f"Section text (start): {summary}\n\nCandidates:\n{listing}"}],
                              stage="listings", input_id=section["id"],
                              validate=lambda o: _validate_picks(o, {c["id"] for c in candidates}, limit))["parsed"]["listings"]
    kept, rejected = [], []
    by_id = {c["id"]: c for c in candidates}
    for n, pick in enumerate(picks, 1):
        code, truncated = expand(index["chunks"], by_id[pick["ref"]])
        check = gateway.call_json("judge", [{"role": "system", "content": CHECK.read_text()},
                                            {"role": "user", "content": f"Section teaches:\n{teaches}\n\nCaption: {pick['caption']}\n\nCode:\n{code}"}],
                                  stage="listings", input_id=f"{section['id']}:check{n}",
                                  validate=lambda o: [] if o.get("verdict") in ("matches", "partial", "no") else ["verdict must be matches, partial or no"])["parsed"]
        record = {"id": f"{section['id']}.code{n}", "ref": pick["ref"], "path": by_id[pick["ref"]]["path"],
                  "caption": pick["caption"], "code": code, "truncated": truncated,
                  "check": check["verdict"], "reason": check.get("reason", "")}
        (kept if check["verdict"] == "matches" else rejected).append(record)
    return {"section_id": section["id"], "listings": kept, "rejected": rejected}


def run_listings(root, gateway, config, outline, workers=4):
    pack = config.get("reference_pack") or {}
    if not pack.get("enabled"):
        return []
    index = load_index(root, pack)
    search = Search(index["chunks"])
    limit = pack.get("listings_per_section", 2)
    points = {p["id"]: p for v in outline["lectures"] for p in runner.load(root, "extract", v)["points"]}
    sections = [s for c in outline["chapters"] for s in c["sections"]]

    def job(section):
        verified = runner.load(root, "verify", section["id"])
        section_points = [points[i] for i in section["point_ids"] if i in points]
        inputs = {"pack": pack_hash(index), "points": digest(section_points), "verify": runner.output_hash(root, "verify", section["id"]),
                  "prompts": [digest(PROMPT.read_text()), digest(CHECK.read_text())], "limit": limit, "v": 1}
        return runner.run(root, "listings", section["id"], inputs,
                          lambda: section_listings(gateway, index, search, section, section_points, verified, limit))

    return gateway.map(job, sections, workers=workers)
