from __future__ import annotations
from typing import Any, Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .workflow import run_agent
from .exceptions import AgentError
from .cli import _is_requirements_query

app = FastAPI(title="nucsys-agent")


# ---------------------------------------------------------------------------
# Existing one-shot endpoint (unchanged)
# ---------------------------------------------------------------------------

class DesignRequest(BaseModel):
    query: str


@app.post("/design")
def design(req: DesignRequest):
    try:
        res = run_agent(req.query)
    except AgentError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "spec": res.spec.model_dump(),
        "validation_issues": [i.__dict__ for i in res.validation_issues],
        "export_issues": [i.__dict__ for i in res.export_issues],
        "alchemy_db": res.alchemy_db,
    }


# ---------------------------------------------------------------------------
# Interactive chat endpoint (stateless — client sends full history each call)
# ---------------------------------------------------------------------------

class ChatMessageRequest(BaseModel):
    role: Literal["user", "agent"]
    content: str


class ChatRequest(BaseModel):
    initial_query: str
    history: list[ChatMessageRequest] = []


class ChatResponse(BaseModel):
    agent_reply: str
    phase: str
    is_done: bool
    spec: dict | None = None
    alchemy_db: dict | None = None
    validation_issues: list | None = None
    export_issues: list | None = None
    error: str | None = None


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    from .conversation import (
        ChatMessage,
        advance_conversation,
        replay_history,
        start_conversation,
    )

    try:
        if not req.history:
            # First turn — start fresh
            turn = start_conversation(req.initial_query)
        else:
            # Reconstruct state from full message history (stateless replay)
            msgs = [ChatMessage(role=m.role, content=m.content) for m in req.history]
            state = replay_history(msgs, req.initial_query)

            # The most recent user message drives this turn
            last_user = next(
                (m.content for m in reversed(req.history) if m.role == "user"), ""
            )
            turn = advance_conversation(state, last_user, req.initial_query)

        resp = ChatResponse(
            agent_reply=turn.agent_reply,
            phase=turn.state.phase,
            is_done=turn.is_done,
            error=turn.error,
        )
        if turn.is_done and turn.result is not None:
            resp.spec = turn.result.spec.model_dump()
            resp.alchemy_db = turn.result.alchemy_db
            resp.validation_issues = [i.__dict__ for i in turn.result.validation_issues]
            resp.export_issues = [i.__dict__ for i in turn.result.export_issues]
        return resp

    except AgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Requirements endpoints
# ---------------------------------------------------------------------------

class RequirementsRequest(BaseModel):
    component_type: str
    profile: dict[str, Any]


