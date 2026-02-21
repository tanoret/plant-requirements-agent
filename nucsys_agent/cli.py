from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .workflow import run_agent
from .serializer.alchemy import dumps
from .logging_config import setup_logging
from .exceptions import AgentError

# ──────────────────────────────────────────────────────────────────────────────
# Sentinel command sets (checked at any free-text prompt)
# ──────────────────────────────────────────────────────────────────────────────

_BACK_CMDS = {"back", "menu", "main", "m"}
_EXIT_CMDS = {"exit", "quit", "q", "bye"}
_HELP_CMDS = {"help", "h", "?"}
_REQ_KEYWORDS = {
    "requirements", "requirement", "specs for", "spec for",
    "reqs for", "reqs", "requirements for", "get requirements",
    "component requirements",
}

_DIV   = "─" * 62
_THICK = "═" * 62


def _is_back(s: str)    -> bool: return s.strip().lower() in _BACK_CMDS
def _is_exit(s: str)    -> bool: return s.strip().lower() in _EXIT_CMDS
def _is_help(s: str)    -> bool: return s.strip().lower() in _HELP_CMDS
def _is_req_query(q: str) -> bool:
    ql = q.lower()
    return any(k in ql for k in _REQ_KEYWORDS)

# Alias kept for server.py and any external consumers
_is_requirements_query = _is_req_query


# ──────────────────────────────────────────────────────────────────────────────
# Session state  (persists across all menu actions within one CLI run)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _Session:
    result: Any              = None   # AgentResult | None
    alchemy_db: dict | None  = None
    alchemy_path: Path | None = None
    req_summaries: dict      = field(default_factory=dict)
    title: str               = ""
    out_path: str            = "alchemy_out.json"

    @property
    def has_design(self) -> bool:
        return self.alchemy_db is not None

    def node_count(self) -> int:
        if not self.alchemy_db:
            return 0
        return sum(len(b.get("parts", [])) for b in self.alchemy_db.values())

    def clear_design(self) -> None:
        self.result = None
        self.alchemy_db = None
        self.alchemy_path = None
        self.req_summaries = {}
        self.title = ""


# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────

def _header() -> None:
    print(f"\n{_THICK}")
    print("  nucsys-agent  ·  Nuclear System Design & Requirements")
    print(_THICK)


def _show_context(s: _Session) -> None:
    if s.has_design:
        src   = s.alchemy_path.name if s.alchemy_path else "session"
        label = s.title or src
        n_req = len(s.req_summaries)
        badge = (
            f"  [{n_req} component req{'s' if n_req != 1 else ''} generated]"
            if n_req else ""
        )
        print(f"  Active design : {label}  ·  {s.node_count()} nodes{badge}")
    else:
        print("  No design loaded  —  start by designing or loading a loop")
    print(_DIV)


def _help_text() -> str:
    return f"""
{_DIV}
QUICK REFERENCE
{_DIV}
At any prompt you can type:
  back / menu   → return to the main menu (no data lost)
  exit / quit   → exit the program
  help / ?      → show this reference

Workflow:
  1. Design       describe your system in plain English; the agent asks follow-up
                  questions and produces a sized topology saved as Alchemy JSON.
  2. Requirements pick any sized component; generates an instance requirements
                  document from the 1 500-req baseline (saved as JSON).
  3. Diagram      view or export an IEC-60617 / IEEE-315 single-line diagram
                  (PDF, SVG, or PNG).
  4. Audit        ask questions about the engineering models, correlations,
                  assumptions, and references used in every calculation.

CLI flags (bypass menu — useful for scripting):
  nucsys-agent "query"          one-shot design, then opens menu
  nucsys-agent "query" -i       conversational design, then opens menu
  nucsys-agent -f design.json   load design → requirements / diagram (no menu)
{_DIV}"""


# ──────────────────────────────────────────────────────────────────────────────
# Main menu
# ──────────────────────────────────────────────────────────────────────────────

def _build_menu(s: _Session) -> list[tuple[str, str]]:
    opts: list[tuple[str, str]] = []
    if s.has_design:
        opts.append(("R", "Redesign loop  (start fresh, keeps session open)"))
    opts.append(("D", "Design a new loop"))
    opts.append(("L", "Load an existing design file  (.json)"))
    if s.has_design:
        opts.append(("Q", "Generate component requirements"))
        opts.append(("V", "View / export single-line diagram"))
    opts.append(("A", "Audit engineering models  (explain correlations & references)"))
    opts.append(("H", "Help  (quick reference)"))
    opts.append(("E", "Exit"))
    return opts


