"""
Simulation / what-if service: run a batch of labelled test cases through
compute_price and report per-case pass/fail plus aggregate accuracy. This
is what backs the "pricing correctness" KPI - deterministic, reproducible,
no network or wall-clock dependency unless a case supplies an explicit
as_of date.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .evaluator import compute_price
from .schema import DomainConfig


def run_simulation(config: DomainConfig, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    results = []
    passed = 0
    for i, case in enumerate(cases):
        context = case.get("context", {})
        expected = case.get("expected_price")
        as_of = None
        if case.get("as_of"):
            as_of = datetime.strptime(case["as_of"], "%Y-%m-%d").date()
        try:
            result = compute_price(config, context, as_of=as_of)
            actual = round(result.final_price, 2)
            ok = expected is None or abs(actual - round(float(expected), 2)) < 0.01
            if ok:
                passed += 1
            results.append({
                "case_index": i,
                "case_name": case.get("name", f"case_{i}"),
                "expected_price": expected,
                "actual_price": actual,
                "pass": ok,
                "explanation": result.to_dict(),
            })
        except Exception as e:
            results.append({
                "case_index": i,
                "case_name": case.get("name", f"case_{i}"),
                "expected_price": expected,
                "actual_price": None,
                "pass": False,
                "error": str(e),
            })
    total = len(cases)
    return {
        "domain": config.domain,
        "config_version": config.version,
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy_pct": round(100.0 * passed / total, 2) if total else 0.0,
        "results": results,
    }
