"""
Evaluates the `applicability.when` condition arrays from baseline requirement sets.

Condition format (from data analysis):
  ["always"]                               → always applicable
  ["code_class=ASME_III_Class_1|2|3"]      → enum match, pipe = OR in value list
  ["safety_classification=safety_related",
   "seismic_category=Seismic_Category_I"]  → AND across array elements
  ["design_cycles>0|design_life_years>0"]  → numeric OR (pipe between sub-conditions)

Null-handling policy (conservative / engineering-safe):
  If a profile field is None and a numeric condition references it (e.g. design_cycles>0),
  the requirement is INCLUDED and the parameter is added to tbd_parameters.
  This ensures no requirement is silently dropped just because a parameter hasn't been
  specified yet — the caller can surface the TBDs to the user.
"""
from __future__ import annotations


def evaluate_condition(cond: str, profile: dict) -> tuple[bool, list[str]]:
    """Evaluate a single condition string against a profile dict.

    Returns (is_applicable, tbd_parameters).
    tbd_parameters lists field names that are referenced but have None values
    (conservative: requirement is included, field marked as TBD).
    """
    cond = cond.strip()

    if cond == "always":
        return True, []

    # Enum condition: "field=val1|val2|val3"
    # Has '=' and pipe separates allowed values on the RHS.
    if "=" in cond and ">" not in cond:
        key, rhs = cond.split("=", 1)
        key = key.strip()
        allowed = {v.strip() for v in rhs.split("|")}
        val = profile.get(key)
        if val is None:
            return False, []
        return str(val) in allowed, []

    # Numeric condition(s): "field>threshold" or "field1>0|field2>0" (OR between parts)
    if ">" in cond:
        parts = cond.split("|")
        any_true = False
        tbd: list[str] = []
        for part in parts:
            part = part.strip()
            if ">" not in part:
                continue
            key, thresh_str = part.split(">", 1)
            key = key.strip()
            val = profile.get(key)
            if val is None:
                # Conservative: treat as TBD, count as applicable for this OR branch
                tbd.append(key)
                any_true = True
            else:
                try:
                    if float(val) > float(thresh_str.strip()):
                        any_true = True
                except (ValueError, TypeError):
                    pass
        return any_true, tbd

    # Unknown format — conservative: include
    return True, []


def is_applicable(when: list[str], profile: dict) -> tuple[bool, list[str]]:
    """AND of all conditions in the `when` array.

    Returns (applicable, all_tbd_params).
    If any condition returns False the requirement is not applicable (tbd list empty).
    """
    all_tbd: list[str] = []
    for cond in when:
        applicable, tbd = evaluate_condition(cond, profile)
        if not applicable:
            return False, []
        all_tbd.extend(tbd)
    return True, list(dict.fromkeys(all_tbd))  # deduplicate, preserve order
