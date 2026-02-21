"""Unit tests for nucsys_agent/conversation.py"""
import pytest
from nucsys_agent.models import DesignSpec
from nucsys_agent.conversation import (
    _field_is_filled,
    _next_question,
    _parse_answer_into_spec,
    _parse_param_overrides,
    _parse_removal_request,
    _parse_property_override,
    _prune_topology,
    _format_node_list,
    _format_param_summary,
    _format_design_summary,
    start_conversation,
    advance_conversation,
)


# ---------------------------------------------------------------------------
# _field_is_filled
# ---------------------------------------------------------------------------

def test_field_is_filled_none():
    spec = DesignSpec(request_text="")
    assert not _field_is_filled(spec, "thermal_power_MWth")

def test_field_is_filled_unknown():
    spec = DesignSpec(request_text="")
    assert not _field_is_filled(spec, "system")
    assert not _field_is_filled(spec, "coolant")

def test_field_is_filled_value():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300.0)
    assert _field_is_filled(spec, "system")
    assert _field_is_filled(spec, "thermal_power_MWth")


# ---------------------------------------------------------------------------
# _next_question
# ---------------------------------------------------------------------------

def test_next_question_empty_spec():
    spec = DesignSpec(request_text="")
    q = _next_question(spec, [])
    assert q is not None
    assert q[0] == "system"

def test_next_question_skips_filled_fields():
    spec = DesignSpec(
        request_text="",
        system="primary_loop",
        thermal_power_MWth=300.0,
        coolant="water",
    )
    q = _next_question(spec, [])
    assert q is None

def test_next_question_skips_asked():
    spec = DesignSpec(request_text="")
    q = _next_question(spec, ["system"])
    assert q is not None
    assert q[0] == "thermal_power_MWth"


# ---------------------------------------------------------------------------
# _parse_answer_into_spec
# ---------------------------------------------------------------------------

def test_parse_system_primary():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "system", "primary_loop")
    assert new.system == "primary_loop"

def test_parse_system_keyword():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "system", "I want the primary coolant loop")
    assert new.system == "primary_loop"

def test_parse_system_bop():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "system", "bop")
    assert new.system == "bop_loop"

def test_parse_power_with_unit():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "thermal_power_MWth", "500 MWth")
    assert new.thermal_power_MWth == 500.0

def test_parse_power_bare_number():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "thermal_power_MWth", "300")
    assert new.thermal_power_MWth == 300.0

def test_parse_power_invalid_leaves_none():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "thermal_power_MWth", "lots of power")
    assert new.thermal_power_MWth is None

def test_parse_coolant_water():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "coolant", "light water")
    assert new.coolant == "water"

def test_parse_coolant_sodium():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "coolant", "liquid sodium")
    assert new.coolant == "sodium"


# ---------------------------------------------------------------------------
# _parse_param_overrides  (new)
# ---------------------------------------------------------------------------

def test_parse_param_override_primary_pressure():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("primary pressure 16 MPa", spec)
    assert new.primary_pressure_MPa == 16.0

def test_parse_param_override_hot_leg():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("hot leg 325°C", spec)
    assert new.primary_hot_leg_C == 325.0

def test_parse_param_override_steam_pressure():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("steam pressure 7 MPa", spec)
    assert new.secondary_pressure_MPa == 7.0

def test_parse_param_override_condenser():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("condenser 0.008 MPa", spec)
    assert new.condenser_pressure_MPa == pytest.approx(0.008, rel=1e-3)

def test_parse_param_override_feedwater():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("feedwater 230°C", spec)
    assert new.secondary_feedwater_C == 230.0

def test_parse_param_override_steam_temp():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("steam temp 285", spec)
    assert new.secondary_steam_C == 285.0

def test_parse_param_override_objective_min_pump():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("objective min_pump_power", spec)
    assert new.objective == "min_pump_power"

def test_parse_param_override_objective_min_ua():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("min ua", spec)
    assert new.objective == "min_UA"

def test_parse_param_override_no_change():
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    new = _parse_param_overrides("ok", spec)
    # "ok" should not change anything meaningful
    assert new.primary_pressure_MPa == spec.primary_pressure_MPa
    assert new.objective == spec.objective


# ---------------------------------------------------------------------------
# _format_param_summary  (new)
# ---------------------------------------------------------------------------

def test_format_param_summary_contains_fields():
    from nucsys_agent.config import AgentConfig
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water")
    cfg = AgentConfig()
    text = _format_param_summary(spec, cfg)
    assert "Primary pressure" in text
    assert "Optimization" in text
    assert "Steam" in text
    assert "ok" in text.lower()

def test_format_param_summary_shows_set_tag():
    from nucsys_agent.config import AgentConfig
    spec = DesignSpec(request_text="", system="primary_loop", thermal_power_MWth=300, coolant="water",
                      primary_pressure_MPa=16.0)
    cfg = AgentConfig()
    text = _format_param_summary(spec, cfg)
    assert "(set)" in text


