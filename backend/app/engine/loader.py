from __future__ import annotations

from typing import Any, Dict

from .schema import DomainConfig


class ConfigValidationError(ValueError):
    pass


def load_config(raw: Dict[str, Any]) -> DomainConfig:
    try:
        return DomainConfig.model_validate(raw)
    except Exception as e:  # pydantic ValidationError and friends
        raise ConfigValidationError(str(e)) from e