def _show_menu(s: _Session) -> str:
    """Display the main menu and return the chosen letter (lowercase)."""
    _header()
    _show_context(s)
    opts = _build_menu(s)
    print()
    for key, label in opts:
        print(f"  [{key}]  {label}")
    print()

    valid = {k.lower() for k, _ in opts}
    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            sys.exit(0)

        rl = raw.lower()
        if rl in valid:
            return rl
        if _is_exit(raw):
            print("\nGoodbye!")
            sys.exit(0)
        if _is_help(raw):
            print(_help_text())
            continue
        if raw:
            keys_str = "  ".join(f"[{k}]" for k, _ in opts)
            print(f"  Unknown option. Valid choices: {keys_str}")


# ──────────────────────────────────────────────────────────────────────────────
# Design actions
# ──────────────────────────────────────────────────────────────────────────────

def _design_interactive(s: _Session, query: str | None = None, cfg=None) -> bool:
    """Conversational design session. Modifies *s* in-place. Returns True on success."""
    from .conversation import start_conversation, advance_conversation

    if query is None:
        print(f"\n{_DIV}")
        print("Design a New Loop")
        print(_DIV)
        print("Describe the system you want to design, for example:")
        print("  '300 MWth PWR primary loop'")
        print("  '500 MWth sodium-cooled fast reactor'")
        print("  (type 'back' to return to the menu)\n")
        try:
            query = input("  Your request: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to menu.")
            return False
        if not query:
            return False
        if _is_back(query):
            return False
        if _is_exit(query):
            print("\nGoodbye!")
            sys.exit(0)

    turn = start_conversation(query, cfg)
    print(f"\nAgent: {turn.agent_reply}\n")

    while not turn.is_done:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession interrupted. Returning to menu.")
            return False
        if _is_back(user_input):
            print("Returning to menu.")
            return False
        if _is_exit(user_input):
            print("\nGoodbye!")
            sys.exit(0)
        if _is_help(user_input):
            print(_help_text())
            continue

        turn = advance_conversation(turn.state, user_input, query, cfg)
        print(f"\nAgent: {turn.agent_reply}\n")

    if turn.error:
        print(f"ERROR: {turn.error}", file=sys.stderr)
        return False

    return _store_result(s, turn.result)


def _design_oneshot(s: _Session, query: str) -> bool:
    """One-shot design (no conversation). Returns True on success."""
    print(f"\nRunning design for: {query!r} …")
    try:
        result = run_agent(query)
    except AgentError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False
    return _store_result(s, result)


def _store_result(s: _Session, result: Any) -> bool:
    """Save *result* to disk and update session state. Returns True on success."""
    out = Path(s.out_path)
    out.write_bytes(dumps(result.alchemy_db))

    errs        = [i for i in result.validation_issues if i.level == "error"]
    warns       = [i for i in result.validation_issues if i.level == "warning"]
    export_errs = [i for i in result.export_issues    if i.level == "error"]

    print(f"\nWrote: {out.resolve()}")
    print("Spec:", result.spec.model_dump())

    if errs:
        print("\nVALIDATION ERRORS:")
        for e in errs:
            print(f"  - {e.node_id or ''} {e.message}")
    if warns:
        print(f"\nVALIDATION WARNINGS ({len(warns)} total, first 20 shown):")
        for w in warns[:20]:
            print(f"  - {w.node_id or ''} {w.message}")
    if export_errs:
        print("\nEXPORT SCHEMA ERRORS:")
        for e in export_errs:
            print(f"  - {e.message}")

    spec = result.spec
    s.result       = result
    s.alchemy_db   = result.alchemy_db
    s.alchemy_path = out
    s.req_summaries = {}   # fresh design clears old requirement summaries
    s.title = (
        f"{spec.thermal_power_MWth} MWth "
        f"{spec.system.replace('_', ' ').title()} ({spec.coolant})"
    )
    print(f"\n  Design complete: {s.title}")
    print("  (From the menu you can now generate requirements or view a diagram.)")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Load action
# ──────────────────────────────────────────────────────────────────────────────

