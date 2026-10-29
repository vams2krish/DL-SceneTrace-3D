import argparse
from pathlib import Path
import json
from .media import inventory, save_json


def main():
    parser = argparse.ArgumentParser(prog="scenetrace")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "reconstruct"):
        sub = commands.add_parser(name)
        sub.add_argument("source", type=Path)
        sub.add_argument("output", type=Path)
        sub.add_argument("--interval", type=float, default=1.0)
        sub.add_argument("--max-frames", type=int, default=40)
    sub = commands.add_parser("demo")
    sub.add_argument("output", type=Path)
    sub = commands.add_parser("serve")
    sub.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("scenetrace.server:app", host="127.0.0.1", port=args.port)
    elif args.command == "demo":
        from .demo import generate
        print(json.dumps(generate(args.output), indent=2))
    else:
        if args.command == "inventory":
            result = inventory(args.source, args.output, interval=args.interval, max_frames=args.max_frames)
        else:
            from .pipeline import reconstruct
            try:
                result = reconstruct(args.source, args.output, interval=args.interval, max_frames=args.max_frames)
            except Exception as exc:
                save_json(args.output / "failure.json", {"status": "failed", "error": str(exc)[:1000]})
                raise
        summary = result["metrics"] if "metrics" in result else {"sources": len(result["sources"]), "frames": len(result["frames"])}
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
