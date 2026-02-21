"""
Loader utilities for component requirements baselines and schemas.
"""
from __future__ import annotations

import json
import importlib.resources as pkg_resources

# ---------------------------------------------------------------------------
# Component alias table  (user text → canonical key)
# ---------------------------------------------------------------------------

COMPONENT_KEYS: list[str] = [
    "pump",
    "valve",
    "condenser",
    "steam_generator",
    "pressurizer",
    "turbine",
]

_ALIASES: dict[str, str] = {
    # pump
    "pump": "pump",
    "pumps": "pump",
    "rcp": "pump",
    "feedwater pump": "pump",
    "fw pump": "pump",
    "fwp": "pump",
    # valve
    "valve": "valve",
    "valves": "valve",
    "tav": "valve",
    "fwcv": "valve",
    "mov": "valve",
    "aov": "valve",
    # condenser
    "condenser": "condenser",
    "main condenser": "condenser",
    "heat exchanger": "condenser",
    # steam generator
    "steam generator": "steam_generator",
    "steam_generator": "steam_generator",
    "sg": "steam_generator",
    "steam gen": "steam_generator",
    # pressurizer
    "pressurizer": "pressurizer",
    "prz": "pressurizer",
    "przr": "pressurizer",
    # turbine
    "turbine": "turbine",
    "turbines": "turbine",
    "main turbine": "turbine",
    "hp turbine": "turbine",
    "lp turbine": "turbine",
}


def resolve_component(text: str) -> str | None:
    """Return canonical component key if any alias is found in *text*, else None.

    Longer aliases are checked first to avoid partial matches (e.g. 'steam generator'
    before 'steam').
    """
    tl = text.lower()
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in tl:
            return _ALIASES[alias]
    return None


# ---------------------------------------------------------------------------
# File loaders  (use package resources so they work when installed)
# ---------------------------------------------------------------------------

def _load_json_resource(relpath: str) -> dict:
    text = (
        pkg_resources.files("nucsys_agent")
        .joinpath(relpath)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def load_baseline(component_key: str) -> dict:
    """Load the baseline requirements library for a component."""
    return _load_json_resource(
        f"data/component_requirements/{component_key}_baseline.json"
    )


def load_profile_schema(component_key: str) -> dict:
    """Load the JSON Schema that validates a component profile."""
    return _load_json_resource(
        f"data/component_schema/{component_key}_profile.schema.json"
    )


def load_instance_schema(component_key: str) -> dict:
    """Load the JSON Schema that validates a requirements instance output."""
    return _load_json_resource(
        f"data/component_schema/{component_key}_requirements_instance.schema.json"
    )
