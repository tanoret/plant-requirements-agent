from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Literal

Coolant = Literal["water", "sodium", "co2", "helium", "unknown"]

@dataclass
class ThermoProps:
    cp_J_kgK: float
    rho_kg_m3: float
    h_kJ_kg: float | None = None
    s_kJ_kgK: float | None = None

def water_props_IAPWS(P_MPa: float, T_C: float) -> ThermoProps:
    """Return cp/rho/h/s for pressurized water using IAPWS97.

    Requires `iapws` package.
    """
    from iapws import IAPWS97  # type: ignore
    st = IAPWS97(P=P_MPa, T=T_C + 273.15)
    # IAPWS returns cp [kJ/kg-K], rho [kg/m3], h [kJ/kg], s [kJ/kg-K]
    return ThermoProps(
        cp_J_kgK=float(st.cp) * 1000.0,
        rho_kg_m3=float(st.rho),
        h_kJ_kg=float(st.h),
        s_kJ_kgK=float(st.s),
    )

def get_liquid_props(coolant: str, P_MPa: float, T_C: float) -> ThermoProps:
    coolant = coolant.lower()
    if coolant == "water":
        try:
            return water_props_IAPWS(P_MPa, T_C)
        except Exception:
            # Fallback (rough)
            return ThermoProps(cp_J_kgK=4200.0, rho_kg_m3=950.0)
    if coolant == "sodium":
        # Rough correlations near ~500K; refine later with validated correlations
        cp = 1270.0
        rho = 850.0
        return ThermoProps(cp_J_kgK=cp, rho_kg_m3=rho)
    if coolant in ("co2", "helium"):
        # Placeholder
        return ThermoProps(cp_J_kgK=2000.0, rho_kg_m3=50.0)
    return ThermoProps(cp_J_kgK=2000.0, rho_kg_m3=1000.0)
