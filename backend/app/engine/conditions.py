"""
Domain-agnostic condition DSL.

A condition is a JSON tree, e.g.:
  {"all": [
      {"attr": "occupancy_rate", "op": ">=", "value": 0.8},
      {"any": [
          {"attr": "day_type", "op": "==", "value": "weekend"},
          {"attr": "day_type", "op": "==", "value": "holiday"}
      ]}
  ]}

Supported ops: ==, !=, >, >=, <, <=, in, not_in, between, contains, exists
A bare {} (empty dict) or {"always": true} always matches - used for
default / catch-all rules.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "between": lambda a, b: a is not None and b[0] <= a <= b[1],
    "contains": lambda a, b: b in a if a is not None else False,
    "exists": lambda a, b: a is not None,
}


class ConditionError(ValueError):
    pass


def evaluate(condition: Dict[str, Any] | None, context: Dict[str, Any]) -> bool:
    if not condition or condition.get("always") is True:
        return True
    if "all" in condition:
        return all(evaluate(c, context) for c in condition["all"])
    if "any" in condition:
        return any(evaluate(c, context) for c in condition["any"])
    if "not" in condition:
        return not evaluate(condition["not"], context)
    if "attr" in condition:
        op = condition.get("op", "==")
        if op not in _OPS:
            raise ConditionError(f"Unsupported operator '{op}'")
        actual = context.get(condition["attr"])
        return _OPS[op](actual, condition.get("value"))
    raise ConditionError(f"Malformed condition node: {condition}")


def leaf_equalities(condition: Dict[str, Any] | None) -> List[Tuple[str, Any]]:
    """Collect (attr, value) pairs for every '==' leaf reachable through
    'all' nesting only. Used by the conflict detector's disjointness
    heuristic - 'any'/'not' branches are treated conservatively as unknown.
    """
    out: List[Tuple[str, Any]] = []
    if not condition:
        return out
    if "all" in condition:
        for c in condition["all"]:
            out.extend(leaf_equalities(c))
    elif "attr" in condition and condition.get("op", "==") == "==":
        out.append((condition["attr"], condition.get("value")))
    return out


def conditions_provably_disjoint(c1: Dict[str, Any] | None, c2: Dict[str, Any] | None) -> bool:
    """Best-effort static check: True only if we can PROVE the two
    conditions can never both be true (same attribute constrained to two
    different literal values via '==' inside 'all' blocks). Anything we
    can't prove disjoint is treated as possibly overlapping - conservative
    in the direction of flagging more potential conflicts, not fewer.
    """
    eq1 = dict(leaf_equalities(c1))
    eq2 = dict(leaf_equalities(c2))
    for attr, v1 in eq1.items():
        if attr in eq2 and eq2[attr] != v1:
            return True
    return False
