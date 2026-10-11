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
    run = sub.add_parser("run", help="Segment, extract, outline, write, verify and plant-test")
    run.add_argument("--lectures", type=lecture_list, help="playlist positions, e.g. 8,10 (default: config or all captured)")
    run.add_argument("--until", choices=["segment", "extract", "outline", "write", "verify", "plants"], default="plants")
    run.add_argument("--only", help="limit write/verify to sections starting with this id, e.g. ch01 or ch01.s03")
    run.add_argument("--offline", action="store_true", help="replay from the model cache; never call the API")
    approve = sub.add_parser("approve", help="Approve the current outline")
    approve.add_argument("--by", required=True, help="reviewer name")
    render = sub.add_parser("render", help="Build the Quarto book and PDF from verified sections (no model calls)")
    render.add_argument("--output", type=Path, default=Path("output"))
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
        elif args.command == "render":
            from .render import render as render_book
            print(json.dumps(render_book(args.data, config, args.output), indent=2))
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
    queue = [q for p in (Path(root) / "stages" / "verify").glob("*.json") for q in read(p)["output"]["queue"]]
    print(f"review queue: {sum(q['status'] == 'open' for q in queue)} open of {len(queue)}")
    print("outline approval:", "current" if approval_is_current(root) else "missing or stale")


if __name__ == "__main__":
    main()