# ---------------------------------------------------------------------------
# _prune_topology
# ---------------------------------------------------------------------------

def _get_pwr_card():
    from nucsys_agent.rag.store import CardStore
    store = CardStore.load_from_dir(None)
    return next(c for c in store.cards if c.id == "primary_loop_pwr_v1")


def test_prune_topology_no_removal():
    card = _get_pwr_card()
    pruned = _prune_topology(card, [])
    assert pruned is not card.topology_template  # deep copy
    orig_nodes = sum(len(b["nodes"]) for b in card.topology_template["buildings"])
    pruned_nodes = sum(len(b["nodes"]) for b in pruned["buildings"])
    assert orig_nodes == pruned_nodes


def test_prune_topology_removes_node():
    card = _get_pwr_card()
    pruned = _prune_topology(card, ["TAV"])
    for b in pruned["buildings"]:
        names = [n["name"] for n in b["nodes"]]
        assert "TAV" not in names


def test_prune_topology_removes_edges():
    card = _get_pwr_card()
    pruned = _prune_topology(card, ["TAV"])
    for b in pruned["buildings"]:
        for edge in b["edges"]:
            assert "TAV" not in edge


def test_prune_topology_does_not_mutate_original():
    card = _get_pwr_card()
    original_count = sum(len(b["nodes"]) for b in card.topology_template["buildings"])
    _prune_topology(card, ["TAV", "FWCV"])
    after_count = sum(len(b["nodes"]) for b in card.topology_template["buildings"])
    assert original_count == after_count


# ---------------------------------------------------------------------------
# _parse_removal_request
# ---------------------------------------------------------------------------

def test_parse_removal_ok():
    card = _get_pwr_card()
    assert _parse_removal_request("ok", card) == []
    assert _parse_removal_request("", card) == []
    assert _parse_removal_request("looks good", card) == []
    assert _parse_removal_request("proceed", card) == []

def test_parse_removal_single():
    card = _get_pwr_card()
    removed = _parse_removal_request("remove TAV", card)
    assert "TAV" in removed

def test_parse_removal_multiple():
    card = _get_pwr_card()
    removed = _parse_removal_request("remove TAV and FWCV", card)
    assert "TAV" in removed
    assert "FWCV" in removed


# ---------------------------------------------------------------------------
# _parse_property_override  (new)
# ---------------------------------------------------------------------------

def test_parse_property_override_turbine_efficiency():
    overrides = _parse_property_override("set Turbine efficiency 0.90", ["Turbine", "SG", "FWP"])
    assert "Turbine" in overrides
    assert overrides["Turbine"]["isentropic_efficiency"] == pytest.approx(0.90)

def test_parse_property_override_sg_area():
    overrides = _parse_property_override("set SG area 500", ["Turbine", "SG", "FWP"])
    assert "SG" in overrides
    assert overrides["SG"]["area_m2"] == 500.0

def test_parse_property_override_pump_efficiency():
    overrides = _parse_property_override("set FWP efficiency 0.85", ["Turbine", "SG", "FWP"])
    assert "FWP" in overrides
    assert overrides["FWP"]["efficiency"] == pytest.approx(0.85)

def test_parse_property_override_no_set_keyword():
    overrides = _parse_property_override("Turbine efficiency 0.90", ["Turbine"])
    assert overrides == {}

def test_parse_property_override_unknown_node():
    overrides = _parse_property_override("set UnknownNode efficiency 0.90", ["Turbine", "SG"])
    assert overrides == {}


# ---------------------------------------------------------------------------
# _format_node_list
# ---------------------------------------------------------------------------

def test_format_node_list():
    card = _get_pwr_card()
    text = _format_node_list(card)
    assert "Primary Source" in text
    assert "SG" in text
    assert "Turbine" in text

def test_format_node_list_shows_removed():
    card = _get_pwr_card()
    text = _format_node_list(card, removed_nodes=["TAV"])
    assert "[REMOVED]" in text


# ---------------------------------------------------------------------------
# End-to-end conversation flow
# ---------------------------------------------------------------------------

def test_fully_specified_query_goes_to_param_review():
    """A query with all required fields should jump to param_review (not straight to component_review)."""
    turn = start_conversation(
        "design the primary coolant system for a 300 MWth reactor, water coolant"
    )
    assert turn.state.phase == "param_review"
    assert "Operating parameters" in turn.agent_reply
    assert not turn.is_done


def test_param_review_ok_advances_to_component_review():
    """Saying 'ok' in param_review should advance to component_review."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    assert turn.state.phase == "param_review"
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "component_review"
    assert "Proposed components" in turn.agent_reply


def test_param_review_override_loops():
    """Providing an override should stay in param_review and show updated values."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    assert turn.state.phase == "param_review"
    turn = advance_conversation(turn.state, "primary pressure 16 MPa", initial)
    assert turn.state.phase == "param_review"
    assert turn.state.spec.primary_pressure_MPa == 16.0


