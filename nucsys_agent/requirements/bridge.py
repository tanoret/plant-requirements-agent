"""
Bridge between the loop-design pipeline and the requirements module.

After ``run_agent()`` produces a sized ``AgentResult``, this module maps
each Alchemy node's engineering parameters to the optional numeric fields
expected by the requirements conversation, so users do not have to re-enter
values that are already known from the design.

Public API
----------
extract_design_numerics(node_name, node_props, all_node_props=None)
    -> (component_key | None, partial_numeric_profile)

list_design_components(agent_result)
    -> list of selectable component dicts  {"node_name", "component_key",
                                            "summary", "node_props"}
"""
from __future__ import annotations

_G = 9.81  # m/s² — for pump head conversion

# ---------------------------------------------------------------------------
# Node → requirements component mapping
# ---------------------------------------------------------------------------

# Maps Alchemy graph node names to requirements component keys.
# Only nodes that have a requirements baseline are listed.
NODE_TO_COMPONENT: dict[str, str] = {
    "Primary Sink": "pump",           # Reactor Coolant Pump
    "SG":           "steam_generator",
    "FWP":          "pump",           # Feedwater Pump
    "Turbine":      "turbine",
}


# ---------------------------------------------------------------------------
# Numeric field extraction
# ---------------------------------------------------------------------------

def extract_design_numerics(
    node_name: str,
    node_props: dict,
    all_node_props: dict[str, dict] | None = None,
) -> tuple[str | None, dict]:
    """Extract requirements-profile numeric fields from a sized Alchemy node.

    Only fills *optional* numeric fields (design_pressure, design_flowrate,
    rated_power, …).  Required classification fields (code_class,
    safety_classification, seismic_category, component type, tag) are always
    left for user input — they represent engineering judgement that cannot be
    inferred from sizing alone.

    Parameters
    ----------
    node_name : str
        Name of the node in the Alchemy graph (e.g. "Primary Sink", "SG").
    node_props : dict
        Properties dict from the sized node (``node.properties``).
    all_node_props : dict[str, dict] | None
        Full {name: properties} map for the design.  Used to look up
        cross-node values (e.g. hot-leg temperature from "Primary Source").

    Returns
    -------
    (component_key, partial_numeric_profile)
        Returns (None, {}) for nodes with no requirements mapping.
    """
    component_key = NODE_TO_COMPONENT.get(node_name)
    if component_key is None:
        return None, {}

    numerics: dict = {}
    ds        = node_props.get("design_summary", {})
    all_props = all_node_props or {}

    if component_key == "pump":
        # --- Flow rate [kg/s] ---
        m_dot = node_props.get("m_dot_kg_s")
        if m_dot is not None:
            numerics["design_flowrate"] = round(float(m_dot), 2)

        # --- Hydraulic head [m] from pump ΔP and fluid density ---
        delta_p = node_props.get("delta_p_MPa")
        rho     = node_props.get("rho_kg_m3")
        if delta_p is not None and rho and float(rho) > 0:
            head_m = float(delta_p) * 1e6 / (float(rho) * _G)
            numerics["design_head"] = round(head_m, 1)

        # --- Rated shaft power [kW] ---
        shaft_mw = node_props.get("shaft_power_MW")
        if shaft_mw is not None:
            numerics["rated_power"] = round(float(shaft_mw) * 1000.0, 1)

        # --- Design pressure [MPa] — use primary system operating pressure.
        # NOTE: actual design pressure = operating pressure × ~1.1–1.25 per
        # ASME III NB-3000.  This value is a conservative lower bound. ---
        p_op = ds.get("primary_pressure_MPa")
        if p_op is not None:
            numerics["design_pressure"] = round(float(p_op), 2)

        # --- Design temperature [°C] from Primary Source hot-leg ---
        src = all_props.get("Primary Source", {})
        t_hot = src.get("hot_leg_C")
        if t_hot is not None:
            numerics["design_temperature"] = round(float(t_hot), 1)

    elif component_key == "steam_generator":
        # --- Rated thermal duty [MW] ---
        duty = node_props.get("duty_MW")
        if duty is not None:
            numerics["thermal_duty_rated"] = round(float(duty), 1)

        # --- Primary design pressure [MPa] (operating pressure) ---
        p_pri = ds.get("primary_pressure_MPa")
        if p_pri is not None:
            numerics["design_pressure_primary"] = round(float(p_pri), 2)

        # --- Secondary design pressure [MPa] ---
        p_sec = (node_props.get("secondary_pressure_MPa")
                 or ds.get("secondary_pressure_MPa"))
        if p_sec is not None:
            numerics["design_pressure_secondary"] = round(float(p_sec), 2)

    elif component_key == "turbine":
        # --- Rated gross electrical power [MW] ---
        power = node_props.get("gross_power_MWe")
        if power is not None:
            numerics["rated_power_mw"] = round(float(power), 1)

    return component_key, numerics