def _action_load(s: _Session) -> None:
    print(f"\n{_DIV}")
    print("Load Existing Design File  (type 'back' to return to menu)")
    print(_DIV)
    try:
        raw = input("  Path to alchemy JSON: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nReturning to menu.")
        return
    if not raw or _is_back(raw):
        return
    if _is_exit(raw):
        print("\nGoodbye!"); sys.exit(0)

    p = Path(raw)
    if not p.exists():
        print(f"  File not found: {p}")
        return
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Could not parse JSON: {e}")
        return

    s.alchemy_db    = db
    s.alchemy_path  = p
    s.result        = None
    s.req_summaries = {}
    s.title         = p.stem.replace("_", " ").title()
    n = sum(len(b.get("parts", [])) for b in db.values())
    print(f"  Loaded: {p.resolve()}  ({n} nodes)")
    print("  (From the menu you can now generate requirements or view a diagram.)")


# ──────────────────────────────────────────────────────────────────────────────
# Requirements action  (shared between session menu and --from-design)
# ──────────────────────────────────────────────────────────────────────────────

def _action_requirements(s: _Session) -> None:
    """Menu entry point for requirements generation."""
    if not s.has_design:
        print("  No design loaded. Design or load a system first.")
        return

    from .requirements.bridge import list_design_components_from_db, all_node_props_from_db

    print(f"\n{_DIV}")
    print("Generate Component Requirements  (type 'back' to return to menu)")
    print(_DIV)

    components = list_design_components_from_db(s.alchemy_db)
    if not components:
        print(
            "  No components with a requirements baseline found in this design.\n"
            "  Supported types: pump, steam_generator, turbine."
        )
        return

    all_props = all_node_props_from_db(s.alchemy_db)
    new = _requirements_loop(components, all_props)
    s.req_summaries.update(new)
    if new:
        print(f"\n  Requirements generated for: {', '.join(new.keys())}")
        print("  (From the menu you can now view the diagram with requirement badges.)")