def test_component_review_property_override_loops():
    """Setting a property in component_review should stay in component_review."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)  # param_review → component_review
    assert turn.state.phase == "component_review"

    turn = advance_conversation(turn.state, "set Turbine efficiency 0.90", initial)
    assert turn.state.phase == "component_review"
    assert "Turbine" in turn.state.node_overrides
    assert turn.state.node_overrides["Turbine"]["isentropic_efficiency"] == pytest.approx(0.90)


def test_component_review_removal_loops():
    """Removing a node should stay in component_review."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "component_review"

    turn = advance_conversation(turn.state, "remove TAV", initial)
    assert turn.state.phase == "component_review"
    assert "TAV" in turn.state.removed_nodes


def test_component_review_ok_runs_pipeline_and_goes_to_design_review():
    """'ok' in component_review should run the pipeline and enter design_review."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)  # param_review → component_review
    turn = advance_conversation(turn.state, "ok", initial)  # component_review → design_review
    assert turn.state.phase == "design_review"
    assert not turn.is_done
    assert "Design results" in turn.agent_reply


def test_design_review_done_finalises():
    """'done' in design_review should produce a final result."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "design_review"

    turn = advance_conversation(turn.state, "done", initial)
    assert turn.is_done
    assert turn.result is not None
    assert turn.error is None
    assert "Building" in turn.result.alchemy_db


def test_design_review_refinement_reruns_pipeline():
    """Providing a refinement in design_review should re-run the pipeline."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "design_review"

    turn2 = advance_conversation(turn.state, "primary pressure 16 MPa", initial)
    assert turn2.state.phase == "design_review"
    assert not turn2.is_done
    assert turn2.state.spec.primary_pressure_MPa == 16.0
    assert "Design updated" in turn2.agent_reply


def test_full_conversation_unspecified_query():
    """Walk through all phases with an underspecified initial query."""
    initial = "design a nuclear system"
    turn = start_conversation(initial)
    assert turn.state.phase == "spec_gaps"
    assert not turn.is_done

    # Fill required fields
    answers = {
        "system": "primary_loop",
        "thermal_power_MWth": "300 MWth",
        "coolant": "water",
    }

    for _ in range(10):
        if turn.state.phase != "spec_gaps":
            break
        asked_field = turn.state.spec_fields_asked[-1] if turn.state.spec_fields_asked else None
        ans = answers.get(asked_field, "")
        turn = advance_conversation(turn.state, ans, initial)

    assert turn.state.phase == "param_review"

    # Accept params
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "component_review"

    # Accept components
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "design_review"
    assert "Design results" in turn.agent_reply

    # Finalise
    turn = advance_conversation(turn.state, "done", initial)
    assert turn.is_done
    assert turn.result is not None
    assert turn.error is None
    assert "Building" in turn.result.alchemy_db


def test_conversation_with_component_removal():
    """Accept spec via pre-specified query then remove a valve."""
    initial = "design the primary coolant system for a 300 MWth reactor, water, minimize pumping power"
    turn = start_conversation(initial)

    # Get through spec_gaps (may already be in param_review)
    for _ in range(15):
        if turn.state.phase == "param_review":
            break
        turn = advance_conversation(turn.state, "", initial)

    assert turn.state.phase == "param_review"
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "component_review"

    # Remove TAV
    turn = advance_conversation(turn.state, "remove TAV", initial)
    assert turn.state.phase == "component_review"
    assert "TAV" in turn.state.removed_nodes

    # Accept
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.state.phase == "design_review"

    # Finalise
    turn = advance_conversation(turn.state, "done", initial)
    assert turn.is_done
    assert turn.error is None

    all_parts = [
        p["name"]
        for b in turn.result.alchemy_db.values()
        for p in b["parts"]
    ]
    assert "TAV" not in all_parts


def test_node_override_applied_in_output():
    """Node property overrides set in component_review should appear in the final output."""
    initial = "design the primary coolant system for a 300 MWth reactor, water coolant"
    turn = start_conversation(initial)
    turn = advance_conversation(turn.state, "ok", initial)  # param_review → component_review

    # Override SG area
    turn = advance_conversation(turn.state, "set SG area 600", initial)
    assert "SG" in turn.state.node_overrides

    turn = advance_conversation(turn.state, "ok", initial)  # run pipeline → design_review
    assert turn.result is not None

    # Find SG in alchemy_db
    sg_parts = [
        p for b in turn.result.alchemy_db.values()
        for p in b["parts"]
        if p["name"] == "SG"
    ]
    assert sg_parts, "SG not found in output"
    assert sg_parts[0]["properties"]["area_m2"] == pytest.approx(600.0)
