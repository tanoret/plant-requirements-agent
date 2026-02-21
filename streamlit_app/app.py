"""
nucsys-agent · Streamlit chatbot application
=============================================

Run with:
    streamlit run streamlit_app/app.py
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

# ── Page config (must be the very first Streamlit call) ──────────────────────
st.set_page_config(
    page_title="nucsys-agent · Nuclear Design",
    page_icon="⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Make nucsys_agent importable when running from this sub-directory ─────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* ── Sidebar ── */
[data-testid="stSidebar"] { min-width: 290px; max-width: 290px; }

/* ── Chat messages ── */
[data-testid="stChatMessage"] { border-radius: 12px; margin-bottom: 4px; }

/* ── Pre-formatted agent text (parameter tables, topology lists, etc.) ── */
.nucsys-pre {
    white-space: pre-wrap;
    font-family: "SFMono-Regular", "Consolas", "Menlo", monospace;
    font-size: 0.84em;
    line-height: 1.5;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}

/* ── Requirement badge ── */
.req-badge {
    display: inline-block;
    padding: 2px 12px;
    border-radius: 14px;
    font-size: 0.78em;
    font-weight: 700;
    letter-spacing: 0.04em;
}
.badge-done  { background: #1a7a4a; color: #fff; }
.badge-tbd   { background: #b36c00; color: #fff; }
.badge-idle  { background: #444;    color: #ccc; }

/* ── Subtle section header inside expander ── */
.req-section-title {
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #888;
    margin: 0.7rem 0 0.3rem;
}

/* ── API key test result ── */
.key-ok  { color: #3ddc84; font-weight: 600; font-size: 0.88em; }
.key-err { color: #ff6b6b; font-weight: 600; font-size: 0.88em; }
</style>
""",
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Schema: classification fields per component type
# ═══════════════════════════════════════════════════════════════════════════════

