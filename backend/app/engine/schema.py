"""
Pydantic models describing the domain-agnostic pricing configuration format.
Any industry (hospitality, ride-hailing, e-commerce, banking, ...) is
expressed as one of these documents - adding a domain means authoring a new
JSON document, never touching engine code.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Attribute(BaseModel):
    name: str
    type: Literal["number", "string", "boolean", "date"]
    description: str = ""
    enum: Optional[List[Any]] = None
    source: Literal["context", "derived"] = "context"


class BasePrice(BaseModel):
    mode: Literal["attribute", "formula", "fixed"]
    attribute: Optional[str] = None
    formula: Optional[str] = None
    value: Optional[float] = None


class Adjustment(BaseModel):
    type: Literal["multiply", "percent", "add", "set", "formula"]
    value: Optional[float] = None
    formula: Optional[str] = None


class Rule(BaseModel):
    id: str
    description: str = ""
    priority: int = 100
    enabled: bool = True
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    condition: Dict[str, Any] = Field(default_factory=lambda: {"always": True})
    adjustment: Adjustment
    tags: List[str] = Field(default_factory=list)


class Constraint(BaseModel):
    type: Literal["min_price", "max_price", "max_increase_pct", "max_decrease_pct", "round"]
    value: float
    rounding: Optional[Literal["nearest", "up", "down", "charm"]] = None


class SignalConfig(BaseModel):
    """Optional ML-assist signals that get computed from context and
    injected back into the context namespace before rules run, e.g.
    a predicted-demand-index derived attribute or an anomaly flag."""
    demand_prediction: Optional[Dict[str, Any]] = None
    anomaly_detection: Optional[Dict[str, Any]] = None


class DomainConfig(BaseModel):
    domain: str
    version: int = 1
    description: str = ""
    currency: str = "USD"
    entity: Dict[str, str] = Field(default_factory=dict)
    attributes: List[Attribute] = Field(default_factory=list)
    base_price: BasePrice
    combination_mode: Literal["sequential"] = "sequential"
    rules: List[Rule] = Field(default_factory=list)
    constraints: List[Constraint] = Field(default_factory=list)
    signals: Optional[SignalConfig] = None

    @field_validator("rules")
    @classmethod
    def unique_rule_ids(cls, rules: List[Rule]) -> List[Rule]:
        ids = [r.id for r in rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate rule ids in config: {dupes}")
        return rules
