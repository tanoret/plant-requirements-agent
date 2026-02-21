# nucsys-agent

Semi-production-ready starter for a **pattern-card-driven** (RAG) nuclear system designer that outputs
**Alchemy-style JSON graphs** (buildings + parts + edgesIncoming/edgesOutgoing) and sizes key components
with deterministic thermodynamics/hydraulics.

## What's "production-ready" in this repo

- Package resources (ontology + cards) included in builds (`MANIFEST.in`, package-data)
- Structured logging (`LOG_LEVEL` or `--log-level`)
- Strict pattern card validation (Pydantic)
- Hard applicability checks (system tag must match)
- Deterministic sizing (no LLM numeric sizing)
- Simple Rankine closure using **IAPWS97** (fallback if not available)
- Export JSON schema validation (`schemas/alchemy_export.schema.json`)
- Minimal test suite (`pytest`)

---

## Install

```bash
python -m pip install -e .
export OPENAI_API_KEY="..."  # optional — enables improved spec parsing
```

---

## One-shot CLI

Provide all parameters in a single query and get the output JSON immediately:

```bash
nucsys-agent "design the primary coolant system for a 300 MWth nuclear reactor, minimize pumping power" --out out.json
```

---

## Interactive CLI

Use `--interactive` (or `-i`) to walk through the design step by step.
The agent guides you through four phases:

```bash
nucsys-agent "design a nuclear system" --interactive --out out.json
```

### Phase 1 — Spec gaps

The agent asks for any required information not already in your query.
Required fields: **system type**, **thermal power**, **coolant**.

```
Agent: Which system are you designing?
  Options: primary_loop, bop_loop, intermediate_loop
You: primary_loop

Agent: What is the thermal power in MWth?
You: 300 MWth

Agent: What coolant?  Options: water, sodium, co2, helium
You: water
```

If your initial query already contains all three required fields, this phase is skipped.

### Phase 2 — Parameter review

The agent displays every operating parameter with its current value and a `(default)` or `(set)` tag.
Type `ok` to accept, or override any value in plain English:

```
Agent: Required spec confirmed.

  Operating parameters:
    Optimization:       balanced             (set)
    Primary pressure:   15.50 MPa            (default)
    Primary hot-leg:    320.0 °C             (default)
    Steam pressure:     6.50 MPa             (default)
    Condenser pressure: 0.0100 MPa           (default)
    Feedwater temp:     220.0 °C             (default)
    Steam out temp:     280.0 °C             (default)

  Type 'ok' to use these values, or override any parameter, e.g.:
    'primary pressure 16 MPa'  /  'hot leg 325°C'  /  'steam pressure 7 MPa'
    'objective min_pump_power'  /  'feedwater 230°C'  /  'condenser 0.008 MPa'

You: primary pressure 16 MPa, hot leg 325°C
# → shows updated table, stays in this phase

You: ok
```

You can send multiple overrides in one message and the summary re-displays after each change.

### Phase 3 — Component review

The agent shows the proposed topology and lets you customise it before the pipeline runs.
You can send multiple edits before confirming:

```
Agent: Parameters saved. Matched pattern: PWR Primary Loop

  Proposed components:
    [Primary Loop]
      1. Primary Source  (reactor_core)
      2. SG              (steam_generator)
      3. Primary Sink    (pump)
    [BOP]
      4. TAV             (valve)
      5. Turbine         (turbine)
      6. FWP             (pump)
      7. FWCV            (valve)

  Type 'ok' to accept, or:
    - Remove components:    'remove TAV and FWCV'
    - Override a property:  'set Turbine efficiency 0.90'

You: remove TAV
# → TAV marked [REMOVED], stays in this phase

You: set Turbine efficiency 0.90
# → override stored, stays in this phase

You: ok
# → pipeline runs, moves to Phase 4
```

Recognised property aliases for `set <ComponentName> <property> <value>`:

| Alias | Maps to |
|---|---|
| `efficiency` | `isentropic_efficiency` (Turbine) / `efficiency` (pumps) |
| `area` | `area_m2` |
| `power` | `gross_power_MWe` (Turbine) / `shaft_power_MW` (pumps) |
| `delta_p` / `dp` | `delta_p_MPa` |

### Phase 4 — Design review & refinement

The agent runs the sizing pipeline and shows key results.
Type `done` to finalise, or keep refining — parameter and property overrides work here too,
and the pipeline re-runs immediately after each change:

```
Agent: Design results:
    Thermal power:      300 MWth
    Primary ΔT:         35.2 K
    Hot-leg / Cold-leg: 325 °C / 289 °C
    Primary flow:       1423 kg/s
    Pump power:         1.74 MW
    SG duty:            300 MW
    SG UA:              0.47 MW/K
    SG area:            157 m²
    Turbine gross:      94.8 MWe
    Net power:          93.1 MWe
    Cycle efficiency:   31.0 %
    Validation:         0 error(s), 0 warning(s)

  Type 'done' to save this design, or refine with:
    'primary pressure 16 MPa'  /  'hot leg 330°C'  /  'objective min_pump_power'
    'set Turbine efficiency 0.90'  /  'set SG area 500'

You: set Turbine efficiency 0.85
# → pipeline re-runs, shows updated results

You: done
# → writes out.json
```

---

## API server

```bash
uvicorn nucsys_agent.server:app --reload --port 8000
```

### `POST /design` — one-shot

```json
{ "query": "300 MWth primary loop water" }
```

### `POST /chat` — interactive (stateless)

The endpoint is stateless: the client sends the full conversation history on every call.

```json
{
  "initial_query": "design a nuclear system",
  "history": [
    { "role": "agent", "content": "Which system are you designing? ..." },
    { "role": "user",  "content": "primary_loop" }
  ]
}
```

Response:
```json
{
  "agent_reply": "...",
  "phase": "spec_gaps | param_review | component_review | design_review | done",
  "is_done": false,
  "spec": null,
  "alchemy_db": null,
  "validation_issues": null,
  "export_issues": null,
  "error": null
}
```

`spec`, `alchemy_db`, `validation_issues`, and `export_issues` are populated only on the final
turn (`is_done: true`).

---

## Customize guardrails

- Ontology allowlist: `nucsys_agent/data/ontology.yaml`
- Pattern cards: `nucsys_agent/data/cards/*.yaml`
- Export schema: `nucsys_agent/schemas/alchemy_export.schema.json`
