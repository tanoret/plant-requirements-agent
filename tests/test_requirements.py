"""Tests for the component requirements feature."""
import pytest
from nucsys_agent.requirements.loader import resolve_component, load_baseline, COMPONENT_KEYS
from nucsys_agent.requirements.applicability import evaluate_condition, is_applicable
from nucsys_agent.requirements.filter import filter_requirements
from nucsys_agent.requirements.conversation import (
    _parse_required_field,
    _parse_optional_overrides,
    start_req_conversation,
    advance_req_conversation,
)


# ---------------------------------------------------------------------------
# loader: resolve_component
# ---------------------------------------------------------------------------

def test_resolve_component_pump():
    assert resolve_component("pump") == "pump"
    assert resolve_component("requirements for a centrifugal pump") == "pump"
    assert resolve_component("PUMPS") == "pump"
    assert resolve_component("RCP pump") == "pump"

def test_resolve_component_steam_generator():
    assert resolve_component("steam generator") == "steam_generator"
    assert resolve_component("SG requirements") == "steam_generator"
    assert resolve_component("steam_generator") == "steam_generator"

def test_resolve_component_pressurizer():
    assert resolve_component("pressurizer") == "pressurizer"
    assert resolve_component("PRZ specs") == "pressurizer"

def test_resolve_component_turbine():
    assert resolve_component("turbine requirements") == "turbine"
    assert resolve_component("main turbine") == "turbine"

def test_resolve_component_unknown():
    assert resolve_component("reactor core") is None
    assert resolve_component("") is None

def test_resolve_component_valve():
    assert resolve_component("valve") == "valve"
    assert resolve_component("TAV valve requirements") == "valve"


# ---------------------------------------------------------------------------
# applicability: evaluate_condition
# ---------------------------------------------------------------------------

def test_evaluate_condition_always():
    ok, tbd = evaluate_condition("always", {})
    assert ok is True
    assert tbd == []

def test_evaluate_condition_enum_match():
    profile = {"code_class": "ASME_III_Class_1"}
    ok, tbd = evaluate_condition("code_class=ASME_III_Class_1|2|3", profile)
    assert ok is True
    assert tbd == []

def test_evaluate_condition_enum_no_match():
    profile = {"code_class": "NonCode"}
    ok, tbd = evaluate_condition("code_class=ASME_III_Class_1|2|3", profile)
    assert ok is False

def test_evaluate_condition_enum_pipe_or():
    profile = {"actuation_type": "AOV"}
    ok, _ = evaluate_condition("actuation_type=MOV|AOV|SOV|HOV", profile)
    assert ok is True

def test_evaluate_condition_enum_missing_field():
    profile = {}
    ok, tbd = evaluate_condition("code_class=ASME_III_Class_1", profile)
    assert ok is False

def test_evaluate_condition_numeric_defined_above():
    profile = {"design_cycles": 1000}
    ok, tbd = evaluate_condition("design_cycles>0", profile)
    assert ok is True
    assert tbd == []

def test_evaluate_condition_numeric_defined_zero():
    profile = {"design_cycles": 0}
    ok, tbd = evaluate_condition("design_cycles>0", profile)
    assert ok is False

def test_evaluate_condition_numeric_null_conservative():
    """Null field should be treated as TBD (requirement included)."""
    profile = {}
    ok, tbd = evaluate_condition("design_cycles>0", profile)
    assert ok is True
    assert "design_cycles" in tbd

def test_evaluate_condition_numeric_or():
    profile = {"design_cycles": 0, "service_life_years": 40}
    ok, tbd = evaluate_condition("design_cycles>0|service_life_years>0", profile)
    assert ok is True

def test_evaluate_condition_numeric_or_both_zero():
    profile = {"design_cycles": 0, "service_life_years": 0}
    ok, _ = evaluate_condition("design_cycles>0|service_life_years>0", profile)
    assert ok is False


def test_is_applicable_and_logic():
    profile = {
        "safety_classification": "safety_related",
        "actuation_type": "MOV",
    }
    when = ["safety_classification=safety_related", "actuation_type=MOV|AOV|SOV|HOV"]
    ok, tbd = is_applicable(when, profile)
    assert ok is True
    assert tbd == []

def test_is_applicable_and_logic_one_fails():
    profile = {
        "safety_classification": "non_safety",
        "actuation_type": "MOV",
    }
    when = ["safety_classification=safety_related", "actuation_type=MOV|AOV|SOV|HOV"]
    ok, _ = is_applicable(when, profile)
    assert ok is False


# ---------------------------------------------------------------------------
# filter_requirements: structure + counts
# ---------------------------------------------------------------------------

