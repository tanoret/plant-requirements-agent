from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .workflow import run_agent
from .exceptions import AgentError

app = FastAPI(title="nucsys-agent")

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
