from __future__ import annotations
from pydantic import BaseModel, Field, ValidationError
from typing import Any

class TopologyNodeDef(BaseModel):
    name: str
    canonical_type: str

class TopologyBuildingDef(BaseModel):
    name: str
    nodes: list[TopologyNodeDef]
    edges: list[list[str]]  # [[src_name, dst_name], ...]

class TopologyTemplateDef(BaseModel):
    buildings: list[TopologyBuildingDef]

class PatternCardDef(BaseModel):
    id: str
    title: str
    tags: list[str] = Field(default_factory=list)
    purpose: str
    required_inputs: list[str] = Field(default_factory=list)
    topology_template: TopologyTemplateDef | None = None
    sizing_methods: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    serialization_hints: dict[str, Any] = Field(default_factory=dict)

def validate_card_dict(d: dict[str, Any]) -> PatternCardDef:
    try:
        return PatternCardDef.model_validate(d)
    except ValidationError as e:
        raise ValueError(f"Invalid pattern card YAML: {e}") from e
