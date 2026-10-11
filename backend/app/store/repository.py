"""
Repository for versioned domain configs and the pricing audit log.

Every config change creates a new immutable version row; activating a
version just flips the is_active flag (and deactivates whichever version
was active before). Nothing is ever mutated or deleted in place, so
"rollback" is simply "activate an older version" and the audit trail of
who-was-active-when falls out of created_at + is_active history for free.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..engine.loader import load_config
from ..engine.schema import DomainConfig
from .db import AuditLog, ConfigVersion, get_session


class RepositoryError(ValueError):
    pass


def list_domains() -> List[str]:
    with get_session() as s:
        rows = s.execute(select(ConfigVersion.domain).distinct()).all()
        return sorted({r[0] for r in rows})


def list_versions(domain: str) -> List[Dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(ConfigVersion).where(ConfigVersion.domain == domain).order_by(ConfigVersion.version)
        ).scalars().all()
        return [
            {
                "domain": r.domain,
                "version": r.version,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat(),
                "created_by": r.created_by,
                "note": r.note,
            }
            for r in rows
        ]


def get_version(domain: str, version: int) -> Dict[str, Any]:
    with get_session() as s:
        row = s.execute(
            select(ConfigVersion).where(ConfigVersion.domain == domain, ConfigVersion.version == version)
        ).scalar_one_or_none()
        if row is None:
            raise RepositoryError(f"No such config version: {domain} v{version}")
        return row.config_json


def get_active_config(domain: str) -> DomainConfig:
    with get_session() as s:
        row = s.execute(
            select(ConfigVersion).where(ConfigVersion.domain == domain, ConfigVersion.is_active == True)  # noqa: E712
        ).scalar_one_or_none()
        if row is None:
            raise RepositoryError(f"No active config for domain '{domain}'")
        return load_config(row.config_json)


def create_version(domain: str, config_dict: Dict[str, Any], created_by: str = "system",
                    note: str = "", activate: bool = False) -> int:
    config_dict = dict(config_dict)
    config_dict["domain"] = domain
    with get_session() as s:
        existing = s.execute(
            select(ConfigVersion.version).where(ConfigVersion.domain == domain).order_by(ConfigVersion.version.desc())
        ).scalars().first()
        next_version = (existing or 0) + 1
        config_dict["version"] = next_version
        validated = load_config(config_dict)  # raises on structural errors

        row = ConfigVersion(
            domain=domain,
            version=next_version,
            config_json=validated.model_dump(mode="json"),
            is_active=False,
            created_by=created_by,
            note=note,
        )
        s.add(row)
        s.commit()
        if activate:
            _activate_locked(s, domain, next_version)
        return next_version


def _activate_locked(s, domain: str, version: int) -> None:
    rows = s.execute(select(ConfigVersion).where(ConfigVersion.domain == domain)).scalars().all()
    found = False
    for r in rows:
        if r.version == version:
            r.is_active = True
            found = True
        else:
            r.is_active = False
    if not found:
        raise RepositoryError(f"No such config version: {domain} v{version}")
    s.commit()


def activate_version(domain: str, version: int) -> None:
    with get_session() as s:
        _activate_locked(s, domain, version)


def rollback(domain: str, version: int) -> None:
    activate_version(domain, version)


def record_audit(domain: str, config_version: int, context: Dict[str, Any],
                  response: Dict[str, Any], source: str = "api") -> int:
    with get_session() as s:
        row = AuditLog(
            domain=domain,
            config_version=config_version,
            request_context=context,
            response=response,
            final_price=str(response.get("final_price")),
            source=source,
        )
        s.add(row)
        s.commit()
        return row.id


def list_audit(domain: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with get_session() as s:
        q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if domain:
            q = select(AuditLog).where(AuditLog.domain == domain).order_by(AuditLog.created_at.desc()).limit(limit)
        rows = s.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "domain": r.domain,
                "config_version": r.config_version,
                "request_context": r.request_context,
                "response": r.response,
                "final_price": r.final_price,
                "created_at": r.created_at.isoformat(),
                "source": r.source,
            }
            for r in rows
        ]
