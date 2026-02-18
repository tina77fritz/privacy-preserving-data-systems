from __future__ import annotations

from typing import Dict
from .base import SQLDialect

_REGISTRY: Dict[str, SQLDialect] = {}


def register(dialect: SQLDialect) -> None:
    name = getattr(dialect, "name", None)
    if not name or not isinstance(name, str):
        raise ValueError("Dialect must define a non-empty .name")
    _REGISTRY[name.lower()] = dialect


def get(name: str) -> SQLDialect:
    k = (name or "").lower()
    if k not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise KeyError(f"Unknown dialect '{name}'. Available: {available}")
    return _REGISTRY[k]


def available() -> Dict[str, SQLDialect]:
    return dict(_REGISTRY)
