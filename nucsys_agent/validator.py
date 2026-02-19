from __future__ import annotations
from dataclasses import dataclass
from .models import Node
from .ontology import Ontology

@dataclass
class ValidationIssue:
    level: str  # "error" | "warning"
    message: str
    node_id: str | None = None

def validate_nodes(nodes: list[Node], ontology: Ontology) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_id = {n.id: n for n in nodes}

    for n in nodes:
        try:
            ct = ontology.require(n.canonical_type)
        except KeyError as e:
            issues.append(ValidationIssue("error", str(e), n.id))
            continue

        if n.preset_element_type != ct.alchemy_preset_element_type:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"preset_element_type mismatch: got {n.preset_element_type}, expected {ct.alchemy_preset_element_type}",
                    n.id,
                )
            )

        for req in ct.required_properties:
            if req not in n.properties:
                issues.append(ValidationIssue("warning", f"Missing required property '{req}'", n.id))

    # Edge symmetry and referential integrity
    for n in nodes:
        for dst in n.edgesOutgoing:
            if dst not in by_id:
                issues.append(ValidationIssue("error", f"Outgoing edge to missing id '{dst}'", n.id))
                continue
            if n.id not in by_id[dst].edgesIncoming:
                issues.append(ValidationIssue("error", f"Edge symmetry broken: {n.id} -> {dst}", n.id))
        for src in n.edgesIncoming:
            if src not in by_id:
                issues.append(ValidationIssue("error", f"Incoming edge from missing id '{src}'", n.id))
                continue
            if n.id not in by_id[src].edgesOutgoing:
                issues.append(ValidationIssue("error", f"Edge symmetry broken: {src} -> {n.id}", n.id))

    return issues
