"""
Interactive conversation engine for nucsys-agent.

Manages a four-phase dialogue:
  1. spec_gaps       – ask clarifying questions to fill missing DesignSpec fields
  2. param_review    – show all operating parameters (with defaults), let user override
  3. component_review – show proposed topology nodes, let user remove or override properties
  4. design_review   – run pipeline, show key metrics, let user refine or finalise

Works in two modes:
  - Stateful (CLI): call start_conversation() then advance_conversation() in a loop.
  - Stateless (API): call replay_history() to reconstruct ChatState from message
    history, then call advance_conversation() with the latest user message.
"""
from __future__ import annotations

import copy
import logging
import re
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

Phase = Literal["spec_gaps", "param_review", "component_review", "design_review", "done"]

_AFFIRMATIVE = {"ok", "yes", "accept", "looks good", "proceed", "continue", "go", "good", "done", ""}


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
    node_overrides: dict[str, dict] = field(default_factory=dict)


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
]

# Map field → question text (used by replay_history to identify which field was asked)
_FIELD_TO_QUESTION: dict[str, str] = {f: q for f, q, _ in _SPEC_QUESTIONS}


# ---------------------------------------------------------------------------
# Phase 1: spec_gaps helpers
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
    or None when all required fields are filled."""
    for field_name, question, is_required in _SPEC_QUESTIONS:
        if not is_required:
            continue
        if field_name in asked:
            continue
        if not _field_is_filled(spec, field_name):
            return field_name, question
    return None


def _parse_answer_into_spec(spec: DesignSpec, field_name: str, answer: str) -> DesignSpec:
    """Return a new DesignSpec with the parsed answer applied."""
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

    return DesignSpec(**data)


# ---------------------------------------------------------------------------
# Phase 2: param_review helpers
# ---------------------------------------------------------------------------

def _format_param_summary(spec: DesignSpec, cfg: "AgentConfig") -> str:
    """Format a two-column table showing current parameter values with (default)/(set) tags."""
    def _tag(spec_val: Any) -> str:
        return "(set)" if spec_val is not None else "(default)"

    p_press = spec.primary_pressure_MPa or cfg.default_primary_pressure_MPa
    p_hot   = spec.primary_hot_leg_C or cfg.default_primary_hot_leg_C
    sec_p   = spec.secondary_pressure_MPa or cfg.default_secondary_pressure_MPa
    cond_p  = spec.condenser_pressure_MPa or cfg.default_condenser_pressure_MPa
    fw_t    = spec.secondary_feedwater_C or cfg.default_secondary_feedwater_C
    stm_t   = spec.secondary_steam_C or cfg.default_secondary_steam_C
    obj     = spec.objective

    lines = [
        "Operating parameters:",
        f"  Optimization:       {obj:<20} (set)",
        f"  Primary pressure:   {p_press:.2f} MPa           {_tag(spec.primary_pressure_MPa)}",
        f"  Primary hot-leg:    {p_hot:.1f} °C             {_tag(spec.primary_hot_leg_C)}",
        f"  Steam pressure:     {sec_p:.2f} MPa           {_tag(spec.secondary_pressure_MPa)}",
        f"  Condenser pressure: {cond_p:.4f} MPa         {_tag(spec.condenser_pressure_MPa)}",
        f"  Feedwater temp:     {fw_t:.1f} °C             {_tag(spec.secondary_feedwater_C)}",
        f"  Steam out temp:     {stm_t:.1f} °C             {_tag(spec.secondary_steam_C)}",
        "",
        "Type 'ok' to use these values, or override any parameter, e.g.:",
        "  'primary pressure 16 MPa'  /  'hot leg 325°C'  /  'steam pressure 7 MPa'",
        "  'objective min_pump_power'  /  'feedwater 230°C'  /  'condenser 0.008 MPa'",
    ]
    return "\n".join(lines)


def _parse_param_overrides(answer: str, spec: DesignSpec) -> DesignSpec:
    """Parse free-form text for operating-parameter overrides and return updated DesignSpec."""
    data = spec.model_dump()
    al = answer.strip().lower()

    # Objective
    if "min_pump" in al or "min pump" in al:
        data["objective"] = "min_pump_power"
    elif "min_ua" in al or "min ua" in al:
        data["objective"] = "min_UA"
    elif "baseline" in al:
        data["objective"] = "baseline"
    elif "balanced" in al:
        data["objective"] = "balanced"

    # Condenser pressure — check before generic "pressure" to avoid mismatching
    if "condenser" in al:
        m = _MPA_RE.search(answer)
        if m:
            data["condenser_pressure_MPa"] = float(m.group(1))
        else:
            # Try bare float
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["condenser_pressure_MPa"] = float(nums[-1])

    # Steam / secondary pressure
    if "steam pressure" in al or "secondary pressure" in al or "boiler pressure" in al:
        m = _MPA_RE.search(answer)
        if m:
            data["secondary_pressure_MPa"] = float(m.group(1))
        else:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["secondary_pressure_MPa"] = float(nums[-1])

    # Primary pressure (do after steam so "secondary pressure" doesn't fall through here)
    if ("primary pressure" in al or "inlet pressure" in al) and "condenser" not in al:
        m = _MPA_RE.search(answer)
        if m:
            data["primary_pressure_MPa"] = float(m.group(1))
        else:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["primary_pressure_MPa"] = float(nums[-1])

    # Hot-leg / primary temperature
    if "hot leg" in al or "hot-leg" in al or "primary temp" in al or "primary hot" in al:
        m = _TEMP_C_RE.search(answer)
        if m:
            data["primary_hot_leg_C"] = float(m.group(1))
        else:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["primary_hot_leg_C"] = float(nums[-1])

    # Feedwater temperature
    if "feedwater" in al or "feed water" in al or "fw temp" in al:
        m = _TEMP_C_RE.search(answer)
        if m:
            data["secondary_feedwater_C"] = float(m.group(1))
        else:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["secondary_feedwater_C"] = float(nums[-1])

    # Steam outlet temperature
    if "steam temp" in al or "steam out" in al or "steam outlet" in al or "steam temperature" in al:
        m = _TEMP_C_RE.search(answer)
        if m:
            data["secondary_steam_C"] = float(m.group(1))
        else:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                data["secondary_steam_C"] = float(nums[-1])

    return DesignSpec(**data)


# ---------------------------------------------------------------------------
# Phase 3: component_review helpers
# ---------------------------------------------------------------------------

def _format_node_list(topo_card: PatternCard, removed_nodes: list[str] | None = None) -> str:
    """Numbered, building-grouped list of nodes from the topology template.
    Nodes in removed_nodes are shown with a strikethrough marker."""
    removed_set = set(removed_nodes or [])
    if not topo_card.topology_template:
        return "  (No topology template — sizing-only card)"
    lines: list[str] = []
    for b in topo_card.topology_template["buildings"]:
        lines.append(f"  [{b['name']}]")
        for i, node in enumerate(b["nodes"], 1):
            name = node["name"]
            marker = "  [REMOVED]" if name in removed_set else ""
            lines.append(f"    {i}. {name}  ({node['canonical_type']}){marker}")
    return "\n".join(lines)


def _parse_removal_request(answer: str, topo_card: PatternCard) -> list[str]:
    """Return list of node names the user wants removed. Empty/affirmative returns []."""
    al = answer.strip().lower()
    if al in _AFFIRMATIVE:
        return []

    all_names: list[str] = []
    if topo_card.topology_template:
        for b in topo_card.topology_template["buildings"]:
            for node in b["nodes"]:
                all_names.append(node["name"])

    removed = [name for name in all_names if name.lower() in al]
    return removed


# Property alias table: alias → (property_key_generic, property_key_for_turbine)
_PROP_ALIASES: dict[str, tuple[str, str]] = {
    "efficiency":  ("efficiency", "isentropic_efficiency"),
    "area":        ("area_m2", "area_m2"),
    "power":       ("shaft_power_MW", "gross_power_MWe"),
    "delta_p":     ("delta_p_MPa", "delta_p_MPa"),
    "dp":          ("delta_p_MPa", "delta_p_MPa"),
}


def _parse_property_override(answer: str, all_node_names: list[str]) -> dict[str, dict]:
    """Parse 'set <NodeName> <property_alias> <float_value>' from answer.

    Returns {node_name: {prop_key: value}} or {} if no match.
    """
    overrides: dict[str, dict] = {}
    al = answer.strip().lower()

    # Only process if "set" keyword appears
    if "set" not in al:
        return overrides

    for node_name in all_node_names:
        if node_name.lower() not in al:
            continue
        for alias, (generic_key, turbine_key) in _PROP_ALIASES.items():
            if alias not in al:
                continue
            # Extract trailing float value
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if not nums:
                continue
            val = float(nums[-1])
            prop_key = turbine_key if node_name == "Turbine" else generic_key
            overrides.setdefault(node_name, {})[prop_key] = val

    return overrides


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
# Phase 4: design_review helpers
# ---------------------------------------------------------------------------

def _format_design_summary(result: "AgentResult") -> str:
    """Format key design metrics from a completed AgentResult."""
    lines: list[str] = ["Design results:"]

    # Gather node properties by name
    props_by_name: dict[str, dict] = {}
    for b in result.buildings.values():
        for n in b.parts:
            props_by_name[n.name] = n.properties

    if "Primary Source" in props_by_name:
        p = props_by_name["Primary Source"]
        lines.append(f"  Thermal power:      {p.get('thermal_power_MWth', '?')} MWth")
        lines.append(f"  Primary ΔT:         {p.get('chosen_primary_deltaT_K', '?'):.1f} K")
        lines.append(f"  Hot-leg / Cold-leg: {p.get('hot_leg_C', '?'):.0f} °C / {p.get('cold_leg_C', '?'):.0f} °C")

    if "Primary Sink" in props_by_name:
        p = props_by_name["Primary Sink"]
        lines.append(f"  Primary flow:       {p.get('m_dot_kg_s', '?'):.0f} kg/s")
        lines.append(f"  Pump power:         {p.get('shaft_power_MW', '?'):.2f} MW")

    if "SG" in props_by_name:
        p = props_by_name["SG"]
        lines.append(f"  SG duty:            {p.get('duty_MW', '?')} MW")
        ua = p.get('UA_MW_per_K')
        if ua is not None:
            lines.append(f"  SG UA:              {ua:.2f} MW/K")
        area = p.get('area_m2')
        if area is not None:
            lines.append(f"  SG area:            {area:.0f} m²")

    if "Turbine" in props_by_name:
        p = props_by_name["Turbine"]
        lines.append(f"  Turbine gross:      {p.get('gross_power_MWe', '?'):.1f} MWe")
        lines.append(f"  Net power:          {p.get('net_power_MWe', '?'):.1f} MWe")
        eff = p.get('cycle_efficiency')
        if eff is not None:
            lines.append(f"  Cycle efficiency:   {eff*100:.1f} %")

    errs  = [i for i in result.validation_issues if i.level == "error"]
    warns = [i for i in result.validation_issues if i.level == "warning"]
    lines.append(f"  Validation:         {len(errs)} error(s), {len(warns)} warning(s)")
    if errs:
        for e in errs[:3]:
            lines.append(f"    ERROR: {e.message}")

    lines += [
        "",
        "Type 'done' to save this design, or refine with:",
        "  'primary pressure 16 MPa'  /  'hot leg 330°C'  /  'objective min_pump_power'",
        "  'set Turbine efficiency 0.90'  /  'set SG area 500'",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared: card selection utilities
# ---------------------------------------------------------------------------

def _select_card(spec: DesignSpec, initial_query: str, cfg: "AgentConfig") -> PatternCard:
    from .rag.store import CardStore
    from .workflow import _choose_topology_card

    store = CardStore.load_from_dir(cfg.cards_dir)
    cards = store.retrieve(initial_query, tags=[spec.system, spec.coolant], k=8)
    return _choose_topology_card(cards, spec)


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


def _all_node_names_from_card(card: PatternCard) -> list[str]:
    if not card.topology_template:
        return []
    return [
        node["name"]
        for b in card.topology_template["buildings"]
        for node in b["nodes"]
    ]


# ---------------------------------------------------------------------------
# Stateless API: history replay
# ---------------------------------------------------------------------------

def replay_history(messages: list[ChatMessage], initial_query: str) -> ChatState:
    """Reconstruct ChatState deterministically from a full message history.

    Protocol:
    - messages[0] is the user's initial query.
    - Then pairs of (agent question, user answer) follow.
    - Phase transitions follow the same logic as advance_conversation.
    """
    from .config import AgentConfig
    from .spec_parser import parse_design_spec

    cfg = AgentConfig()
    spec = parse_design_spec(initial_query)
    state = ChatState(phase="spec_gaps", spec=spec)

    agent_msgs  = [m for m in messages if m.role == "agent"]
    user_answers = [m for m in messages if m.role == "user"][1:]  # skip initial query

    for agent_msg, user_ans in zip(agent_msgs, user_answers):
        al = user_ans.content.strip().lower()

        if state.phase == "spec_gaps":
            for field_name, q_text, _ in _SPEC_QUESTIONS:
                if field_name not in state.spec_fields_asked and q_text in agent_msg.content:
                    state.spec_fields_asked.append(field_name)
                    state.spec = _parse_answer_into_spec(state.spec, field_name, user_ans.content)
                    break

            if _next_question(state.spec, state.spec_fields_asked) is None:
                state.phase = "param_review"

        elif state.phase == "param_review":
            if al in _AFFIRMATIVE:
                # Advance to component_review; select card
                try:
                    card = _select_card(state.spec, initial_query, cfg)
                    state.card_id = card.id
                except Exception:
                    pass
                state.phase = "component_review"
            else:
                state.spec = _parse_param_overrides(user_ans.content, state.spec)

        elif state.phase == "component_review":
            if al in _AFFIRMATIVE:
                state.phase = "design_review"
            else:
                if state.card_id:
                    card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
                    if card:
                        node_names = _all_node_names_from_card(card)
                        overrides = _parse_property_override(user_ans.content, node_names)
                        if overrides:
                            for n, props in overrides.items():
                                state.node_overrides.setdefault(n, {}).update(props)
                        else:
                            removed = _parse_removal_request(user_ans.content, card)
                            for r in removed:
                                if r not in state.removed_nodes:
                                    state.removed_nodes.append(r)

        elif state.phase == "design_review":
            if al in {"done", ""}:
                state.phase = "done"
            else:
                state.spec = _parse_param_overrides(user_ans.content, state.spec)
                if state.card_id:
                    card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
                    if card:
                        node_names = _all_node_names_from_card(card)
                        overrides = _parse_property_override(user_ans.content, node_names)
                        for n, props in overrides.items():
                            state.node_overrides.setdefault(n, {}).update(props)
                        removed = _parse_removal_request(user_ans.content, card)
                        for r in removed:
                            if r not in state.removed_nodes:
                                state.removed_nodes.append(r)

    return state


# ---------------------------------------------------------------------------
# Conversation driver
# ---------------------------------------------------------------------------

def start_conversation(
    initial_query: str,
    cfg: "AgentConfig | None" = None,
) -> TurnResult:
    """Create initial ChatState and return the first agent message.
    If all required spec fields are already specified, skips straight to param_review."""
    from .config import AgentConfig
    from .spec_parser import parse_design_spec

    cfg = cfg or AgentConfig()
    spec = parse_design_spec(initial_query)
    state = ChatState(phase="spec_gaps", spec=spec)

    next_q = _next_question(spec, [])
    if next_q is None:
        return _transition_to_param_review(state, cfg)

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
        if state.spec_fields_asked:
            last_field = state.spec_fields_asked[-1]
            state.spec = _parse_answer_into_spec(state.spec, last_field, user_message)

        next_q = _next_question(state.spec, state.spec_fields_asked)
        if next_q:
            field_name, question = next_q
            state.spec_fields_asked.append(field_name)
            return TurnResult(agent_reply=question, state=state, is_done=False)

        return _transition_to_param_review(state, cfg)

    elif state.phase == "param_review":
        return _handle_param_review(state, user_message, initial_query, cfg)

    elif state.phase == "component_review":
        return _handle_component_review(state, user_message, initial_query, cfg)

    elif state.phase == "design_review":
        return _handle_design_review(state, user_message, initial_query, cfg)

    return TurnResult(agent_reply="Design already complete.", state=state, is_done=True)


# ---------------------------------------------------------------------------
# Phase transition helpers
# ---------------------------------------------------------------------------

def _transition_to_param_review(state: ChatState, cfg: "AgentConfig") -> TurnResult:
    """Show operating-parameter summary and ask for confirmation / overrides."""
    state.phase = "param_review"
    summary = _format_param_summary(state.spec, cfg)
    reply = f"Required spec confirmed.\n\n{summary}"
    return TurnResult(agent_reply=reply, state=state, is_done=False)


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

    node_list = _format_node_list(card, state.removed_nodes)
    reply = (
        f"Parameters saved. Matched pattern: {card.title}\n\n"
        f"Proposed components:\n{node_list}\n\n"
        "Type 'ok' to accept, or:\n"
        "  - Remove components:      'remove TAV and FWCV'\n"
        "  - Override a property:    'set Turbine efficiency 0.90'\n"
        "  - Multiple actions work:  'remove TAV, set SG area 500'"
    )
    return TurnResult(agent_reply=reply, state=state, is_done=False)


def _handle_param_review(
    state: ChatState,
    user_message: str,
    initial_query: str,
    cfg: "AgentConfig",
) -> TurnResult:
    """Process a param_review turn: parse overrides or advance to component_review."""
    al = user_message.strip().lower()

    if al in _AFFIRMATIVE:
        return _transition_to_component_review(state, initial_query, cfg)

    # Apply overrides and re-show updated summary
    state.spec = _parse_param_overrides(user_message, state.spec)
    summary = _format_param_summary(state.spec, cfg)
    reply = f"Parameters updated.\n\n{summary}"
    return TurnResult(agent_reply=reply, state=state, is_done=False)


def _handle_component_review(
    state: ChatState,
    user_message: str,
    initial_query: str,
    cfg: "AgentConfig",
) -> TurnResult:
    """Process a component_review turn: loop on removals/overrides, advance on 'ok'."""
    from .workflow import run_agent_from_spec

    card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
    if card is None:
        return TurnResult(
            agent_reply="Internal error: topology card not found.",
            state=state,
            is_done=True,
            error="Card not found",
        )

    al = user_message.strip().lower()

    if al not in _AFFIRMATIVE:
        node_names = _all_node_names_from_card(card)

        # Check for property overrides first
        overrides = _parse_property_override(user_message, node_names)
        if overrides:
            for n, props in overrides.items():
                state.node_overrides.setdefault(n, {}).update(props)
            override_summary = "; ".join(
                f"{n}: {', '.join(f'{k}={v}' for k, v in props.items())}"
                for n, props in overrides.items()
            )
            node_list = _format_node_list(card, state.removed_nodes)
            reply = (
                f"Property override stored: {override_summary}\n\n"
                f"Components:\n{node_list}\n\n"
                "Continue editing or type 'ok' to run the design."
            )
            return TurnResult(agent_reply=reply, state=state, is_done=False)

        # Check for removals
        removed = _parse_removal_request(user_message, card)
        if removed:
            for r in removed:
                if r not in state.removed_nodes:
                    state.removed_nodes.append(r)
            node_list = _format_node_list(card, state.removed_nodes)
            reply = (
                f"Marked for removal: {', '.join(removed)}.\n\n"
                f"Components:\n{node_list}\n\n"
                "Continue editing or type 'ok' to run the design."
            )
            return TurnResult(agent_reply=reply, state=state, is_done=False)

        # Unrecognised input — show current state again
        node_list = _format_node_list(card, state.removed_nodes)
        reply = (
            f"Not sure what to do with that. Current components:\n{node_list}\n\n"
            "Type 'ok' to proceed, 'remove <name>' to remove a component, "
            "or 'set <name> <property> <value>' to override a property."
        )
        return TurnResult(agent_reply=reply, state=state, is_done=False)

    # User said ok — run the pipeline → transition to design_review
    pruned_topo = _prune_topology(card, state.removed_nodes)
    try:
        result = run_agent_from_spec(
            state.spec, pruned_topo, card, cfg,
            node_overrides=state.node_overrides or None,
        )
    except Exception as e:
        log.exception("Pipeline error in interactive mode")
        return TurnResult(
            agent_reply=f"Design pipeline error: {e}",
            state=state,
            is_done=True,
            error=str(e),
        )

    state.phase = "design_review"
    summary = _format_design_summary(result)
    return TurnResult(
        agent_reply=summary,
        state=state,
        is_done=False,
        result=result,
    )


def _handle_design_review(
    state: ChatState,
    user_message: str,
    initial_query: str,
    cfg: "AgentConfig",
) -> TurnResult:
    """Process a design_review turn: 'done' finalises; anything else re-runs the pipeline."""
    from .workflow import run_agent_from_spec

    al = user_message.strip().lower()

    if al in {"done", ""}:
        # Final state — retrieve or re-run to get result
        card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
        if card is None:
            return TurnResult(
                agent_reply="Internal error: card not found.",
                state=state,
                is_done=True,
                error="Card not found",
            )
        pruned_topo = _prune_topology(card, state.removed_nodes)
        try:
            result = run_agent_from_spec(
                state.spec, pruned_topo, card, cfg,
                node_overrides=state.node_overrides or None,
            )
        except Exception as e:
            log.exception("Pipeline error finalising design")
            return TurnResult(
                agent_reply=f"Design pipeline error: {e}",
                state=state,
                is_done=True,
                error=str(e),
            )
        state.phase = "done"
        errs  = [i for i in result.validation_issues if i.level == "error"]
        warns = [i for i in result.validation_issues if i.level == "warning"]
        msg = f"Design finalised. {len(errs)} error(s), {len(warns)} warning(s)."
        return TurnResult(agent_reply=msg, state=state, is_done=True, result=result)

    # Apply any refinements
    card = _get_card_by_id(state.card_id, initial_query, state.spec, cfg)
    if card is None:
        return TurnResult(
            agent_reply="Internal error: card not found.",
            state=state,
            is_done=True,
            error="Card not found",
        )

    state.spec = _parse_param_overrides(user_message, state.spec)
    node_names = _all_node_names_from_card(card)
    overrides = _parse_property_override(user_message, node_names)
    for n, props in overrides.items():
        state.node_overrides.setdefault(n, {}).update(props)
    removed = _parse_removal_request(user_message, card)
    for r in removed:
        if r not in state.removed_nodes:
            state.removed_nodes.append(r)

    pruned_topo = _prune_topology(card, state.removed_nodes)
    try:
        result = run_agent_from_spec(
            state.spec, pruned_topo, card, cfg,
            node_overrides=state.node_overrides or None,
        )
    except Exception as e:
        log.exception("Pipeline error during design_review refinement")
        return TurnResult(
            agent_reply=f"Design pipeline error: {e}",
            state=state,
            is_done=True,
            error=str(e),
        )

    summary = _format_design_summary(result)
    return TurnResult(
        agent_reply=f"Design updated.\n\n{summary}",
        state=state,
        is_done=False,
        result=result,
    )
