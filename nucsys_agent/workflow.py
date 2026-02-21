from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import itertools
import logging

from .config import AgentConfig
from .ontology import load_ontology
from .rag.store import CardStore
from .llm import make_llm_client
from .spec_parser import parse_design_spec
from .models import Node, Building, DesignSpec
from .optimizer import sweep_primary_deltaT
from .sizing.hydraulics import size_primary_pump
from .sizing.thermo import lmtd, UA_from_Q_and_LMTD, area_from_UA, primary_mass_flow_from_Q_and_deltaT
from .sizing.rankine import rankine_simple
from .sizing.properties import get_liquid_props
from .validator import validate_nodes, ValidationIssue
from .serializer.alchemy import export_alchemy_db
from .export_validation import validate_alchemy_export
from .exceptions import CardError, SpecError, SizingError

log = logging.getLogger(__name__)

@dataclass
class AgentResult:
    spec: DesignSpec
    buildings: dict[str, Building]
    validation_issues: list[ValidationIssue]
    export_issues: list[Any]
    alchemy_db: dict[str, Any]

class IdGen:
    def __init__(self, start: int = 1):
        self._n = start
    def next(self) -> str:
        s = str(self._n)
        self._n += 1
        return s

def _instantiate_topology(topo_template: dict[str, Any], ontology, idgen: IdGen) -> dict[str, Building]:
    buildings: dict[str, Building] = {}
    for idx, b in enumerate(topo_template["buildings"], start=1):
        bname = "Building" if idx == 1 else f"Building {idx}"
        building = Building()

        # Create nodes
        for node in b["nodes"]:
            n_id = idgen.next()
            ct = ontology.require(node["canonical_type"])
            building.parts.append(Node(
                id=n_id,
                name=node["name"],
                canonical_type=node["canonical_type"],
                preset_element_type=ct.alchemy_preset_element_type,
                properties={"canonical_type": node["canonical_type"]},
            ))

        # Add edges (within building)
        by_name = {n.name: n for n in building.parts}
        for src_name, dst_name in b["edges"]:
            if src_name not in by_name or dst_name not in by_name:
                raise CardError(f"Invalid edge [{src_name} -> {dst_name}] in building '{b.get('name','')}'. "
                                f"Ensure both nodes are declared in that building.")
            src = by_name[src_name]
            dst = by_name[dst_name]
            if dst.id not in src.edgesOutgoing:
                src.edgesOutgoing.append(dst.id)
            if src.id not in dst.edgesIncoming:
                dst.edgesIncoming.append(src.id)

        buildings[bname] = building
    return buildings

def _merge_interface_node(buildings: dict[str, Building], interface_name: str = "SG") -> None:
    found = []
    for bname, b in buildings.items():
        for n in b.parts:
            if n.name == interface_name:
                found.append((bname, n))
    if len(found) <= 1:
        return

    keep_bname, keep_node = found[-1]
    for bname, old in found[:-1]:
        for n in buildings[bname].parts:
            n.edgesIncoming = [keep_node.id if x == old.id else x for x in n.edgesIncoming]
            n.edgesOutgoing = [keep_node.id if x == old.id else x for x in n.edgesOutgoing]
        for inc in old.edgesIncoming:
            if inc not in keep_node.edgesIncoming:
                keep_node.edgesIncoming.append(inc)
        for out in old.edgesOutgoing:
            if out not in keep_node.edgesOutgoing:
                keep_node.edgesOutgoing.append(out)
        buildings[bname].parts = [n for n in buildings[bname].parts if n.id != old.id]

def _choose_topology_card(cards, spec: DesignSpec) -> Any:
    # Hard applicability: must include system tag (e.g., primary_loop)
    for c in cards:
        if c.topology_template and spec.system in c.tags:
            return c
    # fallback: any topology card
    for c in cards:
        if c.topology_template:
            log.warning("Falling back to topology card '%s' without strict tag match.", c.id)
            return c
    raise CardError("No topology card found for this request.")

