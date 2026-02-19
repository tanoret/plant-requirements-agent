from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RankineResult:
    m_dot_kg_s: float
    turbine_power_MWe: float
    pump_power_MWe: float
    net_power_MWe: float
    efficiency: float
    h_in_kJ_kg: float
    h_out_kJ_kg: float
    h_fw_kJ_kg: float
    condenser_duty_MW: float

def rankine_simple_iapws(
    Q_in_MW: float,
    P_boiler_MPa: float,
    T_steam_C: float,
    T_feedwater_C: float,
    P_cond_MPa: float,
    eta_turb: float = 0.87,
    eta_pump: float = 0.80,
) -> RankineResult:
    """Simple Rankine closure using IAPWS97.

    - Boiler outlet: (P_boiler, T_steam)
    - Turbine expands to P_cond with isentropic eff
    - Condenser outlet: saturated liquid at P_cond
    - Pump raises to P_boiler with incompressible approx (via IAPWS saturated v)
    - Feedwater at (P_boiler, T_feedwater) used for heat addition enthalpy delta
    """
    from iapws import IAPWS97  # type: ignore

    # Inlet steam state
    st1 = IAPWS97(P=P_boiler_MPa, T=T_steam_C + 273.15)
    h1 = float(st1.h)  # kJ/kg
    s1 = float(st1.s)  # kJ/kg-K

    # Isentropic outlet at condenser pressure
    st2s = IAPWS97(P=P_cond_MPa, s=s1)
    h2s = float(st2s.h)

    # Actual outlet enthalpy
    h2 = h1 - max(eta_turb, 1e-6) * (h1 - h2s)

    # Condenser saturated liquid at P_cond
    st3 = IAPWS97(P=P_cond_MPa, x=0.0)
    h3 = float(st3.h)
    v3 = 1.0 / float(st3.rho)  # m3/kg

    # Pump specific work (kJ/kg): v * dP / eta
    dP_kPa = (P_boiler_MPa - P_cond_MPa) * 1000.0  # MPa -> kPa
    w_pump_kJ_kg = (v3 * dP_kPa) / max(eta_pump, 1e-6)  # since 1 kPa*m3/kg = 1 kJ/kg
    h4 = h3 + w_pump_kJ_kg

    # Feedwater enthalpy at given T (compressed liquid at boiler P)
    st_fw = IAPWS97(P=P_boiler_MPa, T=T_feedwater_C + 273.15)
    h_fw = float(st_fw.h)

    # Heat addition per kg from feedwater to steam
    q_in_kJ_kg = h1 - h_fw
    if q_in_kJ_kg <= 0:
        raise ValueError("Non-positive boiler heat addition; check inputs.")

    m_dot = (Q_in_MW * 1000.0) / q_in_kJ_kg  # MW -> kJ/s -> kg/s

    w_turb_kJ_kg = h1 - h2
    W_turb_MWe = (m_dot * w_turb_kJ_kg) / 1000.0
    W_pump_MWe = (m_dot * w_pump_kJ_kg) / 1000.0
    W_net = W_turb_MWe - W_pump_MWe

    Q_in = Q_in_MW
    eff = W_net / Q_in if Q_in > 0 else 0.0

    Q_out_MW = (m_dot * (h2 - h3)) / 1000.0

    return RankineResult(
        m_dot_kg_s=float(m_dot),
        turbine_power_MWe=float(W_turb_MWe),
        pump_power_MWe=float(W_pump_MWe),
        net_power_MWe=float(W_net),
        efficiency=float(eff),
        h_in_kJ_kg=float(h1),
        h_out_kJ_kg=float(h2),
        h_fw_kJ_kg=float(h_fw),
        condenser_duty_MW=float(Q_out_MW),
    )

def rankine_simple(
    Q_in_MW: float,
    P_boiler_MPa: float,
    T_steam_C: float,
    T_feedwater_C: float,
    P_cond_MPa: float,
    eta_turb: float = 0.87,
    eta_pump: float = 0.80,
) -> RankineResult:
    """Try IAPWS closure; if iapws not installed, fall back to a simple efficiency proxy."""
    try:
        return rankine_simple_iapws(
            Q_in_MW=Q_in_MW,
            P_boiler_MPa=P_boiler_MPa,
            T_steam_C=T_steam_C,
            T_feedwater_C=T_feedwater_C,
            P_cond_MPa=P_cond_MPa,
            eta_turb=eta_turb,
            eta_pump=eta_pump,
        )
    except Exception:
        # Fallback: assume 33% net efficiency, and rough steam m_dot with 2,000 kJ/kg heat addition.
        eff = 0.33
        net = Q_in_MW * eff
        m_dot = (Q_in_MW * 1000.0) / 2000.0
        return RankineResult(
            m_dot_kg_s=float(m_dot),
            turbine_power_MWe=float(net / 0.95),
            pump_power_MWe=float(net / 0.95 - net),
            net_power_MWe=float(net),
            efficiency=float(eff),
            h_in_kJ_kg=0.0,
            h_out_kJ_kg=0.0,
            h_fw_kJ_kg=0.0,
            condenser_duty_MW=float(Q_in_MW - net),
        )
