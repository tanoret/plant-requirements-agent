"""
Filters a baseline requirements library by a component profile and produces
a requirements_instance dict conforming to the instance schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .applicability import is_applicable


def _exclusion_reason(when: list[str], profile: dict) -> str:
    """Build a human-readable string explaining why a requirement was excluded."""
    reasons: list[str] = []
    for cond in when:
        cond = cond.strip()
        if cond == "always":
            continue
        if "=" in cond and ">" not in cond:
            key, rhs = cond.split("=", 1)
            key = key.strip()
            allowed = [v.strip() for v in rhs.split("|")]
            val = profile.get(key, "(not set)")
            if str(val) not in set(allowed):
                reasons.append(
                    f"{key}={val!r} not in required set [{', '.join(allowed)}]"
                )
        elif ">" in cond:
            parts = cond.split("|")
            sub_reasons: list[str] = []
            for part in parts:
                part = part.strip()
                if ">" not in part:
                    continue
                key, thresh = part.split(">", 1)
                key = key.strip()
                val = profile.get(key)
                if val is None or float(val) <= float(thresh.strip()):
                    sub_reasons.append(f"{key} not > {thresh.strip()}")
            if sub_reasons:
                reasons.append(" and ".join(sub_reasons))
    return "; ".join(reasons) if reasons else "condition not met"


def _parameter_values(req_text: str, profile: dict) -> dict:
    """Return profile fields whose name appears in the requirement text, with their values."""
    result = {}
    for key, val in profile.items():
        if val is not None and key in req_text:
            result[key] = val
    return result


def filter_requirements(
    baseline: dict,
    profile: dict,
    component_key: str,
) -> dict:
    """Filter baseline requirements by profile applicability conditions.

    Returns a requirements_instance dict with:
    - applicable_requirements
    - non_applicable_requirements
    - validation summary
    """
    applicable: list[dict] = []
    non_applicable: list[dict] = []

    for req_set in baseline.get("requirement_sets", []):
        for req in req_set.get("requirements", []):
            when: list[str] = req.get("applicability", {}).get("when", ["always"])
            ok, tbd = is_applicable(when, profile)

            base = {
                "id": req["id"],
                "text": req["text"],
                "type": req.get("type", ""),
                "verification": req.get("verification", {"method": [], "acceptance": ""}),
                "provenance_refs": req.get("provenance_refs", []),
            }

            if ok:
                applicable.append({
                    **base,
                    "status": "applicable",
                    "parameter_values": _parameter_values(req["text"], profile),
                    "tbd_parameters": tbd,
                })
            else:
                non_applicable.append({
                    **base,
                    "exclusion_reason": _exclusion_reason(when, profile),
                })

    # Build validation block
    tbd_all = sorted({p for r in applicable for p in r["tbd_parameters"]})
    issues: list[dict] = []
    for field in tbd_all:
        issues.append({
            "severity": "warning",
            "code": "TBD_PARAMETER",
            "message": f"Parameter '{field}' not specified — requirements that depend on it are included conservatively.",
        })

    # Profile key in output uses component_key (e.g. pump_profile, steam_generator_profile)
    profile_key = f"{component_key}_profile"

    return {
        "instance_id": str(uuid.uuid4()),
        "template_id": baseline.get("template_id", ""),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        profile_key: profile,
        "applicable_requirements": applicable,
        "non_applicable_requirements": non_applicable,
        "validation": {
            "overall_status": "pass",
            "error_count": 0,
            "warning_count": len(issues),
            "info_count": 0,
            "issue_count": len(issues),
            "issues": issues,
        },
    }