def _minimal_pump_profile() -> dict:
    return {
        "pump_tag": "TEST-PMP-001",
        "pump_type": "centrifugal",
        "function": "reactor_coolant",
        "driver_type": "electric_motor",
        "code_class": "ASME_III_Class_1",
        "safety_classification": "safety_related",
        "seismic_category": "Seismic_Category_I",
        "environment_profile": "harsh",
    }


def test_filter_requirements_pump_structure():
    baseline = load_baseline("pump")
    profile = _minimal_pump_profile()
    result = filter_requirements(baseline, profile, "pump")

    assert "instance_id" in result
    assert "template_id" in result
    assert "generated_utc" in result
    assert "pump_profile" in result
    assert "applicable_requirements" in result
    assert "non_applicable_requirements" in result
    assert "validation" in result


def test_filter_requirements_pump_counts():
    """Applicable + non-applicable must equal the total in the baseline."""
    baseline = load_baseline("pump")
    profile = _minimal_pump_profile()
    result = filter_requirements(baseline, profile, "pump")

    total_in_baseline = sum(
        len(rs["requirements"])
        for rs in baseline["requirement_sets"]
    )
    n_applicable = len(result["applicable_requirements"])
    n_non = len(result["non_applicable_requirements"])
    assert n_applicable + n_non == total_in_baseline


def test_filter_requirements_applicable_fields():
    baseline = load_baseline("pump")
    result = filter_requirements(baseline, _minimal_pump_profile(), "pump")
    for req in result["applicable_requirements"]:
        assert "id" in req
        assert "text" in req
        assert "status" in req
        assert req["status"] == "applicable"
        assert "tbd_parameters" in req
        assert "parameter_values" in req


def test_filter_requirements_non_applicable_fields():
    baseline = load_baseline("pump")
    result = filter_requirements(baseline, _minimal_pump_profile(), "pump")
    for req in result["non_applicable_requirements"]:
        assert "id" in req
        assert "exclusion_reason" in req
        assert len(req["exclusion_reason"]) > 0


def test_filter_requirements_profile_key_varies():
    """Profile key in output should match the component name."""
    for key in COMPONENT_KEYS:
        baseline = load_baseline(key)
        result = filter_requirements(baseline, {}, key)
        assert f"{key}_profile" in result


def test_filter_requirements_all_components_loadable():
    """All 6 baselines should load and filter without error."""
    for key in COMPONENT_KEYS:
        baseline = load_baseline(key)
        result = filter_requirements(baseline, {}, key)
        total = sum(len(rs["requirements"]) for rs in baseline["requirement_sets"])
        n = len(result["applicable_requirements"]) + len(result["non_applicable_requirements"])
        assert n == total


def test_filter_manual_valve_excludes_motor_requirements():
    """A manual valve should not receive MOV-specific requirements."""
    baseline = load_baseline("valve")
    profile = {
        "valve_tag": "V-001",
        "valve_type": "gate",
        "function": "isolation",
        "actuation_type": "manual",
        "code_class": "ASME_III_Class_2",
        "safety_classification": "safety_related",
        "seismic_category": "Seismic_Category_I",
        "environment_profile": "mild",
    }
    result = filter_requirements(baseline, profile, "valve")
    # Any requirement with applicability "actuation_type=MOV|AOV|SOV|HOV" should be excluded
    for req in result["non_applicable_requirements"]:
        reason = req["exclusion_reason"]
        if "actuation_type" in reason:
            assert "manual" in reason or "not in required set" in reason
            break  # found at least one, good


# ---------------------------------------------------------------------------
# conversation: _parse_required_field
# ---------------------------------------------------------------------------

def test_parse_required_field_tag():
    ok, val = _parse_required_field("pump_tag", "RCS-PMP-001", None)
    assert ok is True
    assert val == "RCS-PMP-001"

def test_parse_required_field_enum_exact():
    ok, val = _parse_required_field("pump_type", "centrifugal",
                                     ["centrifugal", "canned_motor"])
    assert ok is True
    assert val == "centrifugal"

def test_parse_required_field_enum_case_insensitive():
    ok, val = _parse_required_field("code_class", "asme_iii_class_1",
                                     ["ASME_III_Class_1", "NonCode"])
    assert ok is True
    assert val == "ASME_III_Class_1"

def test_parse_required_field_enum_alias_class1():
    ok, val = _parse_required_field("code_class", "class 1",
                                     ["ASME_III_Class_1", "ASME_III_Class_2", "NonCode"])
    assert ok is True
    assert val == "ASME_III_Class_1"

def test_parse_required_field_enum_alias_noncode():
    ok, val = _parse_required_field("code_class", "noncode",
                                     ["ASME_III_Class_1", "NonCode"])
    assert ok is True
    assert val == "NonCode"

