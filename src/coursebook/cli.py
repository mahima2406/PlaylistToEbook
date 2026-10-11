import argparse
import json
from pathlib import Path
from .core import read, inventory, capture
from .llm import LLMError


def lecture_list(text):
    return [int(x) for x in text.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="Reproducible course-to-book pipeline")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="Freeze playlist metadata with repository yt-dlp")
    cap = sub.add_parser("capture", help="Capture unchanged timed captions")
    cap.add_argument("--limit", type=int, default=1)
    run = sub.add_parser("run", help="Segment, extract, outline, frame, write, verify, takeaways, diagrams, plant test")
    run.add_argument("--lectures", type=lecture_list, help="playlist positions, e.g. 8,10 (default: config or all captured)")
    run.add_argument("--until", choices=["segment", "extract", "reader", "outline", "frame", "write", "verify",
                                         "takeaways", "diagrams", "plants", "listings", "crosscheck"], default="crosscheck")
    run.add_argument("--only", help="limit write/verify to sections starting with this id, e.g. ch01 or ch01.s03")
    run.add_argument("--offline", action="store_true", help="replay from the model cache; never call the API")
    approve = sub.add_parser("approve", help="Approve the current outline")
    approve.add_argument("--by", required=True, help="reviewer name")
    evaluate = sub.add_parser("evaluate", help="Independent evaluator agent: grounding, coverage and quality audits")
    evaluate.add_argument("--offline", action="store_true")
    evaluate.add_argument("--seed", type=int, default=0, help="sample seed (change to draw a fresh sample)")
    render = sub.add_parser("render", help="Build the Quarto book and PDF from verified sections (no model calls)")
    render.add_argument("--output", type=Path, default=Path("output"))
    review = sub.add_parser("review", help="Work through queued sentences: accept, edit (re-checked) or remove")
    review.add_argument("--by", help="reviewer name (required unless --list)")
    review.add_argument("--list", action="store_true", help="list open items and exit")
    review.add_argument("--take-low-risk", action="store_true",
                        help="record every low-risk recommendation as your decision, then stop")
    review.add_argument("--high-risk-only", action="store_true", help="walk only items whose recommendation is high risk")
    sub.add_parser("triage", help="Propose a decision for every open review item (the reviewer still decides)")
    sw = sub.add_parser("sweep", help="Independent grounding check of every factual sentence, with evaluator-checked fixes")
    sw.add_argument("--fix", action="store_true", help="propose rewordings for the sentences the sweep flagged")
    sw.add_argument("--apply", action="store_true", help="record the proposals as your decisions (needs --by)")
    sw.add_argument("--by", help="reviewer name for --apply")
    sw.add_argument("--votes", type=int, default=1, help="judge each sentence N times; the majority counts")
    runcode = sub.add_parser("run-code", help="Execute reference listings and check stated numbers (needs --group listings)")
    runcode.add_argument("--timeout", type=int, default=900, help="seconds per notebook")
    export = sub.add_parser("export", help="Write a shareable book-data package (no raw captions)")
    export.add_argument("--to", type=Path, default=Path("book-data"))
    verify = sub.add_parser("verify-package", help="Check a book-data package and rebuild the book from it")
    verify.add_argument("--package", type=Path, default=Path("book-data"))
    verify.add_argument("--pdf", action="store_true", help="also render the PDF (needs Quarto)")
    verify.add_argument("--out", type=Path, help="keep the rebuilt book here")
    frames = sub.add_parser("frames", help="Redraw whiteboard/screen figures from the video (opt-in media access)")
    frames.add_argument("--allow-media-download", action="store_true", help="read the video stream to grab single frames")
    studio = sub.add_parser("studio", help="Build the Studio: a browsable product view of the book")
    studio.add_argument("--output", type=Path, default=Path("output/studio"))
    studio.add_argument("--single-file", action="store_true", help="one self-contained studio.html")
    app = sub.add_parser("app", help="Open the Coursebook app: paste a playlist, watch the book build, read it")
    app.add_argument("--port", type=int, default=8800)
    why = sub.add_parser("why", help="Show the full trail behind a sentence or paragraph, e.g. ch02.s03.p01")
    why.add_argument("item_id")
    sub.add_parser("status", help="Show stage progress, spend, review queue and approvals")
    args = parser.parse_args()
    try:
        config = read(args.config)
        if args.command == "inventory":
            result = inventory(args.data, config)
            print(f"Captured {len(result['entries'])} playlist entries")
        elif args.command == "capture":
            if args.limit < 1:
                raise ValueError("limit must be positive")
            result = capture(args.data, config, args.limit)
            print(json.dumps(result, indent=2))
            if any(x["status"] == "blocked" for x in result):
                raise SystemExit(2)
        elif args.command == "run":
            from .llm import gateway_from_config
            from .pipeline import run as run_pipeline
            gateway = gateway_from_config(args.data, config, offline=args.offline)
            before = gateway.spent_usd()
            run_pipeline(args.data, config, gateway, args.lectures, args.until, args.only)
            print(f"spent this run: ${gateway.spent_usd() - before:.2f} (total ${gateway.spent_usd():.2f})")
        elif args.command == "approve":
            from .stages.outline import approve as approve_outline
            print(json.dumps(approve_outline(args.data, args.by), indent=2))
        elif args.command == "evaluate":
            from .llm import gateway_from_config
            from .stages.evaluator import run_evaluator
            result = run_evaluator(args.data, gateway_from_config(args.data, config, offline=args.offline), config, args.seed)
            print(json.dumps({"passed": result["passed"], **result["metrics"], "checks": result["checks"]}, indent=2))
        elif args.command == "run-code":
            from .llm import gateway_from_config
            from .stages.runcode import run_code
            from . import runner as _runner
            result = run_code(args.data, gateway_from_config(args.data, config), config,
                              _runner.load(args.data, "outline", "book"), args.timeout)
            rows = result["listings"].values()
            print(json.dumps({"listings": len(rows), "ran": sum(r["status"] == "ran" for r in rows),
                              "checks_passed": sum(c["passed"] is True for r in rows for c in r["checks"]),
                              "checks_failed": sum(c["passed"] is False for r in rows for c in r["checks"]),
                              "checks_discarded": result.get("checks_discarded", 0)}, indent=2))
        elif args.command == "frames":
            from .llm import gateway_from_config
            from .stages.frames import run_frames
            from . import runner as _runner
            summary = run_frames(args.data, gateway_from_config(args.data, config), config,
                                 _runner.load(args.data, "outline", "book"), args.allow_media_download)
            from collections import Counter as _C
            print(json.dumps({"looked_at": summary["looked_at"], "kept": summary["kept"],
                              "outcomes": _C(r.get("status") for r in summary["frames"])}, indent=2))
        elif args.command == "studio":
            from .studio import build_studio
            print(json.dumps(build_studio(args.data, config, args.output, args.single_file), indent=2))
        elif args.command == "app":
            from .app.server import serve
            serve(".", args.port)
        elif args.command == "why":
            from .why import trail
            print(trail(args.data, args.item_id))
        elif args.command == "export":
            from .export import export_package
            print(json.dumps(export_package(args.data, config, args.to), indent=2))
        elif args.command == "verify-package":
            from .export import verify_package
            result = verify_package(config, args.package, args.pdf, args.out)
            print(json.dumps(result, indent=2))
            if not result["ok"]:
                raise SystemExit(1)
        elif args.command == "render":
            from .render import render as render_book
            print(json.dumps(render_book(args.data, config, args.output), indent=2))
        elif args.command == "sweep":
            from .llm import gateway_from_config
            from . import sweep as sw
            if args.apply:
                if not args.by:
                    raise ValueError("pass --by \"Your Name\" to record who made each decision")
                print(json.dumps({"decisions_recorded": sw.apply_fixes(args.data, args.by)}))
            elif args.fix:
                recs = sw.propose_fixes(args.data, gateway_from_config(args.data, config))
                print(json.dumps({"proposals": len(recs), "edits": sum(r["decision"] == "edit" for r in recs.values()),
                                  "removals": sum(r["decision"] == "remove" for r in recs.values())}, indent=2))
            else:
                r = sw.sweep(args.data, gateway_from_config(args.data, config), votes=args.votes,
                             tag="sweep" if args.votes == 1 else "sweep2")
                print(json.dumps({k: r[k] for k in ("sentences", "supported", "rate", "votes", "self_disagreement")}, indent=2))
        elif args.command == "triage":
            from .llm import gateway_from_config
            from .triage import run_triage, summary
            recs = run_triage(args.data, config, gateway_from_config(args.data, config))
            print(json.dumps({"recommendations": len(recs), "by_kind": summary(recs)}, indent=2))
        elif args.command == "review":
            from .review import open_items, interactive, take_low_risk
            from .triage import load_recommendations, current_recommendation
            if args.list:
                recs = load_recommendations(args.data)
                for item in open_items(args.data):
                    rec = current_recommendation(recs, item) or {}
                    print(f"{item['sentence_id']}  {item['verdict']} ({item['confidence']:.2f})  "
                          f"{('-> ' + rec['decision'] + '/' + rec['risk']) if rec else ''}  {item['sentence']['text'][:80]}")
            elif not args.by:
                raise ValueError("pass --by \"Your Name\" to record who made each decision")
            elif args.take_low_risk:
                take_low_risk(args.data, args.by)
            else:
                from .llm import gateway_from_config
                interactive(args.data, config, gateway_from_config(args.data, config), args.by, only_high=args.high_risk_only)
        else:
            print_status(args.data, config)
    except (ValueError, KeyError, FileNotFoundError, LLMError) as exc:
        parser.exit(2, f"Blocked ({type(exc).__name__}): {exc}\n")


def print_status(root, config):
    from . import runner
    from .llm import Gateway
    from .stages.outline import approval_is_current
    budget = config.get("llm", {}).get("budget_usd")
    spent = Gateway(root, run_id="status").spent_usd()
    print("stages:", json.dumps(runner.counts(root)))
    print(f"spent: ${spent:.2f}" + (f" of ${budget:.2f} budget" if budget else ""))
    from .review import queue_items, open_items, open_conflicts, conflict_items
    print(f"review queue: {len(open_items(root))} open of {len(queue_items(root))}")
    print(f"reference conflicts: {len(open_conflicts(root))} open of {len(conflict_items(root))}")
    print("outline approval:", "current" if approval_is_current(root) else "missing or stale")


if __name__ == "__main__":
    main()
