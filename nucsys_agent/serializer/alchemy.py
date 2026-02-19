from __future__ import annotations
from typing import Any
import orjson
from ..models import Node, Building

def node_to_part(n: Node) -> dict[str, Any]:
    return {
        "id": n.id,
        "name": n.name,
        "description": "",
        "length": 0,
        "width": 0,
        "height": 0,
        "capacity": 0,
        "class": "",
        "predefined_type": "",
        "preset_element_type": n.preset_element_type,
        "properties": n.properties,
        "edgesIncoming": n.edgesIncoming or [],
        "edgesOutgoing": n.edgesOutgoing or [],
    }

def export_alchemy_db(buildings: dict[str, Building]) -> dict[str, Any]:
    return {
        bname: {
            "length": b.length,
            "width": b.width,
            "height": b.height,
            "parts": [node_to_part(n) for n in b.parts],
        }
        for bname, b in buildings.items()
    }

def dumps(db: dict[str, Any]) -> bytes:
    return orjson.dumps(db, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
