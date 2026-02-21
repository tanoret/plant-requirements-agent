from __future__ import annotations
import re
from typing import Any
from .models import DesignSpec

_POWER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(MWth|MWt|MW_?th|MW)", re.IGNORECASE)
_MPA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MPa", re.IGNORECASE)
_TEMP_C_RE = re.compile(r"(\d+(?:\.\d+)?)\s*°?C", re.IGNORECASE)

def parse_design_spec(query: str, *, llm: Any | None = None) -> DesignSpec:
    spec = DesignSpec(request_text=query)
    ql = query.lower()

    m = _POWER_RE.search(query)
    if m:
        spec.thermal_power_MWth = float(m.group(1))

    if "primary" in ql and ("coolant" in ql or "loop" in ql):
        spec.system = "primary_loop"
    elif "balance of plant" in ql or "bop" in ql or "rankine" in ql:
        spec.system = "bop_loop"

    if "sodium" in ql:
        spec.coolant = "sodium"
    elif "water" in ql or "pwr" in ql or "steam generator" in ql:
        spec.coolant = "water"

    if "minimize pumping" in ql or "min pump" in ql:
        spec.objective = "min_pump_power"
    elif "minimize ua" in ql or "min ua" in ql:
        spec.objective = "min_UA"
    elif "baseline" in ql:
        spec.objective = "baseline"

    # heuristic: first MPa might be primary pressure if "primary" mentioned; otherwise secondary
    mpas = [float(x) for x in _MPA_RE.findall(query)]
    if mpas:
        if "primary" in ql:
            spec.primary_pressure_MPa = mpas[0]
        elif "secondary" in ql or "steam" in ql:
            spec.secondary_pressure_MPa = mpas[0]

    temps = [float(x) for x in _TEMP_C_RE.findall(query)]
    # If provided, interpret first as hot leg, second as steam temp, third as feedwater, etc (best-effort)
    if temps:
        spec.primary_hot_leg_C = temps[0]
    if len(temps) >= 2:
        spec.secondary_steam_C = temps[1]
    if len(temps) >= 3:
        spec.secondary_feedwater_C = temps[2]

    if llm is not None:
        try:
            out = llm.chat_json(
                [
                    {"role": "system", "content": "Extract structured design specs from user text. Output JSON only."},
                    {"role": "user", "content": (
                        "Return JSON with keys: system, thermal_power_MWth, coolant, objective, "
                        "primary_pressure_MPa, primary_hot_leg_C, primary_deltaT_K, "
                        "secondary_pressure_MPa, condenser_pressure_MPa, secondary_feedwater_C, secondary_steam_C."
                    )},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
            )
            # Merge only provided values
            for k in out:
                if hasattr(spec, k) and out[k] is not None:
                    setattr(spec, k, out[k])
        except Exception:
            pass

    return spec
