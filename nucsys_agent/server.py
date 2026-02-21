from __future__ import annotations
from typing import Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .workflow import run_agent
from .exceptions import AgentError

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
