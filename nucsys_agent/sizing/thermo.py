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
    """Mass flow from Q = m_dot · cp · ΔT with cp evaluated at bulk temperature."""
    props = get_liquid_props(coolant, pressure_MPa, hot_leg_C - 0.5 * deltaT_K)
    Q_W = Q_MWth * 1e6
    m_dot = Q_W / (props.cp_J_kgK * deltaT_K)
    return PrimaryLoopSizingResult(
        m_dot_kg_s=float(m_dot),
        cp_J_kgK=props.cp_J_kgK,
        rho_kg_m3=props.rho_kg_m3,
    )


# ---------------------------------------------------------------------------
# LMTD
# ---------------------------------------------------------------------------

def lmtd(Th_in: float, Th_out: float, Tc_in: float, Tc_out: float) -> float:
    """Counter-flow log mean temperature difference [K].

    For a pure counter-flow arrangement (most nuclear SG designs).
    Apply an F-correction factor via ``lmtd_corrected`` for multi-pass
    or cross-flow arrangements.
    """
    dT1 = Th_in - Tc_out
    dT2 = Th_out - Tc_in
    if dT1 <= 0 or dT2 <= 0:
        return float("nan")
    if abs(dT1 - dT2) < 1e-9:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)


def lmtd_corrected(
    Th_in: float,
    Th_out: float,
    Tc_in: float,
    Tc_out: float,
    F: float = 1.0,
) -> float:
    """LMTD × F — effective mean driving force for shell-and-tube HX.

    Parameters
    ----------
    F : float
        LMTD correction factor (0 < F ≤ 1.0).
        F = 1.0 for pure counter-flow (U-tube SG, helical-coil SG).
        F ≈ 0.95 for 1-shell / 2-tube-pass arrangements.
        F ≈ 0.85–0.90 for 2-shell / 4-tube-pass.
        Computed from Bowman–Mueller–Nagle charts or NTU-ε method.
    """
    return lmtd(Th_in, Th_out, Tc_in, Tc_out) * F


# ---------------------------------------------------------------------------
# Overall heat-transfer coefficient (U)
# ---------------------------------------------------------------------------

# Representative single-phase convective film coefficients [W/(m²·K)].
# Basis:
#   Water (PWR primary, Re ~ 5×10⁵–10⁶, turbulent in tube bundle):
#       Dittus-Boelter at typical conditions gives h ~ 20 000–50 000 W/m²K.
#       Conservative mid-range: 30 000 W/m²K.
#   Sodium (SFR, liquid metal, high k ~ 70 W/mK):
#       Seban-Shimazaki (Nu = 5.0 + 0.025 Pe^0.8) → h ~ 60 000–120 000 W/m²K.
#       Conservative mid-range: 80 000 W/m²K.
#   CO2 (sCO2, 20 MPa, 400°C, moderate Re):
#       Gnielinski correlation → h ~ 2 000–8 000 W/m²K.
#       Conservative: 4 000 W/m²K.
#   Helium (HTGR, 7 MPa, 700°C, high Re but low k and ρ):
#       Dittus-Boelter → h ~ 600–1 500 W/m²K.
#       Conservative: 800 W/m²K.
#   Secondary (steam/boiling): nucleate boiling or convective boiling
#       h ~ 10 000–40 000 W/m²K; conservative: 15 000 W/m²K.
_H_PRIMARY = {
    "water":  30_000.0,   # W/(m²·K)
    "sodium": 80_000.0,
    "co2":     4_000.0,
    "helium":    800.0,
}
_H_SECONDARY = 15_000.0   # steam/water secondary side [W/(m²·K)]

# TEMA fouling resistances [m²·K/W] for nuclear-grade systems.
# Lower than commercial industry: plant chemistry is tightly controlled.
_RFOUL_PRIMARY = {
    "water":  2.0e-5,   # PWR primary; TEMA R2
    "sodium": 5.0e-6,   # liquid metal — very clean
    "co2":    1.0e-5,
    "helium": 1.0e-5,
}
_RFOUL_SECONDARY = 1.0e-5   # steam-side fouling


def U_overall_W_m2K(
    coolant_primary: str,
    *,
    t_wall_m: float = 2.0e-3,          # tube wall thickness [m]
    k_wall_W_mK: float = 16.0,         # Inconel / SS-316 tube wall [W/(m·K)]
) -> float:
    """Overall heat-transfer coefficient U for primary-to-secondary HX [W/(m²·K)].

    Uses a series thermal-resistance network:
        1/U = 1/h_primary + R_f_primary + t_wall/k_wall + R_f_secondary + 1/h_secondary

    The thin-wall approximation (A_inner ≈ A_outer) is applied, which is
    valid for t_wall / D_tube < 0.1 (standard tube sizes).

    Parameters
    ----------
    coolant_primary : str
        Primary loop coolant ("water", "sodium", "co2", "helium").
    t_wall_m : float
        Tube wall thickness, m.  Default: 2 mm (typical HX tube).
    k_wall_W_mK : float
        Tube material thermal conductivity, W/(m·K).
        Default: 16.0 (SS-316 / Inconel-600 mid-range).

    Returns
    -------
    float
        Overall U, W/(m²·K).
    """
    key = coolant_primary.lower()
    h_p  = _H_PRIMARY.get(key, 10_000.0)
    Rf_p = _RFOUL_PRIMARY.get(key, 2.0e-5)

    R_total = (1.0 / h_p
               + Rf_p
               + t_wall_m / k_wall_W_mK
               + _RFOUL_SECONDARY
               + 1.0 / _H_SECONDARY)
    return 1.0 / R_total


# ---------------------------------------------------------------------------
# UA and heat-exchanger area
# ---------------------------------------------------------------------------

def UA_from_Q_and_LMTD(Q_MW: float, LMTD_K: float) -> float:
    """UA product [W/K] from duty and effective LMTD."""
    return (Q_MW * 1e6) / LMTD_K


def area_from_UA(
    UA_W_per_K: float,
    U_W_per_m2K: float | None = None,
    *,
    coolant: str = "water",
) -> float:
    """Heat-exchanger surface area [m²] from UA product.

    Parameters
    ----------
    UA_W_per_K : float
        Required UA product, W/K.
    U_W_per_m2K : float | None
        If supplied, this value is used directly (backward-compatible override).
        If None, U is computed from ``U_overall_W_m2K(coolant)``.
    coolant : str
        Primary coolant key; used only when ``U_W_per_m2K`` is None.
    """
    if U_W_per_m2K is None:
        U_W_per_m2K = U_overall_W_m2K(coolant)
    return UA_W_per_K / U_W_per_m2K