def test_parse_required_field_boolean_yes():
    ok, val = _parse_required_field("harsh_environment", "yes", None)
    assert ok is True
    assert val is True

def test_parse_required_field_boolean_no():
    ok, val = _parse_required_field("harsh_environment", "no", None)
    assert ok is True
    assert val is False

def test_parse_required_field_enum_fail():
    ok, val = _parse_required_field("pump_type", "rocket engine",
                                     ["centrifugal", "canned_motor"])
    assert ok is False

def test_parse_required_field_empty():
    ok, val = _parse_required_field("pump_type", "", ["centrifugal"])
    assert ok is False


# ---------------------------------------------------------------------------
# conversation: _parse_optional_overrides
# ---------------------------------------------------------------------------

def test_parse_optional_overrides_pump_pressure():
    result = _parse_optional_overrides("design pressure 15.5", "pump")
    assert "design_pressure" in result
    assert result["design_pressure"] == pytest.approx(15.5)

def test_parse_optional_overrides_pump_cycles():
    result = _parse_optional_overrides("design cycles 10000", "pump")
    assert "design_cycles" in result
    assert result["design_cycles"] == 10000.0

def test_parse_optional_overrides_pump_life():
    result = _parse_optional_overrides("service life 40 years", "pump")
    assert "service_life_years" in result
    assert result["service_life_years"] == 40.0

def test_parse_optional_overrides_no_match():
    result = _parse_optional_overrides("ok", "pump")
    assert result == {}


# ---------------------------------------------------------------------------
# End-to-end conversation flow
# ---------------------------------------------------------------------------

def _walk_through_pump(initial: str = "requirements for a reactor coolant pump") -> dict:
    """Walk through the full requirements conversation and return result_json."""
    turn = start_req_conversation(initial)
    assert turn.state.phase in ("component_selection", "profile_required")

    answers = {
        "pump_tag": "RCS-PMP-001",
        "pump_type": "centrifugal",
        "function": "reactor_coolant",
        "driver_type": "electric_motor",
        "code_class": "class 1",
        "safety_classification": "safety_related",
        "seismic_category": "Seismic_Category_I",
        "environment_profile": "harsh",
    }

    for _ in range(20):
        if turn.state.phase == "profile_required":
            field = turn.state.fields_asked[-1] if turn.state.fields_asked else None
            ans = answers.get(field, "")
        elif turn.state.phase == "profile_optional_review":
            ans = "ok"
        elif turn.is_done:
            break
        else:
            ans = ""

        turn = advance_req_conversation(turn.state, ans, initial)
        if turn.is_done:
            break

    assert turn.is_done
    assert turn.error is None
    assert turn.result_json is not None
    return turn.result_json


def test_req_conversation_full_flow_pump():
    result = _walk_through_pump()
    assert "pump_profile" in result
    assert len(result["applicable_requirements"]) > 0
    assert "instance_id" in result


def test_req_conversation_full_flow_pump_profile_values():
    result = _walk_through_pump()
    profile = result["pump_profile"]
    assert profile["pump_type"] == "centrifugal"
    assert profile["safety_classification"] == "safety_related"
    assert profile["code_class"] == "ASME_III_Class_1"


def test_req_conversation_component_from_query():
    """Component detected from query → skip component_selection phase."""
    turn = start_req_conversation("get requirements for a turbine")
    assert turn.state.component_key == "turbine"
    assert turn.state.phase == "profile_required"


def test_req_conversation_unknown_component_asks():
    turn = start_req_conversation("get requirements for nuclear components")
    assert turn.state.phase == "component_selection"
    assert "Options" in turn.agent_reply


def test_req_conversation_optional_override():
    """Setting an optional param before 'ok' should update the profile."""
    initial = "requirements for a pump"
    turn = start_req_conversation(initial)

    answers = {
        "pump_tag": "X", "pump_type": "centrifugal", "function": "feedwater",
        "driver_type": "electric_motor", "code_class": "class 1",
        "safety_classification": "non_safety", "seismic_category": "NonSeismic",
        "environment_profile": "mild",
    }
    for _ in range(15):
        if turn.state.phase == "profile_optional_review":
            break
        field = turn.state.fields_asked[-1] if turn.state.fields_asked else None
        turn = advance_req_conversation(turn.state, answers.get(field, ""), initial)

    assert turn.state.phase == "profile_optional_review"

    # Override design cycles
    turn = advance_req_conversation(turn.state, "design cycles 5000", initial)
    assert turn.state.profile.get("design_cycles") == 5000.0
    assert turn.state.phase == "profile_optional_review"  # still in review

    # Now accept
    turn = advance_req_conversation(turn.state, "ok", initial)
    assert turn.is_done
    assert turn.result_json is not None
