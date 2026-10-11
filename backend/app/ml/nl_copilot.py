"""
Natural-language-to-configuration copilot.

Deliberately a transparent, regex/heuristic parser rather than a live LLM
call: it keeps the demo fully offline/deterministic and makes the mapping
from English to the rule DSL auditable line-by-line. The output contract
(a draft Rule dict + confidence + warnings) is exactly what a real LLM-
backed implementation would need to produce too, so swapping this module
for an Anthropic API call later is a drop-in replacement, not a redesign.

Supported phrasing (case-insensitive), combinable with "and":
  "increase/add/raise price by 20% when occupancy_rate >= 0.8"
  "decrease/discount/reduce price by 10% if customer_segment is vip"
  "add a flat $5 surcharge when driver_supply_count < 3"
  "give a flat $5 discount/credit when rider_segment is first_ride_promo"
  comparisons: is/equals/==, is above/over/greater than/>, is below/under/less than/<,
               at least/>=, at most/<=, is not/!=
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_NUM = r"(-?\d+(?:\.\d+)?)"

_DIRECTION_WORDS = {
    "increase": 1, "raise": 1, "add": 1, "surcharge": 1, "markup": 1, "premium": 1,
    "decrease": -1, "discount": -1, "reduce": -1, "lower": -1, "cut": -1, "credit": -1,
}

_COMPARATORS = [
    (r"is not equal to|is not|!=|not equal to", "!="),
    (r"at least|>=|greater than or equal to", ">="),
    (r"at most|<=|less than or equal to", "<="),
    (r"above|over|greater than|more than|>", ">"),
    (r"below|under|less than|<", "<"),
    (r"is|equals|==|=", "=="),
]


def _coerce_value(raw: str) -> Any:
    raw = raw.strip().strip("'\"")
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _parse_clause(clause: str) -> Optional[Dict[str, Any]]:
    clause = clause.strip()
    for pattern, op in _COMPARATORS:
        m = re.search(rf"^(?P<attr>[\w.]+)\s+(?:{pattern})\s+(?P<value>.+)$", clause, re.IGNORECASE)
        if m:
            return {"attr": m.group("attr").strip(), "op": op, "value": _coerce_value(m.group("value"))}
    return None


def _parse_condition(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\b(?:when|if)\b(.+)$", text, re.IGNORECASE)
    if not m:
        return None
    clauses_text = m.group(1)
    clauses_text = re.split(r"\b(?:unless|otherwise)\b", clauses_text, flags=re.IGNORECASE)[0]
    raw_clauses = re.split(r"\band\b", clauses_text, flags=re.IGNORECASE)
    parsed = [c for c in (_parse_clause(c) for c in raw_clauses) if c]
    if not parsed:
        return None
    if len(parsed) == 1:
        return parsed[0]
    return {"all": parsed}


def parse_nl_rule(text: str, known_attributes: Optional[List[str]] = None) -> Dict[str, Any]:
    warnings: List[str] = []
    lower = text.lower()

    direction = 0
    for word, sign in _DIRECTION_WORDS.items():
        if word in lower:
            direction = sign
            break
    if direction == 0:
        warnings.append("Could not determine whether this increases or decreases price; defaulted to increase.")
        direction = 1

    adjustment: Dict[str, Any]
    pct_match = re.search(rf"{_NUM}\s*%", text)
    flat_match = re.search(rf"flat\s*(?:fee of\s*)?\$?{_NUM}|\${_NUM}\s*(?:flat|credit|discount|surcharge)?", lower)
    if pct_match:
        value = abs(float(pct_match.group(1))) * direction
        adjustment = {"type": "percent", "value": value}
    elif flat_match:
        raw = next(g for g in flat_match.groups() if g is not None)
        value = abs(float(raw)) * direction
        adjustment = {"type": "add", "value": value}
    else:
        warnings.append("No percentage or flat dollar amount found; defaulting to +10%.")
        adjustment = {"type": "percent", "value": 10.0 * direction}

    condition = _parse_condition(text)
    if condition is None:
        warnings.append("No 'when'/'if' clause found; rule will always apply (condition: always true). Review before activating.")
        condition = {"always": True}

    if known_attributes:
        known_lower = {a.lower(): a for a in known_attributes}
        for leaf in ([condition] if "attr" in condition else condition.get("all", [])):
            if "attr" in leaf and leaf["attr"].lower() not in known_lower:
                warnings.append(f"Attribute '{leaf['attr']}' is not defined in this domain's config - add it or fix the name.")
            elif "attr" in leaf:
                leaf["attr"] = known_lower[leaf["attr"].lower()]

    suggested_id = re.sub(r"[^a-z0-9]+", "_", lower).strip("_")[:50] or "nl_generated_rule"

    confidence = 1.0
    if not pct_match and not flat_match:
        confidence -= 0.4
    if condition.get("always"):
        confidence -= 0.3
    if warnings and "not defined" in " ".join(warnings):
        confidence -= 0.3
    confidence = max(0.1, round(confidence, 2))

    rule = {
        "id": suggested_id,
        "description": text.strip(),
        "priority": 100,
        "enabled": True,
        "condition": condition,
        "adjustment": adjustment,
        "tags": ["nl-generated"],
    }
    return {"rule": rule, "confidence": confidence, "warnings": warnings, "source_text": text}
