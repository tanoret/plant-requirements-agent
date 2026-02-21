"""Unit tests for nucsys_agent/conversation.py"""
import pytest
from nucsys_agent.models import DesignSpec
from nucsys_agent.conversation import (
    _field_is_filled,
    _next_question,
    _parse_answer_into_spec,
    _parse_removal_request,
    _prune_topology,
    _format_node_list,
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
    # All required fields filled; optional fields skipped by design → None
    q = _next_question(spec, [])
    assert q is None

def test_next_question_skips_asked():
    spec = DesignSpec(request_text="")
    q = _next_question(spec, ["system"])
    assert q is not None
    assert q[0] == "thermal_power_MWth"

def test_next_question_all_filled_and_asked():
    spec = DesignSpec(
        request_text="",
        system="primary_loop",
        thermal_power_MWth=300.0,
        coolant="water",
    )
    all_optional = [
        "objective", "primary_pressure_MPa", "primary_hot_leg_C",
        "secondary_pressure_MPa", "condenser_pressure_MPa",
        "secondary_feedwater_C", "secondary_steam_C",
    ]
    q = _next_question(spec, all_optional)
    assert q is None


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

def test_parse_objective_balanced_empty():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "objective", "")
    assert new.objective == "balanced"

def test_parse_objective_min_pump():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "objective", "min_pump_power")
    assert new.objective == "min_pump_power"

def test_parse_pressure_mpa():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "primary_pressure_MPa", "15.5 MPa")
    assert new.primary_pressure_MPa == 15.5

def test_parse_pressure_empty_leaves_none():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "primary_pressure_MPa", "")
    assert new.primary_pressure_MPa is None

def test_parse_temp_with_symbol():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "primary_hot_leg_C", "320°C")
    assert new.primary_hot_leg_C == 320.0

def test_parse_temp_bare():
    spec = DesignSpec(request_text="")
    new = _parse_answer_into_spec(spec, "secondary_steam_C", "280")
    assert new.secondary_steam_C == 280.0


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
    # node count unchanged
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
# _format_node_list
# ---------------------------------------------------------------------------

def test_format_node_list():
    card = _get_pwr_card()
    text = _format_node_list(card)
    assert "Primary Source" in text
    assert "SG" in text
    assert "Turbine" in text


# ---------------------------------------------------------------------------
# End-to-end conversation flow
# ---------------------------------------------------------------------------

def test_fully_specified_query_skips_to_component_review():
    """A query with all required fields should jump straight to Phase 2."""
    turn = start_conversation(
        "design the primary coolant system for a 300 MWth reactor, water coolant"
    )
    # Should be in component_review (no spec gaps remain for required fields)
    assert turn.state.phase == "component_review"
    assert "Proposed components" in turn.agent_reply
    assert not turn.is_done


def test_full_conversation_unspecified_query():
    """Walk through all phases with an underspecified initial query."""
    initial = "design a nuclear system"
    turn = start_conversation(initial)
    assert turn.state.phase == "spec_gaps"
    assert not turn.is_done

    answers = {
        "system": "primary_loop",
        "thermal_power_MWth": "300 MWth",
        "coolant": "water",
        "objective": "",                   # accept default
        "primary_pressure_MPa": "",
        "primary_hot_leg_C": "",
        "secondary_pressure_MPa": "",
        "condenser_pressure_MPa": "",
        "secondary_feedwater_C": "",
        "secondary_steam_C": "",
    }

    max_turns = 20
    for _ in range(max_turns):
        if turn.is_done or turn.state.phase == "component_review":
            break
        # Figure out which field we're being asked about
        asked_field = turn.state.spec_fields_asked[-1] if turn.state.spec_fields_asked else None
        ans = answers.get(asked_field, "")
        turn = advance_conversation(turn.state, ans, initial)

    assert turn.state.phase == "component_review"
    assert "Proposed components" in turn.agent_reply

    # Accept components as-is
    turn = advance_conversation(turn.state, "ok", initial)
    assert turn.is_done
    assert turn.result is not None
    assert turn.error is None
    assert "Building" in turn.result.alchemy_db


def test_conversation_with_component_removal():
    """Accept spec via pre-specified query then remove a valve."""
    initial = "design the primary coolant system for a 300 MWth reactor, water, minimize pumping power"
    turn = start_conversation(initial)
    # May need to answer a few optional questions
    for _ in range(15):
        if turn.state.phase == "component_review":
            break
        turn = advance_conversation(turn.state, "", initial)  # all defaults

    assert turn.state.phase == "component_review"

    # Remove TAV (turbine admission valve)
    turn = advance_conversation(turn.state, "remove TAV", initial)
    assert turn.is_done
    assert turn.error is None
    # TAV should not appear in the output
    all_parts = [
        p["name"]
        for b in turn.result.alchemy_db.values()
        for p in b["parts"]
    ]
    assert "TAV" not in all_parts
