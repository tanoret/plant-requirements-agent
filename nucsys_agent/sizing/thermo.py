from __future__ import annotations
import math
from dataclasses import dataclass
from .properties import get_liquid_props

@dataclass
class PrimaryLoopSizingResult:
    m_dot_kg_s: float
    cp_J_kgK: float
    rho_kg_m3: float

def primary_mass_flow_from_Q_and_deltaT(
    Q_MWth: float,
    deltaT_K: float,
    *,
    coolant: str = "water",
    pressure_MPa: float = 15.5,
    hot_leg_C: float = 320.0,
) -> PrimaryLoopSizingResult:
    """Mass flow from Q = m_dot * cp * deltaT, with cp from property library."""
    props = get_liquid_props(coolant, pressure_MPa, hot_leg_C - 0.5 * deltaT_K)
    Q_W = Q_MWth * 1e6
    m_dot = Q_W / (props.cp_J_kgK * deltaT_K)
    return PrimaryLoopSizingResult(m_dot_kg_s=float(m_dot), cp_J_kgK=props.cp_J_kgK, rho_kg_m3=props.rho_kg_m3)

def lmtd(Th_in: float, Th_out: float, Tc_in: float, Tc_out: float) -> float:
    dT1 = Th_in - Tc_out
    dT2 = Th_out - Tc_in
    if dT1 <= 0 or dT2 <= 0:
        return float("nan")
    if abs(dT1 - dT2) < 1e-9:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)

def UA_from_Q_and_LMTD(Q_MW: float, LMTD_K: float) -> float:
    Q_W = Q_MW * 1e6
    return Q_W / LMTD_K  # W/K

def area_from_UA(UA_W_per_K: float, U_W_per_m2K: float = 3000.0) -> float:
    return UA_W_per_K / U_W_per_m2K
