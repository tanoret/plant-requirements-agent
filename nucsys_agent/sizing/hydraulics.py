from __future__ import annotations
import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Friction factor — Churchill (1977) explicit formula
# ---------------------------------------------------------------------------

def _churchill_friction_factor(Re: float, roughness_m: float, diameter_m: float) -> float:
    """Darcy-Weisbach friction factor via Churchill (1977) explicit correlation.

    Valid for all flow regimes (laminar, transition, turbulent) and all
    roughness values.  Maximum error vs Moody chart: < 1 %.

    Reference: Churchill, S. W. (1977), "Friction-factor equation spans all
    fluid-flow regimes", Chemical Engineering, 84(24), 91–92.
    """
    if Re < 1.0:
        return 64.0  # degenerate laminar (very low Re)

    eps_D = roughness_m / max(diameter_m, 1e-9)

    A = (-2.457 * math.log((7.0 / Re)**0.9 + 0.27 * eps_D))**16
    B = (37530.0 / Re)**16

    f = 8.0 * ((8.0 / Re)**12 + (A + B)**(-1.5))**(1.0 / 12.0)
    return f


# ---------------------------------------------------------------------------
# Pipe pressure drop (Darcy-Weisbach)
# ---------------------------------------------------------------------------

def pipe_pressure_drop_Pa(
    m_dot_kg_s: float,
    rho_kg_m3: float,
    mu_Pa_s: float,
    *,
    diameter_m: float,
    length_m: float,
    roughness_m: float = 4.57e-5,   # commercial steel (ASME B36.10 tolerance)
    K_minor: float = 0.0,
) -> float:
    """Pressure drop [Pa] for a pipe segment using Darcy-Weisbach.

    Parameters
    ----------
    m_dot_kg_s : float
        Mass flow rate, kg/s.
    rho_kg_m3 : float
        Fluid density, kg/m³.
    mu_Pa_s : float
        Dynamic viscosity, Pa·s.
    diameter_m : float
        Pipe inner diameter, m.
    length_m : float
        Pipe equivalent length, m  (includes straight runs).
    roughness_m : float
        Absolute roughness of pipe wall, m.
    K_minor : float
        Sum of minor-loss coefficients (bends, reducers, orifices, etc.).

    Returns
    -------
    float
        Pressure drop, Pa.
    """
    A_m2  = math.pi * diameter_m**2 / 4.0
    V_m_s = m_dot_kg_s / (rho_kg_m3 * A_m2)
    Re    = rho_kg_m3 * V_m_s * diameter_m / max(mu_Pa_s, 1e-12)

    f     = _churchill_friction_factor(Re, roughness_m, diameter_m)
    q_dyn = 0.5 * rho_kg_m3 * V_m_s**2   # dynamic pressure [Pa]

    return (f * length_m / diameter_m + K_minor) * q_dyn


# ---------------------------------------------------------------------------
# Coolant-specific default geometry for primary-loop piping
# ---------------------------------------------------------------------------

# Each entry: (pipe_id_m, pipe_length_m, roughness_m, K_fittings, K_vessel)
#
# Pipe inner diameter (D):
#   PWR water: 29-in schedule (ID ≈ 0.736 m) to 34-in ID ≈ 0.864 m; use 0.76 m.
#   SFR sodium: smaller pipes (lower volumetric flow at higher ρ); 0.45 m typical.
#   Gas-cooled (He/CO2): smaller diameter, but higher velocity; 0.30–0.40 m.
#
# Equivalent pipe length (L_eq):
#   Includes straight sections of hot leg, cold leg, and cross-over leg
#   within one primary loop.  Multi-loop plants are sized per loop.
#   PWR: ~50 m/loop; SFR: ~30 m/loop; HTGR: ~20 m/loop.
#
# K_vessel: dimensionless pressure-loss coefficient for reactor vessel
#   (lower head, core, upper head, nozzles).
#   PWR: ~3.0–4.0 (from core flow tests, e.g. Todreas & Kazimi).
#   SFR: ~3.5 (core with wire-wrapped fuel pins, higher form drag).
#   HTGR: ~2.5 (pebble bed / prismatic with bypass flow).
#
# K_fittings: sum of minor-loss coefficients for all elbows, tees, valves
#   in one primary loop (excl. reactor vessel and SG/IHX shell side).
#   Typical: 8–15 (3–4 long-radius elbows at K≈0.3 + isolation valve, etc.)