_CLASSIF: dict[str, list[dict[str, Any]]] = {
    "pump": [
        {"key": "pump_tag",             "label": "Tag / ID",                "type": "text",
         "help": "e.g. RCS-PMP-001"},
        {"key": "pump_type",            "label": "Pump type",               "type": "select",
         "options": ["centrifugal", "vertical_turbine", "positive_displacement",
                     "canned_motor", "submersible"]},
        {"key": "function",             "label": "Function",                "type": "select",
         "options": ["reactor_coolant", "feedwater", "condensate", "cooling_water",
                     "boric_acid", "charging", "other"]},
        {"key": "driver_type",          "label": "Driver type",             "type": "select",
         "options": ["electric_motor", "steam_turbine", "diesel_engine", "hydraulic"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3", "NonCode"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related", "augmented_quality"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild", "submerged", "outdoor"]},
    ],
    "steam_generator": [
        {"key": "sg_tag",               "label": "Tag / ID",                "type": "text",
         "help": "e.g. SG-001"},
        {"key": "sg_type",              "label": "SG type",                 "type": "select",
         "options": ["U_tube", "once_through", "helical_coil", "straight_tube"]},
        {"key": "primary_fluid",        "label": "Primary fluid",           "type": "select",
         "options": ["water", "sodium", "co2", "helium", "molten_salt"]},
        {"key": "secondary_fluid",      "label": "Secondary fluid",         "type": "select",
         "options": ["water_steam", "co2", "organic", "nitrogen"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3", "NonCode"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related", "augmented_quality"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild", "submerged", "outdoor"]},
    ],
    "turbine": [
        {"key": "turbine_tag",          "label": "Tag / ID",                "type": "text",
         "help": "e.g. TBN-001"},
        {"key": "turbine_type",         "label": "Turbine type",            "type": "select",
         "options": ["steam_condensing", "steam_backpressure", "steam_reheat", "gas"]},
        {"key": "working_fluid",        "label": "Working fluid",           "type": "select",
         "options": ["steam", "co2", "helium", "organic"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3",
                     "NonCode", "API_611", "API_612"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related", "augmented_quality"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild", "outdoor"]},
    ],
    "valve": [
        {"key": "valve_tag",            "label": "Tag / ID",                "type": "text",
         "help": "e.g. RCS-VLV-001"},
        {"key": "valve_type",           "label": "Valve type",              "type": "select",
         "options": ["gate", "globe", "check", "ball", "butterfly",
                     "safety_relief", "control"]},
        {"key": "actuation",            "label": "Actuation",               "type": "select",
         "options": ["motor_operated", "air_operated", "hydraulic", "manual", "self_acting"]},
        {"key": "function",             "label": "Function",                "type": "select",
         "options": ["isolation", "control", "check", "pressure_relief", "throttling"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_III_Class_1", "ASME_III_Class_2", "ASME_III_Class_3", "NonCode"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related", "augmented_quality"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild", "submerged", "outdoor"]},
    ],
    "condenser": [
        {"key": "condenser_tag",        "label": "Tag / ID",                "type": "text",
         "help": "e.g. CDN-001"},
        {"key": "condenser_type",       "label": "Condenser type",          "type": "select",
         "options": ["surface", "direct_contact", "air_cooled", "evaporative"]},
        {"key": "cooling_medium",       "label": "Cooling medium",          "type": "select",
         "options": ["seawater", "river_water", "cooling_tower_water", "air"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_VIII_Div1", "ASME_III_Class_3", "NonCode", "HEI"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related", "augmented_quality"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild", "outdoor"]},
    ],
    "pressurizer": [
        {"key": "pzr_tag",              "label": "Tag / ID",                "type": "text",
         "help": "e.g. PZR-001"},
        {"key": "vessel_type",          "label": "Vessel type",             "type": "select",
         "options": ["electric_heated", "steam_heated", "gas_pressurized"]},
        {"key": "code_class",           "label": "Code class",              "type": "select",
         "options": ["ASME_III_Class_1", "ASME_III_Class_2"]},
        {"key": "safety_classification","label": "Safety classification",   "type": "select",
         "options": ["safety_related", "non_safety_related"]},
        {"key": "seismic_category",     "label": "Seismic category",        "type": "select",
         "options": ["Seismic_Category_I", "Seismic_Category_II", "Non_Seismic"]},
        {"key": "environment_profile",  "label": "Environment profile",     "type": "select",
         "options": ["harsh", "mild"]},
    ],
}

_NUMERIC_DISPLAY: dict[str, list[tuple[str, str, str]]] = {
    "pump": [
        ("m_dot_kg_s",    "Mass flow",      "kg/s"),
        ("delta_p_MPa",   "Pressure rise",  "MPa"),
        ("shaft_power_MW","Shaft power",    "MW"),
        ("rho_kg_m3",     "Fluid density",  "kg/m³"),
    ],
    "steam_generator": [
        ("Q_MW",          "Thermal duty",   "MW"),
        ("UA_kW_per_K",   "UA",             "kW/K"),
        ("area_m2",       "HX area",        "m²"),
        ("lmtd_K",        "LMTD",           "K"),
    ],
    "turbine": [
        ("gross_power_MWe",       "Gross power",      "MWe"),
        ("isentropic_efficiency", "Isentropic eff.",  "—"),
        ("steam_quality_exit",    "Steam quality",    "—"),
    ],
    "valve":       [("delta_p_MPa", "Pressure drop", "MPa")],
    "condenser":   [("Q_MW", "Thermal duty", "MW"), ("condenser_pressure_MPa", "Pressure", "MPa")],
    "pressurizer": [("design_pressure_MPa", "Design pressure", "MPa")],
}

# ═══════════════════════════════════════════════════════════════════════════════
# Session state initialisation
# ═══════════════════════════════════════════════════════════════════════════════

def _init_state() -> None:
    defaults: dict[str, Any] = {
        "design_messages": [],   # [{role, content}]
        "chat_state":      None, # ChatState
        "initial_query":   "",
        "design_result":   None, # AgentResult
        "pending_result":  None, # AgentResult from latest pipeline run (before finalise)
        "alchemy_db":      None, # dict
        "req_data":        {},   # {node_name: {"result": dict|None}}
        "audit_messages":  [],   # [{role, content}] for the audit tab
        "provider":        "openai",
        "api_key":         "",
        "key_status":      None, # None | "ok" | "error: ..."
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ═══════════════════════════════════════════════════════════════════════════════
# Utility helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_api_key() -> None:
    """Propagate the sidebar API key into the environment."""
    os.environ.pop("OPENAI_API_KEY",    None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    key = st.session_state.get("api_key", "").strip()
    if not key:
        return
    if st.session_state["provider"] == "openai":
        os.environ["OPENAI_API_KEY"] = key
    elif st.session_state["provider"] == "anthropic":
        os.environ["ANTHROPIC_API_KEY"] = key


def _make_cfg():
    from nucsys_agent.config import AgentConfig
    return AgentConfig()


def _test_api_key() -> None:
    """Fire a minimal completion and store the result in session_state.key_status."""
    _apply_api_key()
    key = st.session_state.get("api_key", "").strip()
    if not key:
        st.session_state["key_status"] = "error: no key entered"
        return
    try:
        from nucsys_agent.llm import make_llm_client
        client = make_llm_client(_make_cfg())
        if client is None:
            st.session_state["key_status"] = "error: no key configured"
            return
        result = client.chat_json(
            [
                {"role": "system", "content": "Reply only with valid JSON."},
                {"role": "user",   "content": 'Return a JSON object: {"status": "ok"}'},
            ],
            temperature=0.0,
        )
        # Any successful JSON response is a pass
        st.session_state["key_status"] = "ok"
    except Exception as exc:
        st.session_state["key_status"] = f"error: {exc}"


def _reset() -> None:
    for k in ("design_messages", "chat_state", "initial_query",
              "design_result", "pending_result", "alchemy_db", "req_data", "audit_messages"):
        if k in ("design_messages", "audit_messages"):
            st.session_state[k] = []
        elif k == "req_data":
            st.session_state[k] = {}
        else:
            st.session_state[k] = None
    st.session_state["initial_query"] = ""
    st.rerun()


def _load_design_json(raw: bytes) -> bool:
    """Parse uploaded JSON bytes as an alchemy_db dict. Returns True on success."""
    try:
        db = json.loads(raw)
        if not isinstance(db, dict):
            return False
        st.session_state["alchemy_db"]    = db
        st.session_state["design_result"] = None   # no AgentResult available from file
        st.session_state["design_messages"].append(
            {"role": "assistant",
             "content": "✅ Design file loaded. "
                        "Switch to the **📐 Diagram** or **📋 Requirements** tab to continue."}
        )
        return True
    except Exception:
        return False


def _design_nodes() -> list[tuple[str, str, dict]]:
    if not st.session_state.get("alchemy_db"):
        return []
    from nucsys_agent.requirements.loader import resolve_component
    seen: set[str] = set()
    out: list[tuple[str, str, dict]] = []
    for building in st.session_state["alchemy_db"].values():
        for part in building.get("parts", []):
            name  = part.get("name", "")
            props = part.get("properties", {})
            ctype = props.get("canonical_type", "")
            key   = resolve_component(name) or resolve_component(ctype)
            if key and name not in seen:
                seen.add(name)
                out.append((name, key, props))
    return out


def _all_node_props() -> dict[str, dict]:
    if not st.session_state.get("alchemy_db"):
        return {}
    out: dict[str, dict] = {}
    for building in st.session_state["alchemy_db"].values():
        for part in building.get("parts", []):
            out[part.get("name", "")] = part.get("properties", {})
    return out


def _fmt(val: Any, unit: str) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:,.3g} {unit}".strip()
    return f"{val} {unit}".strip()


def _render_chat_content(content: str) -> None:
    """Render a design-chat message with mixed prose / structured blocks.

    The agent produces messages where a prose intro (e.g. "Required spec
    confirmed.") is followed by a blank line, then a parameter table with
    two-space-indented lines, then another blank line and a hint paragraph.
    We split on blank lines and render each block independently: prose blocks
    as Markdown (normal font, rendered formatting), structured blocks as
    white-space:pre-wrap so alignment is preserved.
    """
    import re
    blocks = re.split(r"\n{2,}", content)
    for block in blocks:
        if not block.strip():
            continue
        non_empty = [ln for ln in block.splitlines() if ln.strip()]
        if any(ln.startswith("  ") for ln in non_empty):
            escaped = _html.escape(block)
            st.markdown(
                f'<pre class="nucsys-pre">{escaped}</pre>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(block)


# ── Audit-specific rendering ──────────────────────────────────────────────────

_PRE_STYLE = (
    "background:#f6f8fa;padding:0.7rem 0.9rem;"
    "border-radius:6px;overflow-x:auto;font-size:0.82rem;"
    "line-height:1.55;white-space:pre-wrap;border:1px solid #e1e4e8"
)


def _is_caps_header(line: str) -> bool:
    """True if line is an ALL-CAPS section header: non-indented, first two chars uppercase."""
    if line.startswith((" ", "\t")):
        return False
    s = line.strip()
    if not s or re.match(r"^[─═]{3,}$", s):
        return False
    return len(s) >= 2 and s[0].isupper() and s[1].isupper()


def _render_audit_body(main_body: str) -> None:
    """Render topic body: ALL-CAPS headers as bold markdown, content blocks as <pre>.

    Topics with no ALL-CAPS headers (e.g. Architecture Overview) are rendered as
    a single pre block — all indented/numbered content is preserved verbatim.
    Topics with ALL-CAPS section headers (Fluid Properties, Rankine, etc.) get
    visual hierarchy: bold header + pre block per section.
    """
    import html as _html

    body_lines = main_body.splitlines()

    # Group into (header_text | None, content_lines) sections
    sections: list[tuple[str | None, list[str]]] = []
    cur_header: str | None = None
    cur_lines: list[str] = []

    for line in body_lines:
        if _is_caps_header(line):
            sections.append((cur_header, cur_lines))
            cur_header = line.strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    sections.append((cur_header, cur_lines))

    for header, content_lines in sections:
        # Trim leading/trailing blank lines
        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()

        if header:
            st.markdown(f"\n**{header}**")

        if not content_lines:
            continue

        # Intro section (no ALL-CAPS header yet): split leading non-indented prose
        # from any indented content that follows.  Render the prose as markdown and
        # the indented block as <pre>.  This prevents introductory sentences (e.g.
        # "nucsys-agent runs a deterministic…") from appearing inside a code box.
        if header is None:
            first_indented = next(
                (i for i, ln in enumerate(content_lines) if ln.strip() and ln.startswith(" ")),
                None,
            )
            if first_indented is None:
                # Purely non-indented → normal prose
                st.markdown("\n".join(content_lines))
                continue
            if first_indented > 0:
                prose = "\n".join(content_lines[:first_indented]).strip()
                if prose:
                    st.markdown(prose)
                content_lines = content_lines[first_indented:]

        text = "\n".join(content_lines)
        escaped = _html.escape(text)
        st.markdown(f'<pre style="{_PRE_STYLE}">{escaped}</pre>', unsafe_allow_html=True)


def _render_audit_message(content: str) -> None:
    """Render an AuditEngine response as structured Streamlit components.

    Strategy: extract the title (underlined with ─), then render the main body
    verbatim as a pre-formatted block, and pull REFERENCES / SOURCE CODE sections
    into collapsible expanders.  This is robust to any body format (numbered lists,
    indented code blocks, prose) without a fragile line-by-line parser.
    """
    # ── Topic-list output (the "list" / "topics" command) ────────────────────
    if content.startswith("Available topics"):
        lines = content.splitlines()
        out = []
        for line in lines:
            m = re.match(r"^\s+[·•]\s+(.*)", line)
            if m:
                parts = re.split(r"\s{2,}", m.group(1), maxsplit=1)
                title_part = parts[0].strip()
                eg_part    = parts[1].strip() if len(parts) > 1 else ""
                out.append(f"- **{title_part}**" + (f" — {eg_part}" if eg_part else ""))
            elif line.strip() and not re.match(r"^[─]{3,}$", line.strip()):
                out.append(line)
        st.markdown("\n".join(out))
        return

    # ── "I couldn't find a topic…" fallback ──────────────────────────────────
    if content.startswith("I couldn't find"):
        parts = content.split("\n\n", 1)
        st.warning(parts[0])
        if len(parts) > 1:
            _render_audit_message(parts[1])
        return

    # ── One or more topic blocks separated by ─ * 40+ ───────────────────────
    TOPIC_SEP = re.compile(r"\n─{40,}\n")
    topic_blocks = TOPIC_SEP.split(content)

    for idx, block in enumerate(topic_blocks):
        if not block.strip():
            continue
        if idx > 0:
            st.divider()

        lines = block.splitlines()

        # Extract title: first non-blank line followed immediately by a ─ underline
        title = ""
        body_start = 0
        for li, ln in enumerate(lines):
            if ln.strip() and li + 1 < len(lines) and re.match(r"^[─]{3,}$", lines[li + 1].strip()):
                title = ln.strip()
                body_start = li + 2
                break

        if title:
            st.subheader(title, divider="gray")

        # Remaining text after the title underline
        remaining = "\n".join(lines[body_start:])

        # Split off REFERENCES and SOURCE CODE sections (appended by engine.py)
        refs_pat = re.compile(r"\nREFERENCES\n──+\n?", re.MULTILINE)
        src_pat  = re.compile(r"\nSOURCE CODE\n──+\n?",  re.MULTILINE)

        refs_m = refs_pat.search(remaining)
        src_m  = src_pat.search(remaining)

        cut = min(
            refs_m.start() if refs_m else len(remaining),
            src_m.start()  if src_m  else len(remaining),
        )
        main_body = remaining[:cut].strip()
        refs_text = remaining[refs_m.end():src_m.start() if (src_m and src_m.start() > refs_m.start()) else len(remaining)] if refs_m else ""
        src_text  = remaining[src_m.end():]  if src_m  else ""

        # Render main body: split at ALL-CAPS section headers, render each
        # section's content verbatim as <pre>.  Topics with no ALL-CAPS headers
        # (e.g. Architecture Overview) are rendered as a single <pre> block.
        if main_body:
            _render_audit_body(main_body)

        # References expander
        refs = [m.group(1) for line in refs_text.splitlines()
                for m in [re.match(r"^\s*[·•]\s+(.*)", line)] if m]
        if refs:
            with st.expander(f"📚 References ({len(refs)})", expanded=False):
                for ref in refs:
                    st.markdown(f"- {ref}")

        # Source files expander
        srcs = [m.group(1) for line in src_text.splitlines()
                for m in [re.match(r"^\s*[·•]\s+(.*)", line)] if m]
        if srcs:
            with st.expander("📁 Source code", expanded=False):
                for src in srcs:
                    st.markdown(f"`{src}`")


# ═══════════════════════════════════════════════════════════════════════════════
# Design-chat phase widgets  (editable forms shown between messages and input)
# ═══════════════════════════════════════════════════════════════════════════════

def _chat_placeholder() -> str:
    """Return the chat-input placeholder text for the current conversation phase."""
    state = st.session_state.get("chat_state")
    if state is None:
        return "e.g. '300 MWth primary loop, water cooled, minimize pump power'"
    if state.phase == "spec_gaps":
        return "Type your answer…"
    if state.phase == "param_review":
        return "Or type overrides manually: 'primary pressure 16 MPa', 'hot leg 325 °C' — 'ok' to accept all"
    if state.phase == "component_review":
        return "Or type: 'remove TAV'  /  'set Turbine efficiency 0.90'  — 'ok' to proceed"
    if state.phase == "design_review":
        return "Refine: 'primary pressure 16 MPa'  /  'objective min_pump_power'  — type 'done' to finalise"
    return "Type a message…"


def _render_param_editor(chat_state: Any, cfg: Any) -> None:
    """Inline form for editing operating parameters during the param_review phase."""
    from nucsys_agent.models import DesignSpec
    from nucsys_agent.conversation import advance_conversation

    spec          = chat_state.spec
    initial_query = st.session_state.get("initial_query", "")

    with st.container(border=True):
        st.markdown("**✏️ Review & edit operating parameters** — adjust values, then click Accept")

        with st.form("param_editor_form"):
            obj_opts = ["min_pump_power", "min_UA", "balanced", "baseline"]
            cur_obj  = spec.objective or "min_pump_power"
            obj_idx  = obj_opts.index(cur_obj) if cur_obj in obj_opts else 0

            col1, col2 = st.columns(2)
            with col1:
                objective = st.selectbox(
                    "Optimization objective", obj_opts, index=obj_idx,
                )
                p_press = st.number_input(
                    "Primary pressure (MPa)",
                    value=float(spec.primary_pressure_MPa or cfg.default_primary_pressure_MPa),
                    min_value=1.0, max_value=25.0, step=0.5,
                )
                p_hot = st.number_input(
                    "Hot-leg temperature (°C)",
                    value=float(spec.primary_hot_leg_C or cfg.default_primary_hot_leg_C),
                    min_value=100.0, max_value=600.0, step=5.0,
                )
                sec_p = st.number_input(
                    "Steam pressure (MPa)",
                    value=float(spec.secondary_pressure_MPa or cfg.default_secondary_pressure_MPa),
                    min_value=0.1, max_value=15.0, step=0.1,
                )
            with col2:
                cond_p = st.number_input(
                    "Condenser pressure (MPa)",
                    value=float(spec.condenser_pressure_MPa or cfg.default_condenser_pressure_MPa),
                    min_value=0.001, max_value=0.1, step=0.001,
                    format="%.4f",
                )
                fw_t = st.number_input(
                    "Feedwater temperature (°C)",
                    value=float(spec.secondary_feedwater_C or cfg.default_secondary_feedwater_C),
                    min_value=20.0, max_value=400.0, step=5.0,
                )
                stm_t = st.number_input(
                    "Steam outlet temp (°C)",
                    value=float(spec.secondary_steam_C or cfg.default_secondary_steam_C),
                    min_value=100.0, max_value=600.0, step=5.0,
                )

            submitted = st.form_submit_button(
                "Accept Parameters →", type="primary", use_container_width=True
            )

        if submitted:
            data = spec.model_dump()
            data.update({
                "objective":             objective,
                "primary_pressure_MPa":  p_press,
                "primary_hot_leg_C":     p_hot,
                "secondary_pressure_MPa": sec_p,
                "condenser_pressure_MPa": cond_p,
                "secondary_feedwater_C": fw_t,
                "secondary_steam_C":     stm_t,
            })
            chat_state.spec = DesignSpec(**data)

            with st.spinner("Selecting topology…"):
                try:
                    turn = advance_conversation(chat_state, "ok", initial_query, cfg=cfg)
                    st.session_state["chat_state"] = turn.state
                    st.session_state["design_messages"].append(
                        {"role": "user", "content": "✓ Parameters accepted via form"}
                    )
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": turn.agent_reply}
                    )
                    if turn.result is not None:
                        st.session_state["pending_result"] = turn.result
                    if turn.is_done and turn.result is not None:
                        st.session_state["design_result"] = turn.result
                        st.session_state["alchemy_db"]    = turn.result.alchemy_db
                        st.balloons()
                except Exception as exc:
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": f"⚠️ Error: {exc}"}
                    )
            st.rerun()


def _render_component_editor(chat_state: Any, cfg: Any) -> None:
    """Checkbox panel for selecting which components to include (component_review phase)."""
    from nucsys_agent.conversation import _get_card_by_id, advance_conversation

    initial_query = st.session_state.get("initial_query", "")
    card = _get_card_by_id(
        chat_state.card_id, initial_query, chat_state.spec, cfg
    )
    if card is None or not card.topology_template:
        return

    # Deduplicate nodes by name: shared interface nodes (e.g. SG) appear in
    # multiple buildings in the topology template.  We keep the first occurrence
    # so only one checkbox is rendered per unique node name.
    seen: set[str] = set()
    buildings_data: list[tuple[str, list[dict]]] = []
    for building in card.topology_template.get("buildings", []):
        unique_nodes = [n for n in building.get("nodes", []) if n["name"] not in seen
                        and not seen.add(n["name"])]  # type: ignore[func-returns-value]
        if unique_nodes:
            buildings_data.append((building["name"], unique_nodes))

    all_nodes: list[tuple[str, bool]] = []

    with st.container(border=True):
        st.markdown("**🔩 Component selection** — uncheck to remove a component, then click Proceed")

        with st.form("component_editor_form"):
            cols = st.columns(max(1, len(buildings_data)))
            for col, (bname, nodes) in zip(cols, buildings_data):
                with col:
                    st.markdown(f"**{bname}**")
                    for node in nodes:
                        name  = node["name"]
                        ctype = node.get("canonical_type", "")
                        kept  = name not in chat_state.removed_nodes
                        val   = st.checkbox(f"{name}  _{ctype}_", value=kept, key=f"ce_{name}")
                        all_nodes.append((name, val))

            submitted = st.form_submit_button(
                "Proceed to Design →", type="primary", use_container_width=True
            )

        if submitted:
            chat_state.removed_nodes = [name for name, kept in all_nodes if not kept]

            with st.spinner("Running design pipeline…"):
                try:
                    turn = advance_conversation(chat_state, "ok", initial_query, cfg=cfg)
                    st.session_state["chat_state"] = turn.state
                    st.session_state["design_messages"].append(
                        {"role": "user", "content": "✓ Components accepted via form"}
                    )
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": turn.agent_reply}
                    )
                    if turn.result is not None:
                        st.session_state["pending_result"] = turn.result
                    if turn.is_done and turn.result is not None:
                        st.session_state["design_result"] = turn.result
                        st.session_state["alchemy_db"]    = turn.result.alchemy_db
                        st.balloons()
                except Exception as exc:
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": f"⚠️ Error: {exc}"}
                    )
            st.rerun()


def _render_design_finalizer(chat_state: Any, cfg: Any) -> None:
    """Metrics panel + Finalise button shown during the design_review phase."""
    from nucsys_agent.conversation import advance_conversation

    initial_query = st.session_state.get("initial_query", "")
    pending = st.session_state.get("pending_result")

    with st.container(border=True):
        # ── Key metrics from the latest pipeline run ──────────────────────────
        if pending is not None:
            props_by_name: dict[str, Any] = {}
            for b in pending.buildings.values():
                for n in b.parts:
                    props_by_name[n.name] = n.properties

            metric_items: list[tuple[str, str]] = []
            if "Primary Source" in props_by_name:
                p = props_by_name["Primary Source"]
                if p.get("thermal_power_MWth") is not None:
                    metric_items.append(("Thermal Power", f"{p['thermal_power_MWth']:.0f} MWth"))
            if "Turbine" in props_by_name:
                p = props_by_name["Turbine"]
                if p.get("net_power_MWe") is not None:
                    metric_items.append(("Net Power", f"{p['net_power_MWe']:.1f} MWe"))
                if p.get("cycle_efficiency") is not None:
                    metric_items.append(("Cycle Eff.", f"{p['cycle_efficiency'] * 100:.1f} %"))
            if "SG" in props_by_name:
                p = props_by_name["SG"]
                if p.get("area_m2") is not None:
                    metric_items.append(("SG Area", f"{p['area_m2']:.0f} m²"))
            if "Primary Sink" in props_by_name:
                p = props_by_name["Primary Sink"]
                if p.get("shaft_power_MW") is not None:
                    metric_items.append(("Pump Power", f"{p['shaft_power_MW']:.2f} MW"))

            if metric_items:
                cols = st.columns(len(metric_items))
                for col, (label, value) in zip(cols, metric_items):
                    col.metric(label, value)

        # ── Finalise / refine buttons ─────────────────────────────────────────
        cap_col, btn_col = st.columns([3, 1])
        cap_col.caption(
            "Refine using the chat below, or click **Finalise** to lock the design "
            "and switch to the Diagram and Requirements tabs."
        )
        if btn_col.button(
            "Finalise Design ✓", type="primary", use_container_width=True, key="btn_finalise"
        ):
            with st.spinner("Finalising design…"):
                try:
                    turn = advance_conversation(chat_state, "done", initial_query, cfg=cfg)
                    st.session_state["chat_state"] = turn.state
                    st.session_state["design_messages"].append(
                        {"role": "user", "content": "done"}
                    )
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": turn.agent_reply}
                    )
                    if turn.result is not None:
                        st.session_state["design_result"]  = turn.result
                        st.session_state["alchemy_db"]     = turn.result.alchemy_db
                        st.session_state["pending_result"] = None
                        st.balloons()
                except Exception as exc:
                    st.session_state["design_messages"].append(
                        {"role": "assistant", "content": f"⚠️ Error: {exc}"}
                    )
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements panel helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _render_req_result(result: dict, node_name: str) -> None:
    applicable     = result.get("applicable_requirements", [])
    non_applicable = result.get("non_applicable_requirements", [])
    validation     = result.get("validation", {})
    tbd_count      = sum(1 for r in applicable if r.get("tbd_parameters"))

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Applicable",     len(applicable))
    col_b.metric("TBD parameters", tbd_count,
                 delta="needs values" if tbd_count else None,
                 delta_color="inverse" if tbd_count else "off")
    col_c.metric("Not applicable", len(non_applicable))

    if validation.get("overall_status") == "pass":
        st.success("Validation passed")
    else:
        for issue in validation.get("issues", []):
            st.warning(issue.get("message", str(issue)))

    if applicable:
        with st.expander(f"📄 Applicable requirements ({len(applicable)})", expanded=True):
            rows = [
                {
                    "ID":          r.get("id", ""),
                    "Type":        r.get("type", ""),
                    "Requirement": r.get("text", ""),
                    "TBD params":  ", ".join(r.get("tbd_parameters", [])) or "—",
                    "Verification": ", ".join(
                        r.get("verification", {}).get("method", [])
                    ) or "—",
                }
                for r in applicable
            ]
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ID":          st.column_config.TextColumn("ID",          width=100),
                    "Type":        st.column_config.TextColumn("Type",        width=110),
                    "Requirement": st.column_config.TextColumn("Requirement", width=None),
                    "TBD params":  st.column_config.TextColumn("TBD params",  width=150),
                    "Verification":st.column_config.TextColumn("Verification",width=120),
                },
            )

    if non_applicable:
        with st.expander(f"Excluded requirements ({len(non_applicable)})"):
            rows = [
                {
                    "ID":     r.get("id", ""),
                    "Type":   r.get("type", ""),
                    "Requirement": r.get("text", ""),
                    "Reason": r.get("exclusion_reason", ""),
                }
                for r in non_applicable
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True,
                         column_config={
                             "ID":          st.column_config.TextColumn("ID",    width=100),
                             "Type":        st.column_config.TextColumn("Type",  width=110),
                             "Requirement": st.column_config.TextColumn("Requirement", width=None),
                             "Reason":      st.column_config.TextColumn("Reason",width=200),
                         })

    safe_name = node_name.lower().replace(" ", "_")
    st.download_button(
        "⬇️  Download requirements JSON",
        data=json.dumps(result, indent=2),
        file_name=f"{safe_name}_requirements.json",
        mime="application/json",
        use_container_width=True,
    )


def _render_req_panel(node_name: str, comp_key: str,
                      node_props: dict, all_props: dict) -> None:
    rd = st.session_state["req_data"].setdefault(node_name, {"result": None})

    if rd["result"] is not None:
        _render_req_result(rd["result"], node_name)
        if st.button("🔄  Regenerate", key=f"regen_{node_name}"):
            rd["result"] = None
            st.rerun()
        return

    # Numeric prefill from design
    numeric_prefill: dict[str, Any] = {}
    try:
        from nucsys_agent.requirements.bridge import extract_design_numerics
        _, numeric_prefill = extract_design_numerics(node_name, node_props, all_props) or (None, {})
        numeric_prefill = numeric_prefill or {}
    except Exception:
        pass

    # Show design-derived numerics as metric tiles
    design_summary = node_props.get("design_summary", {})
    all_numeric    = {**design_summary, **node_props, **numeric_prefill}
    visible        = [(label, _fmt(all_numeric.get(k), unit))
                      for k, label, unit in _NUMERIC_DISPLAY.get(comp_key, [])
                      if all_numeric.get(k) is not None]

    if visible:
        st.markdown('<p class="req-section-title">Design parameters (pre-filled)</p>',
                    unsafe_allow_html=True)
        cols = st.columns(min(len(visible), 4))
        for i, (label, val) in enumerate(visible):
            cols[i % 4].metric(label, val)
        st.divider()

    # Classification form
    st.markdown('<p class="req-section-title">Classification parameters</p>',
                unsafe_allow_html=True)
    fields = _CLASSIF.get(comp_key, [])
    if not fields:
        st.info(f"No classification schema defined for '{comp_key}'.")
        return

    with st.form(key=f"req_form_{node_name}"):
        half    = len(fields) // 2 + len(fields) % 2
        col_l, col_r = st.columns(2)
        widget_vals: dict[str, Any] = {}
        for col, col_fields in ((col_l, fields[:half]), (col_r, fields[half:])):
            with col:
                for f in col_fields:
                    fkey, label, ftype = f["key"], f["label"], f["type"]
                    pre = numeric_prefill.get(fkey)
                    if ftype == "text":
                        widget_vals[fkey] = st.text_input(
                            label, value=str(pre) if pre is not None else "",
                            help=f.get("help", ""),
                            key=f"rf_{node_name}_{fkey}",
                        )
                    else:
                        opts = f["options"]
                        idx  = opts.index(pre) if pre in opts else 0
                        widget_vals[fkey] = st.selectbox(
                            label, options=opts, index=idx,
                            key=f"rf_{node_name}_{fkey}",
                        )
        submitted = st.form_submit_button(
            "⚙️  Generate Requirements", type="primary", use_container_width=True
        )

    if submitted:
        profile = {**numeric_prefill, **{k: v for k, v in widget_vals.items() if v != ""}}
        with st.spinner("Filtering requirements…"):
            try:
                from nucsys_agent.requirements.loader import load_baseline
                from nucsys_agent.requirements.filter import filter_requirements
                rd["result"] = filter_requirements(load_baseline(comp_key), profile, comp_key)
                st.rerun()
            except Exception as exc:
                st.error(f"Requirements error: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚛️ nucsys-agent")
    st.caption("Nuclear System Design · Requirements · Diagram · Audit")
    st.divider()

    # ── LLM configuration ─────────────────────────────────────────────────────
    st.markdown("**LLM Configuration**")
    st.selectbox(
        "Provider",
        options=["openai", "anthropic", "none"],
        format_func=lambda x: {
            "openai":    "OpenAI",
            "anthropic": "Anthropic / Claude",
            "none":      "None  (regex-only)",
        }[x],
        key="provider",
        help="Priority: Anthropic → OpenAI → regex-only. All sizing is deterministic.",
        on_change=lambda: st.session_state.update({"key_status": None}),
    )

    if st.session_state["provider"] != "none":
        is_anthropic = st.session_state["provider"] == "anthropic"
        st.text_input(
            "Anthropic API Key" if is_anthropic else "OpenAI API Key",
            type="password",
            key="api_key",
            placeholder="sk-ant-…" if is_anthropic else "sk-…",
            help="Stored in browser session only — never written to disk.",
            on_change=lambda: st.session_state.update({"key_status": None}),
        )
        with st.expander("Model override (optional)"):
            env_key  = "ANTHROPIC_MODEL" if is_anthropic else "OPENAI_MODEL"
            default  = "claude-haiku-4-5-20251001" if is_anthropic else "gpt-4.1-mini"
            override = st.text_input(
                "Model ID", value=os.environ.get(env_key, default),
                key=f"_model_{st.session_state['provider']}",
            )
            if override:
                os.environ[env_key] = override

        # ── Inject & Test button ──────────────────────────────────────────────
        if st.button("🔌  Inject & Test key", use_container_width=True):
            with st.spinner("Testing connection…"):
                _test_api_key()

        # Status indicator (persists until key changes)
        status = st.session_state.get("key_status")
        if status == "ok":
            st.markdown('<p class="key-ok">✅ Connection successful</p>',
                        unsafe_allow_html=True)
        elif status and status.startswith("error"):
            msg = status[len("error: "):]
            st.markdown(f'<p class="key-err">❌ {_html.escape(msg)}</p>',
                        unsafe_allow_html=True)
    else:
        st.session_state["api_key"] = ""
        st.info("Regex-only — no key needed.")

    st.divider()

    # ── Load design file ───────────────────────────────────────────────────────
    st.markdown("**Load existing design**")
    uploaded = st.file_uploader(
        "Upload alchemy JSON", type=["json"], label_visibility="collapsed",
        help="Load a previously saved alchemy_db JSON to resume requirements or diagram.",
    )
    if uploaded is not None:
        if _load_design_json(uploaded.read()):
            st.success("Design loaded")
        else:
            st.error("Invalid JSON file — expected an alchemy_db dict.")

    st.divider()

    # ── Session status ────────────────────────────────────────────────────────
    st.markdown("**Session**")
    if st.session_state.get("alchemy_db"):
        result = st.session_state.get("design_result")
        if result and result.spec:
            sp = result.spec
            pwr  = f"{sp.thermal_power_MWth} MWth" if sp.thermal_power_MWth else "?"
            st.success(f"✅ {pwr} · {sp.system or '?'} · {sp.coolant or '?'}")
        else:
            st.success("✅ Design loaded from file")
        nodes = _design_nodes()
        done  = sum(1 for n, _, _ in nodes
                    if (st.session_state["req_data"].get(n) or {}).get("result"))
        st.caption(f"Nodes: {len(nodes)}  ·  Reqs: {done}/{len(nodes)}")
    else:
        st.info("No design yet — start chatting ↗")

    if st.button("🔄  New session", use_container_width=True, type="secondary"):
        _reset()

# Apply API key on every rerun
_apply_api_key()

# ═══════════════════════════════════════════════════════════════════════════════
# Main content — four tabs
# ═══════════════════════════════════════════════════════════════════════════════

tab_chat, tab_diagram, tab_reqs, tab_audit = st.tabs(
    ["💬  Design Chat", "📐  Diagram", "📋  Requirements", "🔍  Model Audit"]
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 1 — Design Chat                                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

with tab_chat:
    st.markdown("### Design a Nuclear System")
    st.caption(
        "Describe what you want to build in plain English. "
        "The agent asks for any missing information, shows the proposed topology, "
        "runs the sizing pipeline, and saves the design.  "
        "You can also load a saved design from the sidebar."
    )

    # Render conversation history
    for msg in st.session_state["design_messages"]:
        with st.chat_message(msg["role"], avatar="⚛️" if msg["role"] == "assistant" else None):
            _render_chat_content(msg["content"])

    # ── Phase-specific interactive widgets ─────────────────────────────────────
    # These appear between the last message and the chat input so the user can
    # edit values directly without having to type free-form overrides.
    _chat_state = st.session_state.get("chat_state")
    if _chat_state is not None and not st.session_state.get("alchemy_db"):
        _cfg = _make_cfg()
        if _chat_state.phase == "param_review":
            _render_param_editor(_chat_state, _cfg)
        elif _chat_state.phase == "component_review":
            _render_component_editor(_chat_state, _cfg)
        elif _chat_state.phase == "design_review":
            _render_design_finalizer(_chat_state, _cfg)

    # Design-complete banner
    if st.session_state.get("alchemy_db"):
        st.success(
            "✅ **Design complete.** "
            "Switch to the **📐 Diagram** or **📋 Requirements** tab to continue."
        )
        result = st.session_state.get("design_result")
        if result:
            for i in result.validation_issues:
                if getattr(i, "severity", "") == "error":
                    st.error(f"Validation: {i.message}")

    # Chat input — placeholder updates to match the current conversation phase
    prompt = st.chat_input(
        placeholder=_chat_placeholder(),
        disabled=bool(st.session_state.get("alchemy_db")),
    )

    if prompt:
        st.session_state["design_messages"].append({"role": "user", "content": prompt})

        with st.spinner("Thinking…"):
            try:
                from nucsys_agent.conversation import start_conversation, advance_conversation
                cfg = _make_cfg()

                if st.session_state["chat_state"] is None:
                    st.session_state["initial_query"] = prompt
                    turn = start_conversation(prompt, cfg=cfg)
                else:
                    turn = advance_conversation(
                        st.session_state["chat_state"],
                        prompt,
                        st.session_state["initial_query"],
                        cfg=cfg,
                    )

                st.session_state["chat_state"] = turn.state
                st.session_state["design_messages"].append(
                    {"role": "assistant", "content": turn.agent_reply}
                )

                # Track the latest pipeline result even before finalising
                if turn.result is not None:
                    st.session_state["pending_result"] = turn.result

                if turn.is_done and turn.result is not None:
                    st.session_state["design_result"] = turn.result
                    st.session_state["alchemy_db"]    = turn.result.alchemy_db
                    st.session_state["pending_result"] = None
                    st.balloons()

            except Exception as exc:
                st.session_state["design_messages"].append(
                    {"role": "assistant", "content": f"⚠️ **Error:** {exc}"}
                )

        st.rerun()

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 2 — Single-Line Diagram                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

with tab_diagram:
    st.markdown("### Single-Line Diagram")

    if not st.session_state.get("alchemy_db"):
        st.info(
            "Complete a design in **💬 Design Chat** or load a saved file from the sidebar."
        )
    else:
        ctl_col, diag_col = st.columns([1, 4])

        with ctl_col:
            st.markdown("**Display**")
            blueprint = st.toggle("Blueprint style", value=False, key="diag_blueprint")
            st.markdown("**Export**")
            fmt       = st.selectbox("Format", ["PDF", "SVG", "PNG"],
                                     key="diag_fmt", label_visibility="collapsed")
            do_export = st.button("⬇️  Download", use_container_width=True, type="secondary")

            # Requirements badge legend (if any generated)
            req_entries = [
                (n, st.session_state["req_data"].get(n, {}))
                for n, _, _ in _design_nodes()
                if (st.session_state["req_data"].get(n) or {}).get("result")
            ]
            if req_entries:
                st.divider()
                st.markdown("**Requirements**")
                for n, rd in req_entries:
                    app = len(rd["result"].get("applicable_requirements", []))
                    tbd = sum(1 for r in rd["result"].get("applicable_requirements", [])
                              if r.get("tbd_parameters"))
                    colour = "#b36c00" if tbd else "#3ddc84"
                    text   = f"{app} req" + (f"s · {tbd} TBD" if tbd else "s ✓")
                    st.markdown(
                        f'<span style="color:{colour};font-size:0.85em">'
                        f'<b>{n}</b>: {text}</span>',
                        unsafe_allow_html=True,
                    )

        # Build req_info for badge overlay
        req_info: dict[str, Any] = {
            n: {
                "applicable": len((rd.get("result") or {}).get("applicable_requirements", [])),
                "tbd": sum(1 for r in (rd.get("result") or {}).get("applicable_requirements", [])
                           if r.get("tbd_parameters")),
                "generated": bool(rd.get("result")),
            }
            for n, _, _ in _design_nodes()
            for rd in [st.session_state["req_data"].get(n) or {}]
        }

        with diag_col:
            with st.spinner("Rendering diagram…"):
                try:
                    import matplotlib
                    matplotlib.use("Agg")
                    from nucsys_agent.visualization.sld import SingleLineDiagram

                    design_result = st.session_state.get("design_result")
                    sld = (
                        SingleLineDiagram.from_agent_result(
                            design_result, req_info=req_info or None, blueprint=blueprint
                        )
                        if design_result is not None
                        else SingleLineDiagram(
                            st.session_state["alchemy_db"],
                            req_info=req_info or None,
                            blueprint=blueprint,
                        )
                    )
                    fig = sld.draw()

                    # Render to an explicit PNG buffer so that the figure's
                    # facecolor (dark blue for blueprint mode) is preserved.
                    # st.pyplot() calls savefig() without facecolor=, which
                    # falls back to rcParams['savefig.facecolor'] (usually
                    # 'white'), wiping the dark background in blueprint mode.
                    import io as _io
                    _buf = _io.BytesIO()
                    fig.savefig(
                        _buf, format="png", dpi=150,
                        bbox_inches="tight",
                        facecolor=fig.get_facecolor(),
                    )
                    _buf.seek(0)
                    st.image(_buf, use_container_width=True)
                    import matplotlib.pyplot as _mplt
                    _mplt.close(fig)   # prevent figure accumulation across reruns

                    if do_export:
                        suffix = fmt.lower()
                        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
                            tmp_path = tmp.name
                        sld.export(tmp_path)
                        with open(tmp_path, "rb") as fh:
                            st.download_button(
                                label=f"Save {fmt}",
                                data=fh.read(),
                                file_name=f"nuclear_design.{suffix}",
                                mime=(
                                    "application/pdf"   if suffix == "pdf"
                                    else "image/svg+xml" if suffix == "svg"
                                    else "image/png"
                                ),
                                key="diag_dl_btn",
                            )
                        os.unlink(tmp_path)

                except ImportError:
                    st.warning(
                        "**matplotlib not installed.**  "
                        "Run: `pip install nucsys-agent[diagram]`"
                    )
                except Exception as exc:
                    st.error(f"Diagram error: {exc}")
                    import traceback
                    st.code(traceback.format_exc())

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 3 — Component Requirements                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

with tab_reqs:
    st.markdown("### Component Requirements")
    st.caption(
        "Numeric parameters (flow, pressure, power) are pre-filled from the design. "
        "Supply the classification fields and click **Generate Requirements**."
    )

    if not st.session_state.get("alchemy_db"):
        st.info(
            "Complete a design in **💬 Design Chat** or load a saved file from the sidebar."
        )
    else:
        nodes     = _design_nodes()
        all_props = _all_node_props()

        if not nodes:
            st.warning(
                "No components with requirements baselines were found.  "
                "Supported types: pump, valve, condenser, steam_generator, pressurizer, turbine."
            )
        else:
            done_count = sum(
                1 for n, _, _ in nodes
                if (st.session_state["req_data"].get(n) or {}).get("result")
            )
            st.markdown(
                f"**{len(nodes)} component(s)** with baselines — "
                f"requirements generated for **{done_count}**."
            )
            st.divider()

            for node_name, comp_key, node_props in nodes:
                result = (st.session_state["req_data"].get(node_name) or {}).get("result")
                if result:
                    n_app = len(result.get("applicable_requirements", []))
                    n_tbd = sum(1 for r in result.get("applicable_requirements", [])
                                if r.get("tbd_parameters"))
                    badge = f"✅ {n_app} req" + (f"s · ⚠ {n_tbd} TBD" if n_tbd else "s")
                else:
                    badge = "— not generated yet"

                with st.expander(
                    f"**{node_name}** `{comp_key.replace('_', ' ')}` — {badge}",
                    expanded=(result is None),
                ):
                    _render_req_panel(node_name, comp_key, node_props, all_props)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 4 — Model Audit                                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

with tab_audit:
    st.markdown("### Model Audit")
    st.caption(
        "Ask free-text questions about every correlation, equation, assumption, "
        "and literature reference used in the sizing calculations.  "
        "No design needed — the audit module is always available."
    )

    # Render audit conversation
    for msg in st.session_state["audit_messages"]:
        with st.chat_message(msg["role"], avatar="🔍" if msg["role"] == "assistant" else None):
            if msg["role"] == "assistant":
                _render_audit_message(msg["content"])
            else:
                st.markdown(msg["content"])

    # Starter hint when empty
    if not st.session_state["audit_messages"]:
        with st.chat_message("assistant", avatar="🔍"):
            st.markdown(
                "Ask me anything about the engineering models.  Examples:\n\n"
                "- *How is energy conservation done?*\n"
                "- *What fluid properties are implemented and from where?*\n"
                "- *How is the steam generator sized?*\n"
                "- *What are the model assumptions?*\n"
                "- *What references are used?*\n\n"
                "Type **`list`** to see all available topics."
            )

    audit_prompt = st.chat_input(
        placeholder="Ask about a model, correlation, or reference…",
        key="audit_input",
    )

    if audit_prompt:
        st.session_state["audit_messages"].append(
            {"role": "user", "content": audit_prompt}
        )
        try:
            from nucsys_agent.audit import AuditEngine
            engine = AuditEngine()
            answer = engine.ask(audit_prompt)
        except Exception as exc:
            answer = f"⚠️ Audit error: {exc}"

        st.session_state["audit_messages"].append(
            {"role": "assistant", "content": answer}
        )
        st.rerun()
