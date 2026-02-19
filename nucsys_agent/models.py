from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Literal

class DesignSpec(BaseModel):
    request_text: str
    system: Literal["primary_loop", "bop_loop", "intermediate_loop", "unknown"] = "unknown"
    thermal_power_MWth: float | None = None
    coolant: Literal["water", "sodium", "co2", "helium", "unknown"] = "unknown"
    objective: Literal["baseline", "min_pump_power", "min_UA", "balanced"] = "balanced"

    # Primary conditions (optional)
    primary_pressure_MPa: float | None = None
    primary_hot_leg_C: float | None = None
    primary_deltaT_K: float | None = None

    # Secondary / Rankine conditions (optional)
    secondary_pressure_MPa: float | None = None
    condenser_pressure_MPa: float | None = None
    secondary_feedwater_C: float | None = None
    secondary_steam_C: float | None = None

class PatternCard(BaseModel):
    id: str
    title: str
    tags: list[str] = Field(default_factory=list)
    purpose: str
    required_inputs: list[str] = Field(default_factory=list)
    topology_template: dict[str, Any] | None = None
    sizing_methods: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    serialization_hints: dict[str, Any] | None = None

class ComponentType(BaseModel):
    canonical_type: str
    alchemy_preset_element_type: str
    required_ports: list[str] = Field(default_factory=list)
    required_properties: list[str] = Field(default_factory=list)
    description: str = ""

class Node(BaseModel):
    id: str
    name: str
    canonical_type: str
    preset_element_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    edgesIncoming: list[str] = Field(default_factory=list)
    edgesOutgoing: list[str] = Field(default_factory=list)

class Building(BaseModel):
    length: float = 0
    width: float = 0
    height: float = 0
    parts: list[Node] = Field(default_factory=list)

class AlchemyDB(BaseModel):
    buildings: dict[str, Building]
