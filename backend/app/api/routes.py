from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..engine.evaluator import compute_price, detect_conflicts
from ..engine.loader import ConfigValidationError, load_config
from ..engine.simulate import run_simulation
from ..ml.nl_copilot import parse_nl_rule
from ..store import repository as repo
from ..store.repository import RepositoryError

router = APIRouter(prefix="/api")

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "sample_contexts")


class PriceRequest(BaseModel):
    context: Dict[str, Any]
    as_of: Optional[str] = None
    version: Optional[int] = None


class SimulateRequest(BaseModel):
    cases: Optional[List[Dict[str, Any]]] = None
    version: Optional[int] = None


class ConfigCreateRequest(BaseModel):
    config: Dict[str, Any]
    note: str = ""
    activate: bool = False
    created_by: str = "user"


class NLRuleRequest(BaseModel):
    text: str


def _resolve_config(domain: str, version: Optional[int]):
    try:
        if version is not None:
            return load_config(repo.get_version(domain, version))
        return repo.get_active_config(domain)
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/domains")
def list_domains():
    return {"domains": repo.list_domains()}


@router.get("/domains/{domain}/versions")
def list_versions(domain: str):
    versions = repo.list_versions(domain)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")
    return {"domain": domain, "versions": versions}


@router.get("/domains/{domain}/config")
def get_config(domain: str, version: Optional[int] = None):
    config = _resolve_config(domain, version)
    return config.model_dump(mode="json")


@router.get("/domains/{domain}/conflicts")
def get_conflicts(domain: str, version: Optional[int] = None):
    config = _resolve_config(domain, version)
    conflicts = detect_conflicts(config)
    return {"domain": domain, "version": config.version, "conflicts": [vars(c) for c in conflicts]}


@router.post("/domains/{domain}/config")
def create_config_version(domain: str, body: ConfigCreateRequest):
    try:
        version = repo.create_version(domain, body.config, created_by=body.created_by,
                                       note=body.note, activate=body.activate)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=f"Config validation failed: {e}") from e
    config = load_config(repo.get_version(domain, version))
    conflicts = detect_conflicts(config)
    return {
        "domain": domain,
        "version": version,
        "activated": body.activate,
        "conflicts_detected": [vars(c) for c in conflicts],
    }


@router.post("/domains/{domain}/activate/{version}")
def activate_version(domain: str, version: int):
    try:
        repo.activate_version(domain, version)
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"domain": domain, "active_version": version}


@router.post("/domains/{domain}/rollback/{version}")
def rollback_version(domain: str, version: int):
    try:
        repo.rollback(domain, version)
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"domain": domain, "active_version": version, "action": "rollback"}


@router.post("/price/{domain}")
def price(domain: str, body: PriceRequest):
    config = _resolve_config(domain, body.version)
    as_of = datetime.strptime(body.as_of, "%Y-%m-%d").date() if body.as_of else None
    try:
        result = compute_price(config, body.context, as_of=as_of)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    response = result.to_dict()
    repo.record_audit(domain, config.version, body.context, response, source="api")
    return response


@router.post("/simulate/{domain}")
def simulate(domain: str, body: SimulateRequest):
    config = _resolve_config(domain, body.version)
    cases = body.cases
    if cases is None:
        path = os.path.join(SAMPLE_DIR, f"{domain}_cases.json")
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"No built-in sample cases for '{domain}'; pass 'cases' explicitly.")
        with open(path) as f:
            cases = json.load(f)
    return run_simulation(config, cases)


@router.get("/audit")
def audit(domain: Optional[str] = None, limit: int = 50):
    return {"entries": repo.list_audit(domain=domain, limit=limit)}


@router.post("/copilot/nl-to-rule")
def nl_to_rule(domain: str, body: NLRuleRequest):
    config = _resolve_config(domain, None)
    known_attrs = [a.name for a in config.attributes]
    return parse_nl_rule(body.text, known_attributes=known_attrs)