def _apply_sizing(spec: DesignSpec, cfg: AgentConfig, buildings: dict[str, Building]) -> None:
    Q = spec.thermal_power_MWth
    if Q is None:
        raise SpecError("thermal_power_MWth is required (e.g., '300 MWth').")

    coolant = spec.coolant if spec.coolant != "unknown" else "water"

    primary_pressure = spec.primary_pressure_MPa or cfg.default_primary_pressure_MPa
    Th_hot = spec.primary_hot_leg_C or cfg.default_primary_hot_leg_C
    sec_in = spec.secondary_feedwater_C or cfg.default_secondary_feedwater_C
    sec_out = spec.secondary_steam_C or cfg.default_secondary_steam_C
    sec_P = spec.secondary_pressure_MPa or cfg.default_secondary_pressure_MPa
    cond_P = spec.condenser_pressure_MPa or cfg.default_condenser_pressure_MPa

    # Optimize deltaT unless baseline
    if spec.objective == "baseline":
        dT = spec.primary_deltaT_K or cfg.default_primary_deltaT_K
        mres = primary_mass_flow_from_Q_and_deltaT(
            Q, dT,
            coolant=coolant,
            pressure_MPa=primary_pressure,
            hot_leg_C=Th_hot,
        )
        props = get_liquid_props(coolant, primary_pressure, Th_hot - 0.5 * dT)
        pump = size_primary_pump(
            mres.m_dot_kg_s,
            rho_kg_m3=mres.rho_kg_m3,
            efficiency=cfg.default_pump_efficiency,
            mu_Pa_s=props.mu_Pa_s,
            coolant=coolant,
        )
        L = lmtd(Th_hot, Th_hot - dT, sec_in, sec_out)
        if not (L > 0):
            raise SizingError("Invalid LMTD for steam generator; check temperature assumptions.")
        UA_W_per_K = UA_from_Q_and_LMTD(Q, L)
        opt = dict(primary_deltaT_K=dT, m_dot_kg_s=mres.m_dot_kg_s, rho_kg_m3=mres.rho_kg_m3,
                   pump_power_MW=pump.shaft_power_MW, UA_W_per_K=UA_W_per_K)
    else:
        # Objective-specific weights
        w_pump = cfg.w_pump
        w_UA = cfg.w_UA
        if spec.objective == "min_pump_power":
            w_UA = 0.0
        elif spec.objective == "min_UA":
            w_pump = 0.0

        optres = sweep_primary_deltaT(
            Q_MWth=Q,
            Th_hot_C=Th_hot,
            secondary_in_C=sec_in,
            secondary_out_C=sec_out,
            coolant=coolant,
            primary_pressure_MPa=primary_pressure,
            w_pump=w_pump,
            w_UA=w_UA,
        )
        # recompute rho and mu with chosen deltaT
        mres = primary_mass_flow_from_Q_and_deltaT(
            Q, optres.primary_deltaT_K,
            coolant=coolant,
            pressure_MPa=primary_pressure,
            hot_leg_C=Th_hot,
        )
        props = get_liquid_props(coolant, primary_pressure, Th_hot - 0.5 * optres.primary_deltaT_K)
        pump = size_primary_pump(
            mres.m_dot_kg_s,
            rho_kg_m3=mres.rho_kg_m3,
            efficiency=cfg.default_pump_efficiency,
            mu_Pa_s=props.mu_Pa_s,
            coolant=coolant,
        )
        L = lmtd(Th_hot, Th_hot - optres.primary_deltaT_K, sec_in, sec_out)
        if not (L > 0):
            raise SizingError("Invalid LMTD for steam generator; check temperature assumptions.")
        UA_W_per_K = UA_from_Q_and_LMTD(Q, L)
        opt = dict(primary_deltaT_K=optres.primary_deltaT_K, m_dot_kg_s=mres.m_dot_kg_s, rho_kg_m3=mres.rho_kg_m3,
                   pump_power_MW=pump.shaft_power_MW, UA_W_per_K=UA_W_per_K)

    dT = float(opt["primary_deltaT_K"])
    Tc_cold = Th_hot - dT

    # Rankine closure (secondary flow + turbine & pump power)
    rank = rankine_simple(
        Q_in_MW=Q,
        P_boiler_MPa=sec_P,
        T_steam_C=sec_out,
        T_feedwater_C=sec_in,
        P_cond_MPa=cond_P,
        eta_turb=cfg.default_turbine_isentropic_efficiency,
        eta_pump=cfg.default_pump_efficiency,
    )

    # Apply to nodes
    all_nodes = list(itertools.chain.from_iterable(b.parts for b in buildings.values()))
    by_name = {n.name: n for n in all_nodes}

    if "Primary Source" in by_name:
        by_name["Primary Source"].properties.update({
            "thermal_power_MWth": Q,
            "primary_pressure_MPa": primary_pressure,
            "hot_leg_C": Th_hot,
            "cold_leg_C": Tc_cold,
            "coolant": coolant,
            "chosen_primary_deltaT_K": dT,
        })

    if "Primary Sink" in by_name:
        by_name["Primary Sink"].properties.update({
            "m_dot_kg_s": opt["m_dot_kg_s"],
            "delta_p_MPa": pump.delta_p_MPa,
            "efficiency": pump.efficiency,
            "shaft_power_MW": pump.shaft_power_MW,
            "rho_kg_m3": opt["rho_kg_m3"],
        })

    if "SG" in by_name:
        area = area_from_UA(float(opt["UA_W_per_K"]), coolant=coolant)
        by_name["SG"].properties.update({
            "duty_MW": Q,
            "UA_MW_per_K": float(opt["UA_W_per_K"]) / 1e6,
            "area_m2": float(area),
            "primary_hot_in_C": Th_hot,
            "primary_hot_out_C": Tc_cold,
            "secondary_pressure_MPa": sec_P,
            "secondary_cold_in_C": sec_in,
            "secondary_hot_out_C": sec_out,
            "secondary_m_dot_kg_s": rank.m_dot_kg_s,
        })

    if "FWP" in by_name:
        # Size feedwater pump from Rankine result
        by_name["FWP"].properties.update({
            "m_dot_kg_s": rank.m_dot_kg_s,
            "delta_p_MPa": max(sec_P - cond_P, 0.1),
            "efficiency": cfg.default_pump_efficiency,
            "shaft_power_MW": max(rank.pump_power_MWe, 0.0),
        })

    if "Turbine" in by_name:
        by_name["Turbine"].properties.update({
            "gross_power_MWe": rank.turbine_power_MWe,
            "net_power_MWe": rank.net_power_MWe,
            "isentropic_efficiency": cfg.default_turbine_isentropic_efficiency,
            "cycle_efficiency": rank.efficiency,
            "condenser_pressure_MPa": cond_P,
        })

    # Always include a design summary on every node for traceability
    for n in all_nodes:
        n.properties.setdefault("design_summary", {})
        n.properties["design_summary"].update({
            "Q_MWth": Q,
            "primary_deltaT_K": dT,
            "primary_pressure_MPa": primary_pressure,
            "secondary_pressure_MPa": sec_P,
            "condenser_pressure_MPa": cond_P,
        })