_LOOP_GEOMETRY: dict[str, dict] = {
    "water": dict(
        pipe_id_m=0.762,        # 30-in ID (approximate for large PWR)
        pipe_length_m=50.0,     # hot + cold leg equivalent length per loop
        roughness_m=4.57e-5,    # commercial steel
        K_fittings=10.0,
        K_vessel=3.5,
    ),
    "sodium": dict(
        pipe_id_m=0.450,
        pipe_length_m=30.0,
        roughness_m=4.57e-5,
        K_fittings=8.0,
        K_vessel=3.8,
    ),
    "co2": dict(
        pipe_id_m=0.350,
        pipe_length_m=20.0,
        roughness_m=1.5e-5,     # internally coated / smooth tube
        K_fittings=6.0,
        # Prismatic VHTR / sCO2 turbine core: higher form loss than liquid loops.
        # Target core ΔP ≈ 0.1 MPa at typical sCO2 operating conditions.
        # K_vessel sized to reproduce ~0.1 MPa at target velocity; this is
        # equivalent to ~0.5 % of system pressure at 20 MPa — representative
        # of closed Brayton cycle recuperated layout (IHX + turbomachinery).
        K_vessel=25.0,
    ),
    "helium": dict(
        pipe_id_m=0.300,
        pipe_length_m=20.0,
        roughness_m=1.5e-5,
        K_fittings=6.0,
        # Pebble-bed HTGR core: dominant ΔP from interstitial flow (Ergun equation).
        # PBMR-400 data: core ΔP ≈ 0.035–0.05 MPa at 7–9 MPa system pressure;
        # circulator power ≈ 2–3 % of Q_th.
        # K_vessel = 200 reproduces ~0.04 MPa at ρ=3.5 kg/m³, V=12 m/s.
        K_vessel=200.0,
    ),
}

