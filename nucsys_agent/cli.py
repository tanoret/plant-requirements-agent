from __future__ import annotations
import argparse
from pathlib import Path
import sys

from .workflow import run_agent
from .serializer.alchemy import dumps
from .logging_config import setup_logging
from .exceptions import AgentError


def _run_interactive_cli(initial_query: str, out_path_str: str, cfg=None) -> None:
    from .conversation import start_conversation, advance_conversation

    turn = start_conversation(initial_query, cfg)
    print(f"\nAgent: {turn.agent_reply}\n")

    while not turn.is_done:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            return

        turn = advance_conversation(turn.state, user_input, initial_query, cfg)
        print(f"\nAgent: {turn.agent_reply}\n")

    if turn.error:
        print(f"ERROR: {turn.error}", file=sys.stderr)
        raise SystemExit(2)

    result = turn.result
    out = Path(out_path_str)
    out.write_bytes(dumps(result.alchemy_db))
    print(f"Wrote: {out.resolve()}")
    print("Spec:", result.spec.model_dump())

    errs = [i for i in result.validation_issues if i.level == "error"]
    warns = [i for i in result.validation_issues if i.level == "warning"]
    export_errs = [i for i in result.export_issues if i.level == "error"]

    if errs:
        print("\nVALIDATION ERRORS:")
        for e in errs:
            print(f"- {e.node_id or ''} {e.message}")
    if warns:
        print("\nVALIDATION WARNINGS (first 20):")
        for w_ in warns[:20]:
            print(f"- {w_.node_id or ''} {w_.message}")
    if export_errs:
        print("\nEXPORT SCHEMA ERRORS:")
        for e in export_errs:
            print(f"- {e.message}")
        raise SystemExit(3)


def main():
    ap = argparse.ArgumentParser(prog="nucsys-agent")
    ap.add_argument("query", type=str, help="Design request in natural language.")
    ap.add_argument("--out", type=str, default="alchemy_out.json", help="Output JSON path.")
    ap.add_argument("--log-level", type=str, default=None, help="DEBUG|INFO|WARNING|ERROR")
    ap.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Engage in a step-by-step conversation to fill spec gaps and review components.",
    )
    args = ap.parse_args()

    setup_logging(args.log_level)

    if args.interactive:
        _run_interactive_cli(args.query, args.out)
        return

    try:
        res = run_agent(args.query)
    except AgentError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(2)

    out_path = Path(args.out)
    out_path.write_bytes(dumps(res.alchemy_db))

    errs = [i for i in res.validation_issues if i.level == "error"]
    warns = [i for i in res.validation_issues if i.level == "warning"]
    export_errs = [i for i in res.export_issues if i.level == "error"]

    print(f"Wrote: {out_path.resolve()}")
    print("Spec:", res.spec.model_dump())

    if errs:
        print("\nVALIDATION ERRORS:")
        for e in errs:
            print(f"- {e.node_id or ''} {e.message}")
    if warns:
        print("\nVALIDATION WARNINGS (first 20):")
        for w_ in warns[:20]:
            print(f"- {w_.node_id or ''} {w_.message}")

    if export_errs:
        print("\nEXPORT SCHEMA ERRORS:")
        for e in export_errs:
            print(f"- {e.message}")
        raise SystemExit(3)

if __name__ == "__main__":
    main()
