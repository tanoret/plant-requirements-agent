from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
import importlib.resources as pkg_resources
from .models import ComponentType

@dataclass(frozen=True)
class Ontology:
    by_canonical: dict[str, ComponentType]

    def require(self, canonical_type: str) -> ComponentType:
        if canonical_type not in self.by_canonical:
            raise KeyError(f"Unknown component canonical_type: {canonical_type}")
        return self.by_canonical[canonical_type]

def _read_text_maybe_resource(path: str | None, resource_relpath: str) -> str:
    if path:
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
    return pkg_resources.files("nucsys_agent").joinpath(resource_relpath).read_text(encoding="utf-8")

def load_ontology(path: str | None = None) -> Ontology:
    text = _read_text_maybe_resource(path, "data/ontology.yaml")
    data = yaml.safe_load(text)
    items: dict[str, ComponentType] = {}
    for obj in data.get("components", []):
        ct = ComponentType(**obj)
        items[ct.canonical_type] = ct
    return Ontology(by_canonical=items)
