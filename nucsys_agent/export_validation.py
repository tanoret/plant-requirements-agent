from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import json
import importlib.resources as pkg_resources

@dataclass
class ExportIssue:
    level: str  # "error" | "warning"
    message: str

def validate_alchemy_export(db: dict[str, Any]) -> list[ExportIssue]:
    """Validate exported JSON against an embedded JSON Schema.

    Uses jsonschema if installed; otherwise performs a minimal structural check.
    """
    issues: list[ExportIssue] = []
    try:
        import jsonschema  # type: ignore
    except Exception:
        # Minimal validation fallback
        if not isinstance(db, dict) or not db:
            return [ExportIssue("error", "Export must be a non-empty dict of buildings.")]
        for bname, b in db.items():
            if not isinstance(b, dict) or "parts" not in b:
                issues.append(ExportIssue("error", f"Building '{bname}' missing 'parts'."))
        return issues

    schema_text = pkg_resources.files("nucsys_agent").joinpath("schemas/alchemy_export.schema.json").read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    try:
        jsonschema.validate(instance=db, schema=schema)
    except jsonschema.ValidationError as e:  # type: ignore
        issues.append(ExportIssue("error", f"Alchemy export schema validation failed: {e.message}"))
    return issues
