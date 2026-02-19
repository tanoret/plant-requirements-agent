# nucsys-agent

Semi-production-ready starter for a **pattern-card-driven** (RAG) nuclear system designer that outputs
**Alchemy-style JSON graphs** (buildings + parts + edgesIncoming/edgesOutgoing) and sizes key components
with deterministic thermodynamics/hydraulics.

## What’s “production-ready” in this repo

- Package resources (ontology + cards) included in builds (`MANIFEST.in`, package-data)
- Structured logging (`LOG_LEVEL` or `--log-level`)
- Strict pattern card validation (Pydantic)
- Hard applicability checks (system tag must match)
- Deterministic sizing (no LLM numeric sizing)
- Simple Rankine closure using **IAPWS97** (fallback if not available)
- Export JSON schema validation (`schemas/alchemy_export.schema.json`)
- Minimal test suite (`pytest`)

## Install & Run

```bash
python -m pip install -e .
export OPENAI_API_KEY="..."  # optional (enables improved spec parsing)
nucsys-agent "design the primary coolant system for a 300 MWth nuclear reactor, minimize pumping power" --out out.json
```

## API server

```bash
uvicorn nucsys_agent.server:app --reload --port 8000
```

POST `/design` with JSON: `{"query":"..."}`

## Customize guardrails

- Ontology allowlist: `nucsys_agent/data/ontology.yaml`
- Pattern cards: `nucsys_agent/data/cards/*.yaml`
- Export schema: `nucsys_agent/schemas/alchemy_export.schema.json`