@app.post("/requirements")
def requirements_oneshot(req: RequirementsRequest):
    """One-shot requirements filtering: provide component type + full profile."""
    from .requirements.loader import resolve_component, load_baseline
    from .requirements.filter import filter_requirements

    key = resolve_component(req.component_type)
    if key is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown component type '{req.component_type}'. "
                   "Valid types: pump, valve, condenser, steam_generator, pressurizer, turbine.",
        )
    try:
        baseline = load_baseline(key)
        result = filter_requirements(baseline, req.profile, key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


class ReqChatMessageRequest(BaseModel):
    role: Literal["user", "agent"]
    content: str


class ReqChatRequest(BaseModel):
    initial_query: str
    history: list[ReqChatMessageRequest] = []


class ReqChatResponse(BaseModel):
    agent_reply: str
    phase: str
    is_done: bool
    requirements_instance: dict | None = None
    error: str | None = None


@app.post("/requirements/chat", response_model=ReqChatResponse)
def requirements_chat(req: ReqChatRequest):
    """Interactive (stateless) requirements conversation endpoint."""
    from .requirements.conversation import (
        ReqChatMessage,
        start_req_conversation,
        advance_req_conversation,
        replay_req_history,
    )

    try:
        if not req.history:
            turn = start_req_conversation(req.initial_query)
        else:
            msgs = [ReqChatMessage(role=m.role, content=m.content) for m in req.history]
            state = replay_req_history(msgs, req.initial_query)
            last_user = next(
                (m.content for m in reversed(req.history) if m.role == "user"), ""
            )
            turn = advance_req_conversation(state, last_user, req.initial_query)

        resp = ReqChatResponse(
            agent_reply=turn.agent_reply,
            phase=turn.state.phase,
            is_done=turn.is_done,
            error=turn.error,
        )
        if turn.is_done and turn.result_json is not None:
            resp.requirements_instance = turn.result_json
        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Design-linked requirements endpoint
# ---------------------------------------------------------------------------

class DesignReqRequest(BaseModel):
    """Stateless requirements conversation seeded from a loop-design node.

    Typical flow
    ------------
    1. Call ``POST /design`` → receive ``alchemy_db``.
    2. Pick a node from ``alchemy_db`` (e.g. "Primary Sink", "SG", "Turbine").
    3. Send its ``properties`` dict as ``node_props`` here with an empty
       ``history`` to start the conversation.
    4. Repeat with growing ``history`` until ``is_done`` is true; the final
       response contains ``requirements_instance``.
    """
    node_name: str
    node_props: dict[str, Any]
    all_node_props: dict[str, dict[str, Any]] | None = None
    history: list[ReqChatMessageRequest] = []


@app.post("/requirements-from-design", response_model=ReqChatResponse)
def requirements_from_design(req: DesignReqRequest):
    """Interactive requirements conversation pre-seeded with loop-design parameters.

    Numeric optional fields (flow rate, head, rated power, thermal duty,
    operating pressures) are automatically extracted from the sized node
    properties.  Only classification fields (code class, safety category,
    seismic category, environment profile, tag, component sub-type) are
    asked interactively.
    """
    from .requirements.bridge import extract_design_numerics
    from .requirements.conversation import (
        ReqChatMessage,
        start_req_conversation_from_design,
        advance_req_conversation_from_design,
        replay_req_history_from_design,
    )

    try:
        if not req.history:
            turn = start_req_conversation_from_design(
                req.node_name,
                req.node_props,
                req.all_node_props,
            )
        else:
            component_key, prefilled_numeric = extract_design_numerics(
                req.node_name, req.node_props, req.all_node_props
            )
            if component_key is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Node '{req.node_name}' has no requirements mapping.",
                )
            msgs = [ReqChatMessage(role=m.role, content=m.content) for m in req.history]
            state = replay_req_history_from_design(msgs, component_key, prefilled_numeric)
            last_user = next(
                (m.content for m in reversed(req.history) if m.role == "user"), ""
            )
            turn = advance_req_conversation_from_design(state, last_user)

        resp = ReqChatResponse(
            agent_reply=turn.agent_reply,
            phase=turn.state.phase,
            is_done=turn.is_done,
            error=turn.error,
        )
        if turn.is_done and turn.result_json is not None:
            resp.requirements_instance = turn.result_json
        return resp

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Audit endpoint  (model auditability Q&A)
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    question: str
    topic_id: str | None = None   # optional: request a specific topic by ID


class AuditResponse(BaseModel):
    answer: str
    matched_topics: list[str]     # list of topic IDs that contributed to the answer
    available_topics: list[str]   # always returned for discoverability


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest):
    """Answer questions about the engineering models implemented in nucsys-agent.

    Supply a free-text ``question`` (e.g. "How is energy conservation done?",
    "What fluid properties are implemented?", "What are the model assumptions?").

    Alternatively, set ``topic_id`` to retrieve a specific topic directly.
    Call with ``question = "list"`` to get a catalogue of available topics.

    Matched topic IDs are returned alongside the answer so callers can request
    the full topic via ``topic_id`` in a follow-up call.
    """
    from .audit import AuditEngine, TOPICS

    engine = AuditEngine()
    available = engine.topic_ids()

    # Direct topic lookup by ID
    if req.topic_id:
        body = engine.get_topic(req.topic_id)
        if body is None:
            raise HTTPException(
                status_code=404,
                detail=f"Topic '{req.topic_id}' not found. "
                       f"Available: {', '.join(available)}",
            )
        return AuditResponse(
            answer=body,
            matched_topics=[req.topic_id],
            available_topics=available,
        )

    # Free-text question
    answer = engine.ask(req.question)

    # Determine which topics were matched (re-score to find them)
    from nucsys_agent.audit.engine import _score_topic, _tokenise, _MIN_SCORE
    import re as _re
    q_lower = req.question.lower()
    tokens  = _tokenise(q_lower)
    matched = [
        t["id"] for t in TOPICS
        if _score_topic(q_lower, tokens, t) >= _MIN_SCORE
    ]

    return AuditResponse(
        answer=answer,
        matched_topics=matched,
        available_topics=available,
    )
