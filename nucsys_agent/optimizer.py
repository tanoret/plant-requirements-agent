from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .sizing.thermo import primary_mass_flow_from_Q_and_deltaT, lmtd, UA_from_Q_and_LMTD
from .sizing.hydraulics import size_primary_pump
from .sizing.properties import get_liquid_props

@dataclass
class OptResult:
    primary_deltaT_K: float
    m_dot_kg_s: float
    pump_power_MW: float
    UA_MW_per_K: float
    score: float

def sweep_primary_deltaT(
    Q_MWth: float,
    Th_hot_C: float,
    secondary_in_C: float,
    secondary_out_C: float,
    coolant: str,
    primary_pressure_MPa: float,
    w_pump: float,
    w_UA: float,
    deltaT_grid: np.ndarray | None = None,
    min_pinch_K: float = 10.0,
) -> OptResult:
    if deltaT_grid is None:
        deltaT_grid = np.linspace(20.0, 60.0, 21)

    best: OptResult | None = None
    for dT in deltaT_grid:
        Th_in = Th_hot_C
        Th_out = Th_hot_C - float(dT)

        if (Th_out - secondary_out_C) < min_pinch_K:
            continue

        mres = primary_mass_flow_from_Q_and_deltaT(
            Q_MWth, float(dT),
            coolant=coolant,
            pressure_MPa=primary_pressure_MPa,
            hot_leg_C=Th_hot_C,
        )
        pump = size_primary_pump(
            mres.m_dot_kg_s,
            rho_kg_m3=mres.rho_kg_m3,
            efficiency=0.83,
        )

        L = lmtd(Th_in, Th_out, secondary_in_C, secondary_out_C)
        if not np.isfinite(L) or L <= 0:
            continue

        UA_W_per_K = UA_from_Q_and_LMTD(Q_MWth, L)
        UA_MW_per_K = UA_W_per_K / 1e6

        score = w_pump * pump.shaft_power_MW + w_UA * UA_W_per_K
        cand = OptResult(
            primary_deltaT_K=float(dT),
            m_dot_kg_s=float(mres.m_dot_kg_s),
            pump_power_MW=float(pump.shaft_power_MW),
            UA_MW_per_K=float(UA_MW_per_K),
            score=float(score),
        )
        if best is None or cand.score < best.score:
            best = cand

    if best is None:
        raise RuntimeError("No feasible design found in sweep.")
    return best
