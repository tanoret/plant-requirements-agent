from __future__ import annotations
from dataclasses import dataclass

def pump_power_MW(m_dot_kg_s: float, delta_p_MPa: float, *, rho_kg_m3: float, efficiency: float) -> float:
    """P = (m_dot/rho)*deltaP / eta."""
    deltaP_Pa = delta_p_MPa * 1e6
    vol_flow = m_dot_kg_s / max(rho_kg_m3, 1e-9)
    P_W = vol_flow * deltaP_Pa / max(efficiency, 1e-6)
    return P_W / 1e6

@dataclass
class PumpSizingResult:
    delta_p_MPa: float
    efficiency: float
    shaft_power_MW: float

def size_primary_pump(
    m_dot_kg_s: float,
    *,
    rho_kg_m3: float = 950.0,
    efficiency: float = 0.83,
    m_dot_ref: float = 2500.0,
) -> PumpSizingResult:
    """Very simple system curve model for demo; replace with real hydraulics later."""
    base = 0.6
    k = 0.6
    delta_p = base + k * (m_dot_kg_s / max(m_dot_ref, 1e-9)) ** 2
    P = pump_power_MW(m_dot_kg_s, delta_p, rho_kg_m3=rho_kg_m3, efficiency=efficiency)
    return PumpSizingResult(delta_p_MPa=float(delta_p), efficiency=float(efficiency), shaft_power_MW=float(P))