# Representative dynamic viscosity fallback [Pa·s] if caller does not supply one.
# Used to compute Reynolds number inside size_primary_pump.
# Values: approximate bulk-temperature averages for normal operating conditions.
_MU_FALLBACK: dict[str, float] = {
    "water":  8.5e-5,    # ~300 °C pressurised water
    "sodium": 1.0e-3,    # ~500 °C liquid sodium
    "co2":    3.5e-5,    # ~450 °C supercritical CO2 at 20 MPa
    "helium": 3.5e-5,    # ~650 °C helium at 7 MPa
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def pump_power_MW(
    m_dot_kg_s: float,
    delta_p_MPa: float,
    *,
    rho_kg_m3: float,
    efficiency: float,
) -> float:
    """Pump hydraulic shaft power [MW].

    P = (m_dot / rho) × ΔP / η
    """
    deltaP_Pa  = delta_p_MPa * 1e6
    vol_flow   = m_dot_kg_s / max(rho_kg_m3, 1e-9)
    P_W        = vol_flow * deltaP_Pa / max(efficiency, 1e-6)
    return P_W / 1e6


@dataclass
class PumpSizingResult:
    delta_p_MPa: float
    efficiency: float
    shaft_power_MW: float


# Target pipe velocity [m/s] used when pipe_id_m is not supplied.
# Pipes are sized so that the bulk average velocity equals this target,
# which is standard engineering practice for primary-loop piping.
# Typical ranges:
#   Water  (PWR primary):  3–6 m/s
#   Sodium (SFR primary):  3–5 m/s
#   CO2    (sCO2 Brayton): 5–12 m/s
#   Helium (HTGR):         8–15 m/s
_TARGET_VELOCITY: dict[str, float] = {
    "water":  5.0,
    "sodium": 4.0,
    "co2":    8.0,
    "helium": 12.0,
}


def size_primary_pump(
    m_dot_kg_s: float,
    *,
    rho_kg_m3: float = 750.0,
    efficiency: float = 0.85,
    mu_Pa_s: float | None = None,
    coolant: str = "water",
    # Optional geometry overrides (None → auto-calculated or coolant defaults)
    pipe_id_m: float | None = None,
    pipe_length_m: float | None = None,
    roughness_m: float | None = None,
    K_fittings: float | None = None,
    K_vessel: float | None = None,
) -> PumpSizingResult:
    """Size the primary coolant pump using a physics-based Darcy-Weisbach model.

    The total primary-loop pressure drop is decomposed into:
      1. Piping legs   — Darcy-Weisbach with Churchill friction factor
      2. Fittings      — sum of minor losses (elbows, valves, reducers)
      3. Reactor vessel / core — a lumped form-loss coefficient K_vessel

    Pipe diameter is auto-sized for a coolant-appropriate target velocity
    when ``pipe_id_m`` is not supplied, so the model scales correctly with
    plant size without requiring knowledge of the number of primary loops.

    Parameters
    ----------
    m_dot_kg_s : float
        Total primary coolant mass flow rate (all loops combined), kg/s.
    rho_kg_m3 : float
        Bulk density of primary coolant, kg/m³.
    efficiency : float
        Pump isentropic (hydraulic) efficiency, dimensionless (0–1).
    mu_Pa_s : float | None
        Dynamic viscosity, Pa·s.  If None, a representative value for the
        coolant is used (sufficient for the turbulent-regime friction factor).
    coolant : str
        Coolant key ("water", "sodium", "co2", "helium") for geometry defaults.
    pipe_id_m : float | None
        Pipe inner diameter, m.  If None, sized for ``_TARGET_VELOCITY[coolant]``.
    pipe_length_m, roughness_m, K_fittings, K_vessel : float | None
        Override individual geometry parameters.  None → use coolant default.

    Returns
    -------
    PumpSizingResult
        delta_p_MPa, efficiency, shaft_power_MW.
    """
    geo  = _LOOP_GEOMETRY.get(coolant.lower(), _LOOP_GEOMETRY["water"])
    mu   = mu_Pa_s if mu_Pa_s is not None else _MU_FALLBACK.get(coolant.lower(), 1e-4)

    # Auto-size pipe diameter from target velocity if not specified
    if pipe_id_m is not None:
        D = pipe_id_m
    else:
        target_V = _TARGET_VELOCITY.get(coolant.lower(), 5.0)
        A_req = m_dot_kg_s / (rho_kg_m3 * target_V)
        D = math.sqrt(4.0 * A_req / math.pi)

    L    = pipe_length_m if pipe_length_m is not None else geo["pipe_length_m"]
    eps  = roughness_m   if roughness_m   is not None else geo["roughness_m"]
    K_f  = K_fittings    if K_fittings    is not None else geo["K_fittings"]
    K_v  = K_vessel      if K_vessel      is not None else geo["K_vessel"]

    # Pipe + fittings pressure drop
    A_m2    = math.pi * D**2 / 4.0
    V_m_s   = m_dot_kg_s / (rho_kg_m3 * A_m2)
    Re      = rho_kg_m3 * V_m_s * D / max(mu, 1e-12)
    f       = _churchill_friction_factor(Re, eps, D)
    q_dyn   = 0.5 * rho_kg_m3 * V_m_s**2

    dP_pipe     = (f * L / D + K_f) * q_dyn    # Pa
    dP_vessel   = K_v * q_dyn                   # Pa  (vessel/core based on bulk velocity)
    dP_total_Pa = dP_pipe + dP_vessel

    dP_MPa  = dP_total_Pa / 1e6
    P_shaft = pump_power_MW(m_dot_kg_s, dP_MPa, rho_kg_m3=rho_kg_m3, efficiency=efficiency)

    return PumpSizingResult(
        delta_p_MPa=float(dP_MPa),
        efficiency=float(efficiency),
        shaft_power_MW=float(P_shaft),
    )
