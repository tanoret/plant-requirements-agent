from __future__ import annotations
import argparse
from pathlib import Path
import sys

from .workflow import run_agent
from .serializer.alchemy import dumps
from .logging_config import setup_logging
from .exceptions import AgentError

def main():
    ap = argparse.ArgumentParser(prog="nucsys-agent")
    ap.add_argument("query", type=str, help="Design request in natural language.")
    ap.add_argument("--out", type=str, default="alchemy_out.json", help="Output JSON path.")
    ap.add_argument("--log-level", type=str, default=None, help="DEBUG|INFO|WARNING|ERROR")
    args = ap.parse_args()

    setup_logging(args.log_level)

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
