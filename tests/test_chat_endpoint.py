"""Integration tests for the POST /chat API endpoint."""
import pytest
from fastapi.testclient import TestClient
from nucsys_agent.server import app

client = TestClient(app)


def test_chat_first_turn_returns_question():
    resp = client.post("/chat", json={"initial_query": "design a nuclear system", "history": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_done"] is False
    assert data["phase"] == "spec_gaps"
    assert len(data["agent_reply"]) > 0


def test_chat_first_turn_fully_specified_jumps_to_param_review():
    resp = client.post("/chat", json={
        "initial_query": "design primary coolant loop for 300 MWth, water",
        "history": [],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "param_review"
    assert "Operating parameters" in data["agent_reply"]


def test_chat_stateless_full_flow():
    """Drive the conversation to completion using the stateless /chat endpoint."""
    query = "design a nuclear system"
    history = []

    # Turn 1 — get first question
    r = client.post("/chat", json={"initial_query": query, "history": history})
    data = r.json()
    assert not data["is_done"]
    history.append({"role": "agent", "content": data["agent_reply"]})

    # Map each answer by field keyword in question text
    auto_answers = {
        "system": "primary_loop",
        "thermal": "300 MWth",
        "coolant": "water",
    }

    for _ in range(20):
        # Check phase first — content checks can false-match (e.g. "Thermal power" in design results)
        phase = data.get("phase", "")
        last_q = data["agent_reply"].lower()
        if phase == "design_review":
            ans = "done"
        elif phase == "param_review":
            ans = "ok"
        elif phase == "component_review":
            ans = "ok"
        elif "system" in last_q:
            ans = "primary_loop"
        elif "thermal" in last_q or "power" in last_q:
            ans = "300 MWth"
        elif "coolant" in last_q:
            ans = "water"
        else:
            ans = ""  # accept defaults

        history.append({"role": "user", "content": ans})
        r = client.post("/chat", json={"initial_query": query, "history": history})
        data = r.json()
        assert r.status_code == 200

        if data["is_done"]:
            break
        history.append({"role": "agent", "content": data["agent_reply"]})

    assert data["is_done"] is True
    assert data["alchemy_db"] is not None
    assert data["spec"] is not None
    assert data["error"] is None


def test_chat_existing_design_endpoint_unaffected():
    """Ensure /design still works after adding /chat."""
    resp = client.post("/design", json={"query": "300 MWth primary loop water"})
    assert resp.status_code == 200
    assert "alchemy_db" in resp.json()
