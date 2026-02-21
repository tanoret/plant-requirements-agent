"""
Interactive conversation engine for component requirements collection.

Four-phase dialogue:
  1. component_selection  – detect or ask for the component type
  2. profile_required     – ask each required profile field one at a time
  3. profile_optional_review – show key optional params, allow overrides or accept
  4. done                 – run filtering, return requirements instance JSON

Works in both stateful (CLI) and stateless (API) modes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .loader import resolve_component, load_baseline, COMPONENT_KEYS
from .filter import filter_requirements

ReqPhase = Literal[
    "component_selection",
    "profile_required",
    "profile_optional_review",
    "done",
]

_AFFIRMATIVE = {"ok", "yes", "proceed", "continue", "go", "good", "done", ""}


@dataclass
class ReqChatMessage:
    role: Literal["user", "agent"]
    content: str


@dataclass
class ReqChatState:
    phase: ReqPhase = "component_selection"
    component_key: str | None = None
    profile: dict = field(default_factory=dict)
    fields_asked: list[str] = field(default_factory=list)
    # Numeric values pre-filled from a loop-design result.
    # Keys are optional-field names (e.g. "design_flowrate", "thermal_duty_rated").
    # Merged into profile when the optional-review phase starts; shown with
    # a "(from loop design)" annotation so the user knows the source.
    prefilled_numeric: dict = field(default_factory=dict)


@dataclass
class ReqTurnResult:
    agent_reply: str
    state: ReqChatState
    is_done: bool
    result_json: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Required-field question catalogues  (field, question_text, allowed_values | None)
# ---------------------------------------------------------------------------

_TAG_HINT = "(used as an identifier label, e.g. RCS-PMP-001)"
_CC_OPTS = ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3", "NonCode"]
_SC_OPTS = ["Seismic_Category_I", "Seismic_Category_II", "NonSeismic"]

_REQUIRED_QUESTIONS: dict[str, list[tuple[str, str, list[str] | None]]] = {
    "pump": [
        ("pump_tag",             f"Pump tag / ID?  {_TAG_HINT}", None),
        ("pump_type",            "Pump type?\n  Options: centrifugal, vertical_turbine, positive_displacement, canned_motor, submersible",
         ["centrifugal", "vertical_turbine", "positive_displacement", "canned_motor", "submersible"]),
        ("function",             "Pump function?\n  Options: reactor_coolant, safety_injection, residual_heat_removal, feedwater, service_water, chemical_volume_control",
         ["reactor_coolant", "safety_injection", "residual_heat_removal", "feedwater", "service_water", "chemical_volume_control"]),
        ("driver_type",          "Driver type?\n  Options: electric_motor, steam_turbine, diesel, hydraulic",
         ["electric_motor", "steam_turbine", "diesel", "hydraulic"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_1, ASME_III_Class_2, ASME_III_Class_3, NonCode",
         _CC_OPTS),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety, risk_informed",
         ["safety_related", "non_safety", "risk_informed"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, Seismic_Category_II, NonSeismic",
         _SC_OPTS),
        ("environment_profile",  "Environment profile?\n  Options: mild, harsh, DBA_profile_defined",
         ["mild", "harsh", "DBA_profile_defined"]),
    ],
    "valve": [
        ("valve_tag",            f"Valve tag / ID?  {_TAG_HINT}", None),
        ("valve_type",           "Valve type?\n  Options: gate, globe, check, ball, butterfly, relief, other",
         ["gate", "globe", "check", "ball", "butterfly", "relief", "other"]),
        ("function",             "Valve function?\n  Options: isolation, flow_control, non_return, overpressure_protection",
         ["isolation", "flow_control", "non_return", "overpressure_protection"]),
        ("actuation_type",       "Actuation type?\n  Options: manual, MOV, AOV, SOV, HOV",
         ["manual", "MOV", "AOV", "SOV", "HOV"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_1, ASME_III_Class_2, ASME_III_Class_3, NonCode",
         _CC_OPTS),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety, risk_informed",
         ["safety_related", "non_safety", "risk_informed"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, Seismic_Category_II, NonSeismic",
         _SC_OPTS),
        ("environment_profile",  "Environment profile?\n  Options: mild, harsh, DBA_profile_defined",
         ["mild", "harsh", "DBA_profile_defined"]),
    ],
    "condenser": [
        ("condenser_tag",        f"Condenser tag / ID?  {_TAG_HINT}", None),
        ("condenser_type",       "Condenser type?\n  Options: surface, air_cooled, jet",
         ["surface", "air_cooled", "jet"]),
        ("service",              "Service?\n  Options: main_turbine_condenser, auxiliary_condenser, shutdown_condenser",
         ["main_turbine_condenser", "auxiliary_condenser", "shutdown_condenser"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_3, B31_1, VIII, NonCode",
         ["ASME_III_Class_3", "B31_1", "VIII", "NonCode", "non_code"]),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety, important_to_safety, risk_informed",
         ["safety_related", "non_safety", "important_to_safety", "nonsafety", "risk_informed"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, NonSeismic",
         ["Seismic_Category_I", "NonSeismic", "non_seismic"]),
        ("environment_profile",  "Environment profile?\n  Options: mild, harsh, outdoor, marine, radiological",
         ["mild", "harsh", "outdoor", "marine", "radiological"]),
    ],
    "steam_generator": [
        ("sg_tag",               f"Steam generator tag / ID?  {_TAG_HINT}", None),
        ("sg_type",              "SG type?\n  Options: u_tube_recirc, once_through, helical_coil",
         ["u_tube_recirc", "once_through", "helical_coil"]),
        ("reactor_type",         "Reactor type?\n  Options: PWR, iPWR, SMR, test_reactor",
         ["PWR", "iPWR", "SMR", "test_reactor"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_1, ASME_III_Class_2, ASME_III_Class_3, NonCode",
         _CC_OPTS),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety",
         ["safety_related", "non_safety", "nonsafety"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, Seismic_Category_II, NonSeismic",
         _SC_OPTS),
        ("eq_environment_profile","EQ environment profile?\n  Options: harsh, mild",
         ["harsh", "mild"]),
    ],
    "pressurizer": [
        ("pressurizer_tag",      f"Pressurizer tag / ID?  {_TAG_HINT}", None),
        ("pressurizer_design",   "Pressurizer design?\n  Options: separate_vessel, integral",
         ["separate_vessel", "integral"]),
        ("service",              "Service?\n  Options: rcs_pressure_control, integrated_pressure_control",
         ["rcs_pressure_control", "integrated_pressure_control"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_1, ASME_III_Class_2, ASME_III_Class_3, NonCode",
         _CC_OPTS),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety, risk_informed",
         ["safety_related", "non_safety", "nonsafety", "risk_informed"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, Seismic_Category_II, NonSeismic",
         _SC_OPTS),
        ("harsh_environment",    "Harsh radiation environment?  yes / no",
         None),  # boolean
    ],
    "turbine": [
        ("turbine_tag",          f"Turbine tag / ID?  {_TAG_HINT}", None),
        ("turbine_type",         "Turbine type?\n  Options: steam_turbine, gas_turbine, hydraulic_turbine",
         ["steam_turbine", "gas_turbine", "hydraulic_turbine"]),
        ("turbine_application",  "Application?\n  Options: main_generator, mechanical_drive, black_start, auxiliary",
         ["main_generator", "mechanical_drive", "black_start", "auxiliary"]),
        ("code_class",           "ASME code class?\n  Options: ASME_III_Class_1, ASME_III_Class_2, ASME_III_Class_3, B31_1, NonCode",
         ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3", "B31_1", "NonCode", "non_code"]),
        ("safety_classification","Safety classification?\n  Options: safety_related, non_safety, important_to_safety",
         ["safety_related", "non_safety", "nonsafety", "important_to_safety"]),
        ("seismic_category",     "Seismic category?\n  Options: Seismic_Category_I, NonSeismic",
         ["Seismic_Category_I", "NonSeismic", "non_seismic"]),
        ("environment_profile",  "Environment profile?\n  Options: mild, harsh, DBA_profile_defined",
         ["mild", "harsh", "DBA_profile_defined"]),
    ],
}

# Optional fields shown in profile_optional_review, with units for display
_OPTIONAL_FIELDS: dict[str, list[tuple[str, str, str]]] = {
    "pump": [
        ("design_pressure",    "Design pressure",    "MPa"),
        ("design_temperature", "Design temperature", "°C"),
        ("design_flowrate",    "Design flowrate",    "kg/s"),
        ("design_head",        "Design head",        "m"),
        ("rated_power",        "Rated power",        "kW"),
        ("design_cycles",      "Design cycles",      "cycles"),
        ("service_life_years", "Service life",       "years"),
    ],
    "valve": [
        ("design_pressure",    "Design pressure",    "MPa"),
        ("design_temperature", "Design temperature", "°C"),
        ("dp_max",             "Max differential pressure", "MPa"),
        ("flowrate_max",       "Max flowrate",       "kg/s"),
        ("service_life_years", "Service life",       "years"),
    ],
    "condenser": [
        ("thermal_duty_rated", "Rated thermal duty", "MW"),
        ("cw_flowrate_design", "Cooling water flowrate", "kg/s"),
        ("design_pressure",    "Design pressure",    "MPa"),
        ("service_life_years", "Service life",       "years"),
    ],
    "steam_generator": [
        ("thermal_duty_rated",       "Rated thermal duty",       "MW"),
        ("design_pressure_primary",  "Primary design pressure",  "MPa"),
        ("design_pressure_secondary","Secondary design pressure", "MPa"),
        ("service_life_years",       "Service life",             "years"),
    ],
    "pressurizer": [
        ("total_volume_m3",    "Total volume",       "m³"),
        ("heater_power_total", "Total heater power", "kW"),
        ("safety_valve_count", "Safety valve count", "—"),
        ("service_life_years", "Service life",       "years"),
    ],
    "turbine": [
        ("rated_power_mw",     "Rated power",        "MW"),
        ("design_life_years",  "Design life",        "years"),
        ("start_stop_cycles",  "Start/stop cycles",  "cycles"),
        ("rated_speed_rpm",    "Rated speed",        "rpm"),
    ],
}

# Keyword → field_name mappings for optional override parsing
_OPT_KEYWORDS: dict[str, dict[str, str]] = {
    "pump": {
        "design pressure": "design_pressure",
        "pressure": "design_pressure",
        "temperature": "design_temperature",
        "temp": "design_temperature",
        "flowrate": "design_flowrate",
        "flow rate": "design_flowrate",
        "flow": "design_flowrate",
        "head": "design_head",
        "rated power": "rated_power",
        "power": "rated_power",
        "cycles": "design_cycles",
        "design cycles": "design_cycles",
        "service life": "service_life_years",
        "life": "service_life_years",
    },
    "valve": {
        "pressure": "design_pressure",
        "temperature": "design_temperature",
        "dp": "dp_max",
        "differential pressure": "dp_max",
        "flowrate": "flowrate_max",
        "flow": "flowrate_max",
        "service life": "service_life_years",
        "life": "service_life_years",
    },
    "condenser": {
        "thermal duty": "thermal_duty_rated",
        "duty": "thermal_duty_rated",
        "cooling water": "cw_flowrate_design",
        "cw flow": "cw_flowrate_design",
        "pressure": "design_pressure",
        "service life": "service_life_years",
        "life": "service_life_years",
    },
    "steam_generator": {
        "thermal duty": "thermal_duty_rated",
        "duty": "thermal_duty_rated",
        "primary pressure": "design_pressure_primary",
        "secondary pressure": "design_pressure_secondary",
        "service life": "service_life_years",
        "life": "service_life_years",
    },
    "pressurizer": {
        "volume": "total_volume_m3",
        "heater power": "heater_power_total",
        "safety valve": "safety_valve_count",
        "service life": "service_life_years",
        "life": "service_life_years",
    },
    "turbine": {
        "rated power": "rated_power_mw",
        "power": "rated_power_mw",
        "design life": "design_life_years",
        "life": "design_life_years",
        "cycles": "start_stop_cycles",
        "speed": "rated_speed_rpm",
        "rpm": "rated_speed_rpm",
    },
}


# ---------------------------------------------------------------------------
# Answer parsers
# ---------------------------------------------------------------------------

def _parse_required_field(
    field_name: str,
    answer: str,
    allowed: list[str] | None,
) -> tuple[bool, object]:
    """Parse user answer for a required field. Returns (success, value)."""
    ans = answer.strip()
    if not ans:
        return False, None

    # Boolean field (pressurizer harsh_environment)
    if allowed is None and field_name == "harsh_environment":
        al = ans.lower()
        if al in ("yes", "true", "harsh", "y", "1"):
            return True, True
        if al in ("no", "false", "mild", "n", "0"):
            return True, False
        return False, None

    # Free-text tag fields
    if allowed is None:
        return True, ans

    # Enum fields — case-insensitive partial / normalised match
    al = ans.lower().replace(" ", "_").replace("-", "_")
    # Try exact match first
    if ans in allowed:
        return True, ans
    # Case-insensitive full match
    for v in allowed:
        if v.lower() == al:
            return True, v
    # Normalised partial aliases
    _NORM: dict[str, str] = {
        "class_1": "ASME_III_Class_1", "class1": "ASME_III_Class_1",
        "asme_1": "ASME_III_Class_1", "1": "ASME_III_Class_1",
        "class_2": "ASME_III_Class_2", "class2": "ASME_III_Class_2",
        "asme_2": "ASME_III_Class_2", "2": "ASME_III_Class_2",
        "class_3": "ASME_III_Class_3", "class3": "ASME_III_Class_3",
        "asme_3": "ASME_III_Class_3", "3": "ASME_III_Class_3",
        "noncode": "NonCode", "non_code": "NonCode",
        "seismic_i": "Seismic_Category_I", "cat_i": "Seismic_Category_I",
        "seismic_ii": "Seismic_Category_II", "cat_ii": "Seismic_Category_II",
        "nonseismic": "NonSeismic", "non_seismic": "NonSeismic",
        "safety_related": "safety_related", "sr": "safety_related",
        "non_safety": "non_safety", "nonsafety": "non_safety",
        "risk_informed": "risk_informed", "ri": "risk_informed",
        "important_to_safety": "important_to_safety", "its": "important_to_safety",
        "mild": "mild", "harsh": "harsh",
        "dba": "DBA_profile_defined",
        "pwr": "PWR", "swr": "SMR",
        "u_tube": "u_tube_recirc", "once_through": "once_through",
        "helical": "helical_coil",
        "centrifugal": "centrifugal",
        "electric": "electric_motor", "motor": "electric_motor",
        "steam_turbine_driver": "steam_turbine",
        "manual": "manual",
        "gate": "gate", "globe": "globe", "check": "check",
        "ball": "ball", "butterfly": "butterfly", "relief": "relief",
        "isolation": "isolation", "flow_control": "flow_control",
        "non_return": "non_return", "overpressure": "overpressure_protection",
        "surface": "surface", "air_cooled": "air_cooled", "jet": "jet",
        "main_turbine": "main_turbine_condenser",
        "separate": "separate_vessel", "integral": "integral",
        "rcs": "rcs_pressure_control",
        "main_generator": "main_generator", "mechanical_drive": "mechanical_drive",
        "black_start": "black_start",
    }
    if al in _NORM:
        candidate = _NORM[al]
        if candidate in allowed:
            return True, candidate
    # Substring match (last resort)
    for v in allowed:
        if al in v.lower() or v.lower() in al:
            return True, v
    return False, None


def _parse_optional_overrides(answer: str, component_key: str) -> dict:
    """Parse free-form text for optional numeric field overrides.

    Returns {field_name: float_value} for any matches found.
    """
    overrides: dict = {}
    al = answer.strip().lower()
    keywords = _OPT_KEYWORDS.get(component_key, {})
    # Sort by length descending to match longer phrases first
    for kw in sorted(keywords, key=len, reverse=True):
        if kw in al:
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", answer)
            if nums:
                overrides[keywords[kw]] = float(nums[-1])
    return overrides


# ---------------------------------------------------------------------------
# Summary formatters
# ---------------------------------------------------------------------------

def _format_optional_summary(
    component_key: str,
    profile: dict,
    prefilled_keys: set[str] | None = None,
) -> str:
    opt_fields = _OPTIONAL_FIELDS.get(component_key, [])
    lines = [f"Optional parameters for {component_key.replace('_', ' ').upper()}:"]
    for field_name, label, units in opt_fields:
        val = profile.get(field_name)
        if val is not None:
            source = " (from loop design)" if prefilled_keys and field_name in prefilled_keys else ""
            tag = f"{val} {units}{source}"
        else:
            tag = "(not set)"
        lines.append(f"  {label:<30} {tag}")
    lines += [
        "",
        "Type 'ok' to proceed, or override any value, e.g.:",
        "  'design pressure 15.5'  /  'service life 40'  /  'cycles 1000'",
    ]
    return "\n".join(lines)


def _format_requirements_summary(result_json: dict, component_key: str) -> str:
    n_applicable = len(result_json["applicable_requirements"])
    n_non = len(result_json["non_applicable_requirements"])
    n_total = n_applicable + n_non
    val = result_json["validation"]
    tbd = sorted({
        p
        for r in result_json["applicable_requirements"]
        for p in r.get("tbd_parameters", [])
    })
    tag_key = f"{component_key}_tag"
    profile = result_json.get(f"{component_key}_profile", {})
    tag = profile.get(tag_key, "")

    lines = [
        f"Requirements instance generated for {component_key.upper()}"
        + (f" [{tag}]" if tag else "") + ":",
        f"  Applicable:      {n_applicable} / {n_total}",
        f"  Non-applicable:  {n_non}",
        f"  Validation:      {val['error_count']} error(s), {val['warning_count']} warning(s)",
    ]
    if tbd:
        lines.append(f"  TBD parameters:  {', '.join(tbd)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Next required field helper
# ---------------------------------------------------------------------------

def _next_required_field(
    component_key: str,
    profile: dict,
    fields_asked: list[str],
) -> tuple[str, str, list[str] | None] | None:
    """Return (field_name, question, allowed) for next unfilled required field, or None."""
    for field_name, question, allowed in _REQUIRED_QUESTIONS[component_key]:
        if field_name in fields_asked:
            continue
        if profile.get(field_name) is not None:
            continue
        return field_name, question, allowed
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_req_conversation(initial_query: str) -> ReqTurnResult:
    """Start a requirements conversation from an initial query."""
    state = ReqChatState()

    component_key = resolve_component(initial_query)
    if component_key:
        state.component_key = component_key
        state.profile = {}
        return _transition_to_profile_required(state)

    reply = (
        "Which component do you need requirements for?\n"
        f"  Options: {', '.join(COMPONENT_KEYS)}"
    )
    return ReqTurnResult(agent_reply=reply, state=state, is_done=False)


def advance_req_conversation(
    state: ReqChatState,
    user_message: str,
    initial_query: str,
) -> ReqTurnResult:
    """Process one user message and return the next agent reply (or final result)."""
    if state.phase == "component_selection":
        return _handle_component_selection(state, user_message)

    if state.phase == "profile_required":
        return _handle_profile_required(state, user_message)

    if state.phase == "profile_optional_review":
        return _handle_profile_optional_review(state, user_message)

    return ReqTurnResult(
        agent_reply="Requirements already generated.",
        state=state,
        is_done=True,
    )


def _handle_component_selection(state: ReqChatState, user_message: str) -> ReqTurnResult:
    key = resolve_component(user_message)
    if key is None:
        # Try bare exact match
        msg_lower = user_message.strip().lower()
        if msg_lower in COMPONENT_KEYS:
            key = msg_lower
    if key is None:
        reply = (
            f"I didn't recognise that component. Please choose one of:\n"
            f"  {', '.join(COMPONENT_KEYS)}"
        )
        return ReqTurnResult(agent_reply=reply, state=state, is_done=False)

    state.component_key = key
    state.profile = {}
    return _transition_to_profile_required(state)


def _transition_to_profile_required(state: ReqChatState) -> ReqTurnResult:
    state.phase = "profile_required"
    nxt = _next_required_field(state.component_key, state.profile, state.fields_asked)
    if nxt is None:
        return _transition_to_optional_review(state)
    field_name, question, _ = nxt
    state.fields_asked.append(field_name)
    return ReqTurnResult(
        agent_reply=f"Component: {state.component_key.replace('_', ' ').upper()}\n\n{question}",
        state=state,
        is_done=False,
    )


def _handle_profile_required(state: ReqChatState, user_message: str) -> ReqTurnResult:
    # Apply answer to last asked field
    if state.fields_asked:
        last_field = state.fields_asked[-1]
        questions = {f: (q, a) for f, q, a in _REQUIRED_QUESTIONS[state.component_key]}
        _, allowed = questions[last_field]
        ok, value = _parse_required_field(last_field, user_message, allowed)
        if ok:
            state.profile[last_field] = value
        else:
            # Re-ask
            question, _ = questions[last_field]
            return ReqTurnResult(
                agent_reply=f"Didn't recognise that answer. {question}",
                state=state,
                is_done=False,
            )

    nxt = _next_required_field(state.component_key, state.profile, state.fields_asked)
    if nxt is None:
        return _transition_to_optional_review(state)

    field_name, question, _ = nxt
    state.fields_asked.append(field_name)
    return ReqTurnResult(agent_reply=question, state=state, is_done=False)


def _transition_to_optional_review(state: ReqChatState) -> ReqTurnResult:
    state.phase = "profile_optional_review"
    # Merge design-sourced numerics into profile (do not overwrite user answers)
    for k, v in state.prefilled_numeric.items():
        state.profile.setdefault(k, v)
    prefilled_keys = set(state.prefilled_numeric)
    summary = _format_optional_summary(state.component_key, state.profile, prefilled_keys)
    intro = (
        "Required profile complete. Optional numeric parameters are shown below. "
        "Values marked '(from loop design)' were extracted from the sizing results — "
        "review and adjust as needed, then type 'ok' to generate requirements.\n\n"
        if prefilled_keys else
        "Required profile complete. Providing optional numeric parameters enables more precise "
        "requirement filtering (e.g. design cycle requirements only apply when design_cycles > 0).\n\n"
    )
    return ReqTurnResult(agent_reply=intro + summary, state=state, is_done=False)


def _handle_profile_optional_review(
    state: ReqChatState,
    user_message: str,
) -> ReqTurnResult:
    al = user_message.strip().lower()

    if al in _AFFIRMATIVE:
        return _run_filter(state)

    overrides = _parse_optional_overrides(user_message, state.component_key)
    if overrides:
        state.profile.update(overrides)
        prefilled_keys = set(state.prefilled_numeric)
        summary = _format_optional_summary(state.component_key, state.profile, prefilled_keys)
        return ReqTurnResult(
            agent_reply=f"Parameters updated.\n\n{summary}",
            state=state,
            is_done=False,
        )

    # Unrecognised input — re-show
    prefilled_keys = set(state.prefilled_numeric)
    summary = _format_optional_summary(state.component_key, state.profile, prefilled_keys)
    return ReqTurnResult(
        agent_reply=f"Not sure what to change. Current optional parameters:\n\n{summary}",
        state=state,
        is_done=False,
    )


def _run_filter(state: ReqChatState) -> ReqTurnResult:
    try:
        baseline = load_baseline(state.component_key)
        result_json = filter_requirements(baseline, state.profile, state.component_key)
    except Exception as e:
        return ReqTurnResult(
            agent_reply=f"Error generating requirements: {e}",
            state=state,
            is_done=True,
            error=str(e),
        )

    state.phase = "done"
    summary = _format_requirements_summary(result_json, state.component_key)
    return ReqTurnResult(
        agent_reply=summary,
        state=state,
        is_done=True,
        result_json=result_json,
    )


# ---------------------------------------------------------------------------
# Stateless API: history replay
# ---------------------------------------------------------------------------

def replay_req_history(
    messages: list[ReqChatMessage],
    initial_query: str,
) -> ReqChatState:
    """Reconstruct ReqChatState deterministically from message history."""
    state = ReqChatState()

    component_key = resolve_component(initial_query)
    if component_key:
        state.component_key = component_key
        state.phase = "profile_required"

    agent_msgs = [m for m in messages if m.role == "agent"]
    user_answers = [m for m in messages if m.role == "user"][1:]  # skip initial query

    for agent_msg, user_ans in zip(agent_msgs, user_answers):
        al = user_ans.content.strip().lower()

        if state.phase == "component_selection":
            key = resolve_component(user_ans.content)
            if key is None and al in COMPONENT_KEYS:
                key = al
            if key:
                state.component_key = key
                state.phase = "profile_required"

        elif state.phase == "profile_required":
            if state.fields_asked:
                last = state.fields_asked[-1]
                q_map = {f: a for f, _, a in _REQUIRED_QUESTIONS.get(state.component_key, [])}
                allowed = q_map.get(last)
                ok, val = _parse_required_field(last, user_ans.content, allowed)
                if ok:
                    state.profile[last] = val

            # Check what question the agent just asked to find which field comes next
            for field_name, question, _ in _REQUIRED_QUESTIONS.get(state.component_key, []):
                if field_name not in state.fields_asked and question in agent_msg.content:
                    state.fields_asked.append(field_name)
                    break

            if _next_required_field(state.component_key, state.profile, state.fields_asked) is None:
                state.phase = "profile_optional_review"

        elif state.phase == "profile_optional_review":
            if al in _AFFIRMATIVE:
                state.phase = "done"
            else:
                overrides = _parse_optional_overrides(user_ans.content, state.component_key)
                state.profile.update(overrides)

    return state


def replay_req_history_from_design(
    messages: list[ReqChatMessage],
    component_key: str,
    prefilled_numeric: dict,
) -> ReqChatState:
    """Reconstruct ReqChatState for a design-linked conversation.

    Like ``replay_req_history`` but the component is already known and
    numeric optional fields have been pre-filled from the loop design.
    Used by the stateless ``/requirements-from-design`` API endpoint.
    """
    state = ReqChatState(
        component_key=component_key,
        phase="profile_required",
        prefilled_numeric=prefilled_numeric,
    )

    agent_msgs  = [m for m in messages if m.role == "agent"]
    user_answers = [m for m in messages if m.role == "user"]

    for agent_msg, user_ans in zip(agent_msgs, user_answers):
        al = user_ans.content.strip().lower()

        if state.phase == "profile_required":
            if state.fields_asked:
                last = state.fields_asked[-1]
                q_map = {f: a for f, _, a in _REQUIRED_QUESTIONS.get(state.component_key, [])}
                allowed = q_map.get(last)
                ok, val = _parse_required_field(last, user_ans.content, allowed)
                if ok:
                    state.profile[last] = val

            for field_name, question, _ in _REQUIRED_QUESTIONS.get(state.component_key, []):
                if field_name not in state.fields_asked and question in agent_msg.content:
                    state.fields_asked.append(field_name)
                    break

            if _next_required_field(state.component_key, state.profile, state.fields_asked) is None:
                # Merge prefilled values when entering optional review
                for k, v in state.prefilled_numeric.items():
                    state.profile.setdefault(k, v)
                state.phase = "profile_optional_review"

        elif state.phase == "profile_optional_review":
            if al in _AFFIRMATIVE:
                state.phase = "done"
            else:
                overrides = _parse_optional_overrides(user_ans.content, state.component_key)
                state.profile.update(overrides)

    return state


# ---------------------------------------------------------------------------
# Design-linked public API
# ---------------------------------------------------------------------------

def start_req_conversation_from_design(
    node_name: str,
    node_props: dict,
    all_node_props: dict[str, dict] | None = None,
) -> ReqTurnResult:
    """Start a requirements conversation seeded with parameters from a loop design.

    The component type is resolved from the node name (e.g. "Primary Sink" →
    pump, "SG" → steam_generator).  Numeric optional fields (flow rate, head,
    power, duty, pressures) are pre-filled from the sizing results so the user
    only needs to supply classification fields (code class, safety category,
    seismic category, environment profile, tag, and type).

    Parameters
    ----------
    node_name : str
        Alchemy graph node name, e.g. "Primary Sink", "SG", "Turbine".
    node_props : dict
        Sized node properties (``node.properties`` from AgentResult).
    all_node_props : dict[str, dict] | None
        Full {name: props} map for all nodes in the design; enables
        cross-node lookups (e.g. hot-leg temperature from Primary Source).

    Returns
    -------
    ReqTurnResult
        First agent message — always the first required classification question.
    """
    from .bridge import extract_design_numerics

    component_key, numerics = extract_design_numerics(node_name, node_props, all_node_props)
    if component_key is None:
        return ReqTurnResult(
            agent_reply=(
                f"Node '{node_name}' does not have a requirements baseline. "
                f"Supported nodes: {', '.join(sorted({'Primary Sink', 'SG', 'FWP', 'Turbine'}))}."
            ),
            state=ReqChatState(),
            is_done=True,
            error=f"No requirements mapping for node '{node_name}'.",
        )

    state = ReqChatState(
        component_key=component_key,
        prefilled_numeric=numerics,
    )
    intro = (
        f"Starting requirements for {node_name} ({component_key.replace('_', ' ').upper()}).\n"
        f"Design parameters have been extracted from the loop sizing results.\n"
        f"I only need to ask a few classification questions.\n"
    )
    turn = _transition_to_profile_required(state)
    turn.agent_reply = intro + "\n" + turn.agent_reply
    return turn


def advance_req_conversation_from_design(
    state: ReqChatState,
    user_message: str,
) -> ReqTurnResult:
    """Advance a design-linked requirements conversation by one turn.

    Identical to ``advance_req_conversation`` — the pre-filled state is
    already embedded in ``state.prefilled_numeric``; no extra arguments needed.
    """
    return advance_req_conversation(state, user_message, initial_query="")