def _apply_node_overrides(buildings: dict[str, Building], node_overrides: dict[str, dict]) -> None:
    """Apply per-node property overrides on top of sizing results."""
    all_nodes = {n.name: n for b in buildings.values() for n in b.parts}
    for node_name, props in node_overrides.items():
        if node_name in all_nodes:
            all_nodes[node_name].properties.update(props)


def run_agent_from_spec(
    spec: DesignSpec,
    topology_template: dict[str, Any],
    topo_card: Any,
    cfg: AgentConfig | None = None,
    node_overrides: dict[str, dict] | None = None,
) -> AgentResult:
    """Run the design pipeline from a pre-built spec and (optionally pruned) topology.

    Called by interactive mode after Phase 2; run_agent() is untouched.
    """
    cfg = cfg or AgentConfig()
    ontology = load_ontology(cfg.ontology_path)

    idgen = IdGen(start=3)
    buildings = _instantiate_topology(topology_template, ontology, idgen)
    interface = (topo_card.serialization_hints or {}).get("interface_node", "SG")
    _merge_interface_node(buildings, interface_name=interface)

    _apply_sizing(spec, cfg, buildings)

    if node_overrides:
        _apply_node_overrides(buildings, node_overrides)

    all_nodes = [n for b in buildings.values() for n in b.parts]
    issues = validate_nodes(all_nodes, ontology)
    alchemy_db = export_alchemy_db(buildings)
    export_issues = validate_alchemy_export(alchemy_db)

    return AgentResult(
        spec=spec,
        buildings=buildings,
        validation_issues=issues,
        export_issues=export_issues,
        alchemy_db=alchemy_db,
    )


def run_agent(query: str, cfg: AgentConfig | None = None) -> AgentResult:
    cfg = cfg or AgentConfig()
    ontology = load_ontology(cfg.ontology_path)
    store = CardStore.load_from_dir(cfg.cards_dir)

    llm = make_llm_client(cfg)
    spec = parse_design_spec(query, llm=llm)

    tags = [spec.system, spec.coolant]
    cards = store.retrieve(query, tags=tags, k=8)
    topo_card = _choose_topology_card(cards, spec)

    # Ensure required inputs are present
    if "thermal_power_MWth" in topo_card.required_inputs and spec.thermal_power_MWth is None:
        raise SpecError("Request must include thermal power (e.g., '300 MWth').")

    idgen = IdGen(start=3)  # mimic demo IDs
    buildings = _instantiate_topology(topo_card.topology_template, ontology, idgen)
    _merge_interface_node(buildings, interface_name=topo_card.serialization_hints.get("interface_node", "SG"))

    _apply_sizing(spec, cfg, buildings)

    all_nodes = [n for b in buildings.values() for n in b.parts]
    issues = validate_nodes(all_nodes, ontology)

    alchemy_db = export_alchemy_db(buildings)

    export_issues = validate_alchemy_export(alchemy_db)

    return AgentResult(
        spec=spec,
        buildings=buildings,
        validation_issues=issues,
        export_issues=export_issues,
        alchemy_db=alchemy_db,
    )
