"""Execute a reference notebook's code cells up to given cells, in a fresh process.

    python -m coursebook.nbexec <job.json> <result.json>
    job = {notebook, workdir, stops: {cell_index: [{check_id, expression}]}, last_cell}
Runs cells 0..last_cell in one namespace (IPython magics and shell lines stripped,
plots headless, the notebook's folder importable). A failing cell is recorded and
execution continues: teaching notebooks often show an error on purpose and fix it in
the next cell. Each check's expression is evaluated right after its stop cell.
The parent process enforces the time limit.
"""
import contextlib
import io
import json
import os
import sys
import traceback


def _source(cell):
    lines = "".join(cell.get("source", [])).splitlines()
    return "\n".join(l for l in lines if not l.lstrip().startswith(("%", "!")))


def main(job_path, result_path):
    job = json.loads(open(job_path).read())
    os.chdir(job["workdir"])
    sys.path.insert(0, job["workdir"])
    os.environ.setdefault("MPLBACKEND", "Agg")
    cells = json.loads(open(job["notebook"]).read())["cells"]
    namespace = {"__name__": "__main__"}
    results, errors = {}, {}
    stops = {int(k): v for k, v in job["stops"].items()}
    outputs = {}
    for n, cell in enumerate(cells[: job["last_cell"] + 1]):
        if cell.get("cell_type") != "code":
            continue
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(compile(_source(cell), f"cell{n}", "exec"), namespace)
        except Exception:  # noqa: BLE001 - any notebook error is a reportable result, not a crash
            errors[str(n)] = traceback.format_exc(limit=2)[-800:]
        outputs[n] = buffer.getvalue()[-2000:]
        if n in stops:
            checks = []
            for check in stops[n]:
                try:
                    value = eval(check["expression"], namespace)  # noqa: S307 - expressions run in the sandboxed child process
                    checks.append({"check_id": check["check_id"], "value": float(value)})
                except Exception as exc:  # noqa: BLE001
                    checks.append({"check_id": check["check_id"], "error": f"{type(exc).__name__}: {exc}"[:300]})
            results[n] = {"checks": checks}
    with open(result_path, "w") as fh:
        json.dump({"outputs": {str(k): v for k, v in outputs.items()}, "stops": {str(k): v for k, v in results.items()},
                   "errors": errors, "python": sys.version.split()[0]}, fh)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
