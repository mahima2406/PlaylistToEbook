"""Stage runner: each (stage, item) is computed once per distinct inputs hash.

    data/stages/<stage>/<item>.json = {stage, item, inputs_hash, output_hash, output}

`inputs` must contain everything the output depends on (upstream output hashes,
prompt template hash, relevant config). Same inputs -> stored output, no model
call. Changed inputs -> recompute and overwrite. Downstream stages include the
upstream `output_hash`, so a change propagates without any extra bookkeeping.
"""
import re
from pathlib import Path
from .core import digest, read, write


def _path(root, stage, item):
    if not re.fullmatch(r"[A-Za-z0-9_.:@-]+", item):
        raise ValueError(f"Unsafe stage item name: {item!r}")
    return Path(root) / "stages" / stage / f"{item.replace(':', '_')}.json"


def run(root, stage, item, inputs, compute, force=False):
    path = _path(root, stage, item)
    inputs_hash = digest(inputs)
    if path.exists() and not force:
        record = read(path)
        if record.get("inputs_hash") == inputs_hash and digest(record["output"]) == record["output_hash"]:
            return record["output"]
    output = compute()
    write(path, {"stage": stage, "item": item, "inputs_hash": inputs_hash,
                 "output_hash": digest(output), "output": output})
    return output


def load(root, stage, item):
    path = _path(root, stage, item)
    return read(path)["output"] if path.exists() else None


def output_hash(root, stage, item):
    path = _path(root, stage, item)
    return read(path)["output_hash"] if path.exists() else None


def counts(root):
    base = Path(root) / "stages"
    if not base.exists():
        return {}
    return {d.name: len(list(d.glob("*.json"))) for d in sorted(base.iterdir()) if d.is_dir()}
