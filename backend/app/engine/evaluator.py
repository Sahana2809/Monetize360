"""
The deterministic rule- and strategy-evaluation engine.

Given a DomainConfig and a context dict (the real-time signals: demand,
supply/inventory, time, customer segment, competitor price, ...), this
module resolves the final price and produces a full price-driver
decomposition: which rules fired, in what order, what each one changed,
which rules were skipped and why, and which constraints clamped the result.

Nothing here knows about hotels, rides, or loans - every decision is driven
entirely by the DomainConfig passed in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from .conditions import conditions_provably_disjoint, evaluate
from .expr import safe_eval
from .schema import Adjustment, Constraint, DomainConfig, Rule
from ..ml.signals import apply_signals


class EngineError(ValueError):
    pass


@dataclass
class RuleTrace:
    id: str
    description: str
    priority: int
    adjustment_summary: str
    price_before: float
    price_after: float
    tags: List[str] = field(default_factory=list)


@dataclass
class SkippedRuleTrace:
    id: str
    reason: str


@dataclass
class ConstraintTrace:
    type: str
    detail: str
    price_before: float
    price_after: float


@dataclass
class Conflict:
    kind: str
    rule_ids: List[str]
    detail: str


@dataclass
class PricingResult:
    domain: str
    config_version: int
    base_price: float
    final_price: float
    currency: str
    applied_rules: List[RuleTrace]
    skipped_rules: List[SkippedRuleTrace]
    constraints_applied: List[ConstraintTrace]
    conflicts: List[Conflict]
    context_used: Dict[str, Any]
    signal_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "config_version": self.config_version,
            "currency": self.currency,
            "base_price": round(self.base_price, 2),
            "final_price": round(self.final_price, 2),
            "applied_rules": [vars(r) for r in self.applied_rules],
            "skipped_rules": [vars(r) for r in self.skipped_rules],
            "constraints_applied": [vars(c) for c in self.constraints_applied],
            "conflicts_detected": [vars(c) for c in self.conflicts],
            "signals": self.signal_trace,
            "context_used": self.context_used,
        }


def _resolve_base_price(config: DomainConfig, context: Dict[str, Any]) -> float:
    bp = config.base_price
    if bp.mode == "fixed":
        if bp.value is None:
            raise EngineError("base_price.mode == 'fixed' requires 'value'")
        return float(bp.value)
    if bp.mode == "attribute":
        if not bp.attribute:
            raise EngineError("base_price.mode == 'attribute' requires 'attribute'")
        if bp.attribute not in context:
            raise EngineError(f"Context is missing base price attribute '{bp.attribute}'")
        return float(context[bp.attribute])
    if bp.mode == "formula":
        if not bp.formula:
            raise EngineError("base_price.mode == 'formula' requires 'formula'")
        return safe_eval(bp.formula, context)
    raise EngineError(f"Unknown base_price.mode '{bp.mode}'")


def _rule_active_on(rule: Rule, as_of: date) -> bool:
    if rule.effective_from and as_of < rule.effective_from:
        return False
    if rule.effective_to and as_of > rule.effective_to:
        return False
    return True


def _apply_adjustment(price: float, adjustment: Adjustment, context: Dict[str, Any], base_price: float) -> tuple[float, str]:
    t = adjustment.type
    if t == "multiply":
        v = adjustment.value or 1.0
        return price * v, f"multiply x{v}"
    if t == "percent":
        v = adjustment.value or 0.0
        return price * (1 + v / 100.0), f"{'+' if v >= 0 else ''}{v}%"
    if t == "add":
        v = adjustment.value or 0.0
        return price + v, f"{'+' if v >= 0 else ''}{v} flat"
    if t == "set":
        v = adjustment.value or 0.0
        return v, f"set to {v}"
    if t == "formula":
        if not adjustment.formula:
            raise EngineError("adjustment.type == 'formula' requires 'formula'")
        ns = dict(context)
        ns["price"] = price
        ns["base"] = base_price
        result = safe_eval(adjustment.formula, ns)
        return result, f"formula '{adjustment.formula}' -> {round(result, 2)}"
    raise EngineError(f"Unknown adjustment.type '{t}'")


def _adjustment_direction(adjustment: Adjustment) -> int:
    """+1 increases price, -1 decreases, 0 unknown/neutral - used only for
    conflict heuristics, never for actual price computation."""
    t, v = adjustment.type, adjustment.value
    if t == "multiply" and v is not None:
        return 1 if v > 1 else (-1 if v < 1 else 0)
    if t == "percent" and v is not None:
        return 1 if v > 0 else (-1 if v < 0 else 0)
    if t == "add" and v is not None:
        return 1 if v > 0 else (-1 if v < 0 else 0)
    return 0


def _dates_overlap(r1: Rule, r2: Rule) -> bool:
    start_ok = r1.effective_to is None or r2.effective_from is None or r2.effective_from <= r1.effective_to
    end_ok = r2.effective_to is None or r1.effective_from is None or r1.effective_from <= r2.effective_to
    return start_ok and end_ok


_conflict_cache: Dict[tuple, List[Conflict]] = {}


def detect_conflicts(config: DomainConfig) -> List[Conflict]:
    """Static, config-time conflict detection: pairwise comparison of all
    enabled rules. This is a best-effort heuristic (see conditions.py) that
    favors flagging a possible conflict over silently mis-ordering rules.
    Results depend only on (domain, version), which are immutable once a
    version is created, so they're cached to keep per-request latency flat
    regardless of rule count."""
    cache_key = (config.domain, config.version)
    if cache_key in _conflict_cache:
        return _conflict_cache[cache_key]
    conflicts: List[Conflict] = []
    enabled = [r for r in config.rules if r.enabled]
    for i, r1 in enumerate(enabled):
        for r2 in enabled[i + 1:]:
            if not _dates_overlap(r1, r2):
                continue
            if conditions_provably_disjoint(r1.condition, r2.condition):
                continue
            same_condition = r1.condition == r2.condition

            if r1.adjustment.type == "set" and r2.adjustment.type == "set" and r1.adjustment.value != r2.adjustment.value:
                conflicts.append(Conflict(
                    kind="contradictory_override",
                    rule_ids=[r1.id, r2.id],
                    detail=(f"Both rules can match simultaneously and both 'set' an absolute "
                            f"price ({r1.adjustment.value} vs {r2.adjustment.value}) - outcome "
                            f"depends on priority order, which may be unintended."),
                ))
                continue

            if r1.priority == r2.priority:
                d1, d2 = _adjustment_direction(r1.adjustment), _adjustment_direction(r2.adjustment)
                if d1 != 0 and d2 != 0 and d1 != d2:
                    conflicts.append(Conflict(
                        kind="priority_tie",
                        rule_ids=[r1.id, r2.id],
                        detail=(f"Rules share priority {r1.priority}, can both match, and push the "
                                f"price in opposite directions - evaluation order is ambiguous."),
                    ))
                    continue

            if same_condition:
                d1, d2 = _adjustment_direction(r1.adjustment), _adjustment_direction(r2.adjustment)
                if d1 != 0 and d2 != 0 and d1 != d2:
                    conflicts.append(Conflict(
                        kind="duplicate_condition_conflicting_adjustment",
                        rule_ids=[r1.id, r2.id],
                        detail="Rules have an identical condition but adjust price in opposite directions.",
                    ))
    return conflicts


def _apply_constraints(price: float, base_price: float, config: DomainConfig) -> tuple[float, List[ConstraintTrace]]:
    traces: List[ConstraintTrace] = []
    for c in config.constraints:
        before = price
        if c.type == "min_price" and price < c.value:
            price = c.value
            traces.append(ConstraintTrace("min_price", f"Clamped up to floor {c.value}", before, price))
        elif c.type == "max_price" and price > c.value:
            price = c.value
            traces.append(ConstraintTrace("max_price", f"Clamped down to ceiling {c.value}", before, price))
        elif c.type == "max_increase_pct":
            cap = base_price * (1 + c.value)
            if price > cap:
                price = cap
                traces.append(ConstraintTrace("max_increase_pct", f"Capped increase at {c.value * 100:.0f}% over base", before, price))
        elif c.type == "max_decrease_pct":
            floor = base_price * (1 - c.value)
            if price < floor:
                price = floor
                traces.append(ConstraintTrace("max_decrease_pct", f"Floored decrease at {c.value * 100:.0f}% under base", before, price))
        elif c.type == "round":
            mode = c.rounding or "nearest"
            step = c.value or 1.0
            if mode == "nearest":
                price = round(price / step) * step
            elif mode == "up":
                price = math.ceil(price / step) * step
            elif mode == "down":
                price = math.floor(price / step) * step
            elif mode == "charm":
                price = math.floor(price / step) * step - 0.01
            if price != before:
                traces.append(ConstraintTrace("round", f"Rounded ({mode}, step {step})", before, price))
    return price, traces


def compute_price(
    config: DomainConfig,
    context: Dict[str, Any],
    as_of: Optional[date] = None,
) -> PricingResult:
    as_of = as_of or date.today()
    signals_cfg = config.signals.model_dump() if config.signals else None
    context, signal_trace = apply_signals(signals_cfg, context)
    base_price = _resolve_base_price(config, context)
    price = base_price

    applied: List[RuleTrace] = []
    skipped: List[SkippedRuleTrace] = []

    ordered_rules = sorted(config.rules, key=lambda r: r.priority)
    for rule in ordered_rules:
        if not rule.enabled:
            skipped.append(SkippedRuleTrace(rule.id, "disabled"))
            continue
        if not _rule_active_on(rule, as_of):
            skipped.append(SkippedRuleTrace(rule.id, f"not effective on {as_of.isoformat()}"))
            continue
        if not evaluate(rule.condition, context):
            skipped.append(SkippedRuleTrace(rule.id, "condition not met"))
            continue
        before = price
        price, summary = _apply_adjustment(price, rule.adjustment, context, base_price)
        applied.append(RuleTrace(
            id=rule.id,
            description=rule.description,
            priority=rule.priority,
            adjustment_summary=summary,
            price_before=round(before, 2),
            price_after=round(price, 2),
            tags=rule.tags,
        ))

    price, constraint_traces = _apply_constraints(price, base_price, config)
    conflicts = detect_conflicts(config)

    return PricingResult(
        domain=config.domain,
        config_version=config.version,
        base_price=base_price,
        final_price=price,
        currency=config.currency,
        applied_rules=applied,
        skipped_rules=skipped,
        constraints_applied=constraint_traces,
        conflicts=conflicts,
        context_used=context,
        signal_trace=signal_trace,
    )