def _requirements_loop(components: list[dict], all_node_props: dict) -> dict:
    """Interactive loop: select component → run conversation → save JSON.

    Returns a ``{node_name: {applicable, tbd, generated}}`` dict.
    Type 'back' at any prompt to return to the caller immediately.
    """
    from .requirements.conversation import (
        start_req_conversation_from_design,
        advance_req_conversation_from_design,
    )

    remaining     = list(components)
    req_summaries: dict = {}

    while remaining:
        print(f"\n{_DIV}")
        print("Available components:")
        for i, comp in enumerate(remaining, 1):
            print(f"  {i}.  {comp['summary']}")
        print()
        print("  Enter number or name to select, Enter to stop,")
        print("  or 'back' to return to the main menu.")
        print()

        try:
            raw = input("  Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to menu.")
            return req_summaries

        if not raw:
            return req_summaries
        if _is_back(raw):
            print("Returning to menu.")
            return req_summaries
        if _is_exit(raw):
            print("\nGoodbye!"); sys.exit(0)
        if _is_help(raw):
            print(_help_text()); continue

        chosen = _resolve_component(raw, remaining)
        if chosen is None:
            continue

        # Output file
        safe        = re.sub(r"[^\w]+", "_", chosen["node_name"].lower()).strip("_")
        default_out = f"{safe}_reqs.json"
        try:
            out_raw = input(f"  Output file [{default_out}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return req_summaries
        if _is_back(out_raw):
            print("Returning to menu.")
            return req_summaries
        out_path = Path(out_raw) if out_raw else Path(default_out)

        # Requirements conversation
        turn = start_req_conversation_from_design(
            chosen["node_name"], chosen["node_props"], all_node_props,
        )
        print(f"\nAgent: {turn.agent_reply}\n")

        while not turn.is_done:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nReturning to menu.")
                return req_summaries
            if _is_back(user_input):
                print("Returning to menu.")
                return req_summaries
            if _is_exit(user_input):
                print("\nGoodbye!"); sys.exit(0)
            if _is_help(user_input):
                print(_help_text()); continue

            turn = advance_req_conversation_from_design(turn.state, user_input)
            print(f"\nAgent: {turn.agent_reply}\n")

        if turn.error:
            print(f"  ERROR: {turn.error}", file=sys.stderr)
        elif turn.result_json is not None:
            out_path.write_text(
                json.dumps(turn.result_json, indent=2), encoding="utf-8"
            )
            print(f"  Saved: {out_path.resolve()}")
            v = turn.result_json.get("validation", {})
            req_summaries[chosen["node_name"]] = {
                "applicable": v.get("total_applicable", len(
                    turn.result_json.get("applicable_requirements", [])
                )),
                "tbd": v.get("tbd_count", 0),
                "generated": True,
            }

        remaining = [c for c in remaining if c["node_name"] != chosen["node_name"]]
        if not remaining:
            print("  All available components processed.")
            return req_summaries

        try:
            again = input("\n  Another component? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return req_summaries
        if again not in ("y", "yes"):
            return req_summaries

    return req_summaries


def _resolve_component(raw: str, remaining: list[dict]) -> dict | None:
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(remaining):
            return remaining[idx]
        print(f"  Please enter a number between 1 and {len(remaining)}.")
        return None
    matches = [
        c for c in remaining
        if raw.lower() in c["node_name"].lower()
        or raw.lower() in c["component_key"].lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"  Ambiguous — matches: {', '.join(m['node_name'] for m in matches)}")
    else:
        print(f"  Not found. Options: {', '.join(c['node_name'] for c in remaining)}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Diagram action
# ──────────────────────────────────────────────────────────────────────────────

def _action_diagram(s: _Session) -> None:
    if not s.has_design:
        print("  No design loaded. Design or load a system first.")
        return

    try:
        from .visualization.sld import SingleLineDiagram
    except ImportError:
        print(
            "\n  matplotlib not installed. Run:\n"
            "    pip install matplotlib\n"
            "  or:  pip install 'nucsys-agent[diagram]'"
        )
        return

    print(f"\n{_DIV}")
    print("Single-Line Diagram  (type 'back' to return to menu)")
    print(_DIV)

    if s.req_summaries:
        comps = ", ".join(s.req_summaries.keys())
        print(f"  Requirements badges will be shown for: {comps}")
    else:
        print("  Tip: generate requirements first to show badges on the diagram.")
    print()

    try:
        style_raw = input("  Style [normal / blueprint, default: normal]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if _is_back(style_raw):
        return
    if _is_exit(style_raw):
        print("\nGoodbye!"); sys.exit(0)
    blueprint = style_raw in ("blueprint", "b", "bp")

    sld = SingleLineDiagram(
        s.alchemy_db,
        req_info=s.req_summaries,
        blueprint=blueprint,
        title=s.title,
    )
    sld.draw()

    try:
        sld.show()
    except Exception as exc:
        print(f"  (Interactive display unavailable: {exc})")

    try:
        fmt = input("\n  Export? (pdf / svg / png / N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if _is_back(fmt):
        return
    if fmt not in ("pdf", "svg", "png"):
        return

    default_path = f"diagram.{fmt}"
    try:
        path_raw = input(f"  Output file [{default_path}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    out = Path(path_raw) if path_raw else Path(default_path)
    sld.export(out)
    print(f"  Exported: {out.resolve()}")


# ──────────────────────────────────────────────────────────────────────────────
# Audit action  (model auditability Q&A)
# ──────────────────────────────────────────────────────────────────────────────

def _action_audit(_s=None) -> None:
    """Interactive Q&A loop for model auditability.

    The user can ask any free-text question about the engineering correlations,
    fluid property sources, energy conservation approach, hydraulic models,
    optimizer objective, and assumptions.  Type 'back' to return to the menu.
    """
    from .audit import AuditEngine

    engine = AuditEngine()

    print(f"\n{_DIV}")
    print("Audit Engineering Models")
    print(_DIV)
    print("Ask questions about the models, correlations, and references used.")
    print("Examples:")
    print("  'How is energy conservation done?'")
    print("  'What fluid properties are implemented and from where?'")
    print("  'How is the steam generator sized?'")
    print("  'What are the model assumptions?'")
    print("  'list' — show all available topics")
    print("  'back' — return to the main menu")
    print()

    while True:
        try:
            question = input("  Question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to menu.")
            return

        if not question:
            continue
        if _is_back(question):
            print("Returning to menu.")
            return
        if _is_exit(question):
            print("\nGoodbye!"); sys.exit(0)

        answer = engine.ask(question)
        print()
        # Indent every line slightly for readability
        for line in answer.splitlines():
            print(f"  {line}" if line.strip() else "")
        print()

        try:
            again = input("  Another question? (Enter to continue, 'back' to return): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to menu.")
            return
        if not again or _is_back(again):
            return
        # Any other input is treated as the next question
        if again:
            answer = engine.ask(again)
            print()
            for line in answer.splitlines():
                print(f"  {line}" if line.strip() else "")
            print()


# ──────────────────────────────────────────────────────────────────────────────
# Standalone requirements CLI  (no existing design — pure requirements query)
# ──────────────────────────────────────────────────────────────────────────────

def _run_requirements_standalone(initial_query: str, out_path_str: str) -> None:
    from .requirements.conversation import start_req_conversation, advance_req_conversation

    turn = start_req_conversation(initial_query)
    print(f"\nAgent: {turn.agent_reply}\n")

    while not turn.is_done:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            return
        if _is_back(user_input) or _is_exit(user_input):
            return
        if _is_help(user_input):
            print(_help_text()); continue

        turn = advance_req_conversation(turn.state, user_input, initial_query)
        print(f"\nAgent: {turn.agent_reply}\n")

    if turn.error:
        print(f"ERROR: {turn.error}", file=sys.stderr)
        return

    out = Path(out_path_str)
    out.write_text(json.dumps(turn.result_json, indent=2), encoding="utf-8")
    print(f"Wrote: {out.resolve()}")


# ──────────────────────────────────────────────────────────────────────────────
# --from-design bypass mode  (kept for backward compatibility / scripting)
# ──────────────────────────────────────────────────────────────────────────────

def _run_from_design(design_path_str: str) -> None:
    """Load an existing alchemy JSON and run requirements + optional diagram."""
    from .requirements.bridge import list_design_components_from_db, all_node_props_from_db

    p = Path(design_path_str)
    if not p.exists():
        print(f"ERROR: file not found: {p}", file=sys.stderr)
        raise SystemExit(2)
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: could not parse JSON: {e}", file=sys.stderr)
        raise SystemExit(2)

    components = list_design_components_from_db(db)
    if not components:
        print(
            "\nNo components with a requirements baseline found in this design.\n"
            "Supported: pump, steam_generator, turbine."
        )
        return

    all_props = all_node_props_from_db(db)
    print(f"\nLoaded design: {p.resolve()}")
    req_summaries = _requirements_loop(components, all_props)

    try:
        diag_ans = input("\nGenerate single-line diagram? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if diag_ans in ("y", "yes"):
        s = _Session()
        s.alchemy_db    = db
        s.alchemy_path  = p
        s.req_summaries = req_summaries
        s.title         = p.stem.replace("_", " ").title()
        _action_diagram(s)


# ──────────────────────────────────────────────────────────────────────────────
# Main session loop  (interactive menu)
# ──────────────────────────────────────────────────────────────────────────────

def _run_session(args) -> None:
    """Main interactive session: shows menu, dispatches actions, loops."""
    s = _Session(out_path=args.out)

    # If a query was provided via CLI args, run it immediately before the menu.
    if args.query:
        if _is_req_query(args.query):
            # Requirements-only query → standalone then fall through to menu.
            _run_requirements_standalone(args.query, args.out)
        elif getattr(args, "interactive", False):
            _design_interactive(s, query=args.query)
        else:
            _design_oneshot(s, args.query)

    # ── Main menu loop ────────────────────────────────────────────────────────
    while True:
        choice = _show_menu(s)

        if choice == "d":
            # If the user backs out, the old design (if any) is preserved.
            # _store_result() will overwrite state only on successful completion.
            _design_interactive(s, query=None)

        elif choice == "r":
            # Redesign: same as "D" but the intention is clear to the user.
            # Old design is kept if the user backs out of the new design prompt.
            _design_interactive(s, query=None)

        elif choice == "l":
            _action_load(s)

        elif choice == "q":
            _action_requirements(s)

        elif choice == "v":
            _action_diagram(s)

        elif choice == "a":
            _action_audit(s)

        elif choice == "h":
            print(_help_text())
            try:
                input("  Press Enter to continue…")
            except (EOFError, KeyboardInterrupt):
                pass

        elif choice == "e":
            print("\nGoodbye!")
            break


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        prog="nucsys-agent",
        description=(
            "Nuclear system design, requirements, and diagram tool. "
            "Without arguments opens the interactive menu."
        ),
    )
    ap.add_argument(
        "query", nargs="?", default=None,
        help="Design or requirements request in natural language. Omit to open the menu.",
    )
    ap.add_argument("--out", default="alchemy_out.json", help="Output JSON path.")
    ap.add_argument("--log-level", default=None, help="DEBUG | INFO | WARNING | ERROR")
    ap.add_argument(
        "--interactive", "-i", action="store_true",
        help="Use conversational design rather than one-shot (requires a query).",
    )
    ap.add_argument(
        "--from-design", "-f", type=str, default=None, metavar="PATH",
        help=(
            "Load an existing alchemy JSON and interactively generate requirements "
            "(scripting-friendly bypass — skips the interactive menu)."
        ),
    )
    args = ap.parse_args()
    setup_logging(args.log_level)

    # Direct bypass: --from-design loads the file and runs requirements + diagram.
    if args.from_design:
        _run_from_design(args.from_design)
        return

    # Everything else goes through the interactive session / menu.
    _run_session(args)


if __name__ == "__main__":
    main()
