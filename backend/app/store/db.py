from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, Integer, String,
                         UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = os.environ.get("PRICING_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "pricing.db"))
ENGINE = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("domain", "version", name="uq_domain_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    config_json = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, default="system")
    note = Column(String, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String, nullable=False, index=True)
    config_version = Column(Integer, nullable=False)
    request_context = Column(JSON, nullable=False)
    response = Column(JSON, nullable=False)
    final_price = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String, default="api")


def init_db() -> None:
    Base.metadata.create_all(ENGINE)


def get_session() -> Session:
    return SessionLocal()
