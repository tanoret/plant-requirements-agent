"""
Interactive conversation engine for nucsys-agent.

Manages a three-phase dialogue:
  1. spec_gaps     – ask clarifying questions to fill missing DesignSpec fields
  2. component_review – show proposed topology nodes, let user accept or remove some
  3. done          – run the design pipeline with confirmed spec + pruned topology

Works in two modes:
  - Stateful (CLI): call start_conversation() then advance_conversation() in a loop.
  - Stateless (API): call replay_history() to reconstruct ChatState from message
    history, then call advance_conversation() with the latest user message.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .models import DesignSpec, PatternCard
from .spec_parser import _MPA_RE, _POWER_RE, _TEMP_C_RE

if TYPE_CHECKING:
    from .config import AgentConfig
    from .workflow import AgentResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Phase = Literal["spec_gaps", "component_review", "done"]


@dataclass
class ChatMessage:
    role: Literal["user", "agent"]
    content: str


@dataclass
class ChatState:
    phase: Phase = "spec_gaps"
    spec: DesignSpec | None = None
    card_id: str | None = None
    removed_nodes: list[str] = field(default_factory=list)
    spec_fields_asked: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    agent_reply: str
    state: ChatState
    is_done: bool
    result: "AgentResult | None" = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Question catalogue  (field_name, question_text, is_required)
# ---------------------------------------------------------------------------

_SPEC_QUESTIONS: list[tuple[str, str, bool]] = [
    (
        "system",
        "Which system are you designing?\n  Options: primary_loop, bop_loop, intermediate_loop",
        True,
    ),
    (
        "thermal_power_MWth",
        "What is the thermal power in MWth?  (e.g. '300 MWth' or just '300')",
        True,
    ),
    (
        "coolant",
        "What coolant?  Options: water, sodium, co2, helium",
        True,
    ),
    (
        "objective",
        "Optimization objective?  Options: baseline, min_pump_power, min_UA, balanced\n"
        "  [Press Enter to accept default: balanced]",
        False,
    ),
    (
        "primary_pressure_MPa",
        "Primary pressure in MPa?  (e.g. '15.5 MPa')\n  [Enter for default: 15.5 MPa]",
        False,
    ),
    (
        "primary_hot_leg_C",
        "Primary hot-leg temperature in °C?  (e.g. '320')\n  [Enter for default: 320 °C]",
        False,
    ),
    (
        "secondary_pressure_MPa",
        "Secondary (steam) pressure in MPa?\n  [Enter for default: 6.5 MPa]",
        False,
    ),
    (
        "condenser_pressure_MPa",
        "Condenser pressure in MPa?\n  [Enter for default: 0.01 MPa]",
        False,
    ),
    (
        "secondary_feedwater_C",
        "Feedwater temperature in °C?\n  [Enter for default: 220 °C]",
        False,
    ),
    (
        "secondary_steam_C",
        "Steam outlet temperature in °C?\n  [Enter for default: 280 °C]",
        False,
    ),
]

# Map field → question text (used by replay_history to identify which field was asked)
_FIELD_TO_QUESTION: dict[str, str] = {f: q for f, q, _ in _SPEC_QUESTIONS}


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

def _field_is_filled(spec: DesignSpec, field_name: str) -> bool:
    """Return True if the spec field already has a non-default, non-None value."""
    val = getattr(spec, field_name)
    if val is None:
        return False
    if isinstance(val, str) and val == "unknown":
        return False
    return True


def _next_question(spec: DesignSpec, asked: list[str]) -> tuple[str, str] | None:
    """Return (field_name, question_text) for the next missing required field,
    or None when all required fields are filled.

    Optional fields are intentionally skipped — they fall back to AgentConfig
    defaults so the conversation stays short.
    """
    for field_name, question, is_required in _SPEC_QUESTIONS:
        if not is_required:
            continue
        if field_name in asked:
            continue
        if not _field_is_filled(spec, field_name):
            return field_name, question
    return None


# ---------------------------------------------------------------------------
# Answer parsing  (reuses regexes from spec_parser)
# ---------------------------------------------------------------------------

def _parse_answer_into_spec(spec: DesignSpec, field_name: str, answer: str) -> DesignSpec:
    """Return a new DesignSpec with the parsed answer applied.
    If parsing fails the field is left unchanged (question will be re-asked)."""
    data = spec.model_dump()
    al = answer.strip().lower()

    if field_name == "system":
        if "primary" in al:
            data["system"] = "primary_loop"
        elif "bop" in al or "balance" in al or "rankine" in al:
            data["system"] = "bop_loop"
        elif "intermediate" in al:
            data["system"] = "intermediate_loop"

    elif field_name == "thermal_power_MWth":
        m = _POWER_RE.search(answer)
        if m:
            data["thermal_power_MWth"] = float(m.group(1))
        else:
            try:
                data["thermal_power_MWth"] = float(answer.strip())
            except ValueError:
                pass

    elif field_name == "coolant":
        for c in ("sodium", "co2", "helium"):
            if c in al:
                data["coolant"] = c
                break
        else:
            if "water" in al or "light water" in al or "pwr" in al:
                data["coolant"] = "water"

    elif field_name == "objective":
        if al == "" or "balanced" in al:
            data["objective"] = "balanced"
        elif "min_pump" in al or "pump" in al:
            data["objective"] = "min_pump_power"
        elif "min_ua" in al or " ua" in al:
            data["objective"] = "min_UA"
        elif "baseline" in al:
            data["objective"] = "baseline"

    elif field_name in ("primary_pressure_MPa", "secondary_pressure_MPa", "condenser_pressure_MPa"):
        if al == "":
            pass  # leave None → workflow picks up AgentConfig default
        else:
            m = _MPA_RE.search(answer)
            if m:
                data[field_name] = float(m.group(1))
            else:
                try:
                    data[field_name] = float(answer.strip())
                except ValueError:
                    pass

    elif field_name in ("primary_hot_leg_C", "secondary_feedwater_C", "secondary_steam_C"):
        if al == "":
            pass  # leave None → workflow picks up AgentConfig default
        else:
            m = _TEMP_C_RE.search(answer)
            if m:
                data[field_name] = float(m.group(1))
            else:
                try:
                    data[field_name] = float(answer.strip())
                except ValueError:
                    pass

    return DesignSpec(**data)


# ---------------------------------------------------------------------------
# Component review helpers
# ---------------------------------------------------------------------------

def _format_node_list(topo_card: PatternCard) -> str:
    """Numbered, building-grouped list of nodes from the topology template."""
    if not topo_card.topology_template:
        return "  (No topology template — sizing-only card)"
    lines: list[str] = []
    for b in topo_card.topology_template["buildings"]:
        lines.append(f"  [{b['name']}]")
        for i, node in enumerate(b["nodes"], 1):
            lines.append(f"    {i}. {node['name']}  ({node['canonical_type']})")
    return "\n".join(lines)


def _parse_removal_request(answer: str, topo_card: PatternCard) -> list[str]:
    """Return list of node names the user wants removed.
    Empty / affirmative answers return []. Otherwise scans for node names."""
    al = answer.strip().lower()
    if not al or al in ("ok", "yes", "accept", "looks good", "proceed", "continue", "go", "done"):
        return []

    all_names: list[str] = []
    if topo_card.topology_template:
        for b in topo_card.topology_template["buildings"]:
            for node in b["nodes"]:
                all_names.append(node["name"])

    removed = [name for name in all_names if name.lower() in al]
    return removed


def _prune_topology(topo_card: PatternCard, removed_nodes: list[str]) -> dict[str, Any]:
    """Deep-copy topology_template and strip the named nodes + their edges."""
    topo = copy.deepcopy(topo_card.topology_template)
    if not removed_nodes or topo is None:
        return topo  # type: ignore[return-value]

    removed_set = set(removed_nodes)
    for b in topo["buildings"]:
        b["nodes"] = [n for n in b["nodes"] if n["name"] not in removed_set]
        b["edges"] = [
            e for e in b["edges"]
            if e[0] not in removed_set and e[1] not in removed_set
        ]
    return topo


# ---------------------------------------------------------------------------
# Card selection (delegates to workflow to avoid duplication)
# ---------------------------------------------------------------------------

def _select_card(spec: DesignSpec, initial_query: str, cfg: "AgentConfig") -> PatternCard:
    from .rag.store import CardStore
    from .workflow import _choose_topology_card

    store = CardStore.load_from_dir(cfg.cards_dir)
    cards = store.retrieve(initial_query, tags=[spec.system, spec.coolant], k=8)
    return _choose_topology_card(cards, spec)


# ---------------------------------------------------------------------------
# Stateless API: history replay
# ---------------------------------------------------------------------------

def replay_history(messages: list[ChatMessage], initial_query: str) -> ChatState:
    """Reconstruct ChatState deterministically from a full message history.

    Protocol:
    - messages[0] is the user's initial query (already parsed below).
    - Then pairs of (agent question, user answer) follow.
    - Phase transitions when _next_question returns None.
    """
    from .config import AgentConfig
    from .spec_parser import parse_design_spec

    cfg = AgentConfig()
    spec = parse_design_spec(initial_query)
    state = ChatState(phase="spec_gaps", spec=spec)

    # Separate agent messages and user answers (skip first user message = initial query)
    agent_msgs = [m for m in messages if m.role == "agent"]
    user_answers = [m for m in messages if m.role == "user"][1:]  # skip initial query

    for agent_msg, user_ans in zip(agent_msgs, user_answers):
        if state.phase == "spec_gaps":
            # Identify the field by matching agent question text
            for field_name, q_text, _ in _SPEC_QUESTIONS:
                if field_name not in state.spec_fields_asked and q_text in agent_msg.content:
                    state.spec_fields_asked.append(field_name)
                    state.spec = _parse_answer_into_spec(state.spec, field_name, user_ans.content)
                    break

            if _next_question(state.spec, state.spec_fields_asked) is None:
                try:
                    card = _select_card(state.spec, initial_query, cfg)
                    state.card_id = card.id
                except Exception:
                    pass
                state.phase = "component_review"

        elif state.phase == "component_review":
            if state.card_id:
                card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
                if card:
                    removed = _parse_removal_request(user_ans.content, card)
                    state.removed_nodes = removed
            state.phase = "done"

    return state


def _get_card_by_id(
    card_id: str,
    initial_query: str,
    spec: DesignSpec,
    cfg: "AgentConfig",
) -> PatternCard | None:
    from .rag.store import CardStore

    store = CardStore.load_from_dir(cfg.cards_dir)
    cards = store.retrieve(initial_query, tags=[spec.system, spec.coolant], k=8)
    return next((c for c in cards if c.id == card_id), None)


# ---------------------------------------------------------------------------
# Conversation driver
# ---------------------------------------------------------------------------

def start_conversation(
    initial_query: str,
    cfg: "AgentConfig | None" = None,
) -> TurnResult:
    """Create initial ChatState and return the first agent question.
    If the query is already fully specified, skips straight to Phase 2."""
    from .config import AgentConfig
    from .spec_parser import parse_design_spec

    cfg = cfg or AgentConfig()
    spec = parse_design_spec(initial_query)
    state = ChatState(phase="spec_gaps", spec=spec)

    next_q = _next_question(spec, [])
    if next_q is None:
        # Query fully specified — transition to component review immediately
        return _transition_to_component_review(state, initial_query, cfg)

    field_name, question = next_q
    state.spec_fields_asked.append(field_name)
    return TurnResult(agent_reply=question, state=state, is_done=False)


def advance_conversation(
    state: ChatState,
    user_message: str,
    initial_query: str,
    cfg: "AgentConfig | None" = None,
) -> TurnResult:
    """Process one user message and return the next agent reply (or final result)."""
    from .config import AgentConfig

    cfg = cfg or AgentConfig()

    if state.phase == "spec_gaps":
        # Apply the answer to the last question asked
        if state.spec_fields_asked:
            last_field = state.spec_fields_asked[-1]
            state.spec = _parse_answer_into_spec(state.spec, last_field, user_message)

        next_q = _next_question(state.spec, state.spec_fields_asked)
        if next_q:
            field_name, question = next_q
            state.spec_fields_asked.append(field_name)
            return TurnResult(agent_reply=question, state=state, is_done=False)

        # All gaps filled → Phase 2
        return _transition_to_component_review(state, initial_query, cfg)

    elif state.phase == "component_review":
        return _handle_component_review(state, user_message, initial_query, cfg)

    # phase == "done" already
    return TurnResult(agent_reply="Design already complete.", state=state, is_done=True)


def _transition_to_component_review(
    state: ChatState,
    initial_query: str,
    cfg: "AgentConfig",
) -> TurnResult:
    """Pick the topology card and ask the user to review the component list."""
    from .exceptions import CardError

    try:
        card = _select_card(state.spec, initial_query, cfg)
    except (CardError, Exception) as e:
        return TurnResult(
            agent_reply=f"Could not find a matching pattern card: {e}",
            state=state,
            is_done=True,
            error=str(e),
        )

    state.card_id = card.id
    state.phase = "component_review"

    node_list = _format_node_list(card)
    reply = (
        f"Spec confirmed. Matched pattern: {card.title}\n\n"
        f"Proposed components:\n{node_list}\n\n"
        "Type 'ok' to accept, or name components to remove (e.g. 'remove TAV and FWCV')."
    )
    return TurnResult(agent_reply=reply, state=state, is_done=False)


def _handle_component_review(
    state: ChatState,
    user_message: str,
    initial_query: str,
    cfg: "AgentConfig",
) -> TurnResult:
    """Parse removal request, prune topology, run design pipeline."""
    from .workflow import run_agent_from_spec

    card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
    if card is None:
        return TurnResult(
            agent_reply="Internal error: topology card not found.",
            state=state,
            is_done=True,
            error="Card not found",
        )

    removed = _parse_removal_request(user_message, card)
    state.removed_nodes = removed
    state.phase = "done"

    pruned_topo = _prune_topology(card, removed)
    try:
        result = run_agent_from_spec(state.spec, pruned_topo, card, cfg)
    except Exception as e:
        log.exception("Pipeline error in interactive mode")
        return TurnResult(
            agent_reply=f"Design pipeline error: {e}",
            state=state,
            is_done=True,
            error=str(e),
        )

    errs = [i for i in result.validation_issues if i.level == "error"]
    warns = [i for i in result.validation_issues if i.level == "warning"]
    msg_parts = ["Design complete."]
    if removed:
        msg_parts.append(f"Removed: {', '.join(removed)}.")
    msg_parts.append(f"{len(errs)} error(s), {len(warns)} warning(s).")
    return TurnResult(
        agent_reply=" ".join(msg_parts),
        state=state,
        is_done=True,
        result=result,
    )
