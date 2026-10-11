import argparse
import json
from pathlib import Path
from .core import read, inventory, capture
from .llm import LLMError


def main():
    parser = argparse.ArgumentParser(description="Reproducible course-to-book assignment")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="Freeze playlist metadata with repository yt-dlp")
    cap = sub.add_parser("capture", help="Capture unchanged timed captions")
    cap.add_argument("--limit", type=int, default=1)
    draft = sub.add_parser("draft", help="Generate a candidate through configured API")
    draft.add_argument("video_id")
    render = sub.add_parser("build", help="Replay saved chapters without network or model calls")
    render.add_argument("--output", type=Path, default=Path("output"))
    render.add_argument("--release", action="store_true")
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
        elif args.command == "draft":
            from .model import generate
            generate(args.data, config, args.video_id)
            print("Candidate saved. Human source review is pending.")
        else:
            from .build import build
            print(json.dumps(build(args.data, args.output, config, args.release), indent=2))
    except (ValueError, KeyError, FileNotFoundError, LLMError) as exc:
        parser.exit(2, f"Blocked ({type(exc).__name__}): {exc}\n")


if __name__ == "__main__":
    main()