# ---------------------------------------------------------------------------
# Convenience helpers for CLI / server
# ---------------------------------------------------------------------------

def list_design_components_from_db(alchemy_db: dict) -> list[dict]:
    """Return all sized nodes with a requirements mapping from a raw alchemy JSON dict.

    This is the file-load counterpart of :func:`list_design_components`.
    The alchemy JSON is a flat mapping ``{building_name: {"parts": [...], ...}}``.
    """
    all_props = all_node_props_from_db(alchemy_db)
    items = []
    for node_name, props in all_props.items():
        comp_key, numerics = extract_design_numerics(node_name, props, all_props)
        if comp_key is None:
            continue
        items.append({
            "node_name":     node_name,
            "component_key": comp_key,
            "summary":       _format_node_summary(node_name, comp_key, numerics),
            "node_props":    props,
        })
    return items


def all_node_props_from_db(alchemy_db: dict) -> dict[str, dict]:
    """Extract a flat ``{node_name: properties}`` map from a raw alchemy JSON dict."""
    return {
        part["name"]: part.get("properties", {})
        for building in alchemy_db.values()
        if isinstance(building, dict)
        for part in building.get("parts", [])
    }


def list_design_components(agent_result) -> list[dict]:
    """Return all sized nodes that have a requirements mapping.

    Parameters
    ----------
    agent_result : AgentResult
        Result from ``run_agent()``.

    Returns
    -------
    list[dict]
        Each entry has keys:
          ``node_name``      — Alchemy node name, e.g. "Primary Sink"
          ``component_key``  — requirements key, e.g. "pump"
          ``summary``        — one-line human-readable description
          ``node_props``     — raw node properties dict
    """
    all_props: dict[str, dict] = {
        n.name: n.properties
        for b in agent_result.buildings.values()
        for n in b.parts
    }
    items = []
    for node_name, props in all_props.items():
        comp_key, numerics = extract_design_numerics(node_name, props, all_props)
        if comp_key is None:
            continue
        items.append({
            "node_name":      node_name,
            "component_key":  comp_key,
            "summary":        _format_node_summary(node_name, comp_key, numerics),
            "node_props":     props,
        })
    return items


def _format_node_summary(node_name: str, comp_key: str, numerics: dict) -> str:
    """One-line summary of a designed component and its key sizing parameters."""
    _LABELS: dict[str, str] = {
        "design_flowrate":           "flow={:.0f} kg/s",
        "design_head":               "head={:.0f} m",
        "rated_power":               "P_shaft={:.0f} kW",
        "design_pressure":           "P_sys={:.1f} MPa",
        "design_temperature":        "T={:.0f} °C",
        "thermal_duty_rated":        "Q={:.0f} MW",
        "design_pressure_primary":   "P_pri={:.1f} MPa",
        "design_pressure_secondary": "P_sec={:.1f} MPa",
        "rated_power_mw":            "P={:.0f} MW",
    }
    parts = [f"{node_name} ({comp_key.replace('_', ' ')})"]
    for field, fmt in _LABELS.items():
        if field in numerics:
            parts.append(fmt.format(numerics[field]))
    return "  ".join(parts)
