from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Protocol


@dataclass(frozen=True)
class SQLRenderResult:
    sql: str
    params: Dict[str, Any]
    metadata: Dict[str, Any]  # e.g. {"dialect": "...", "paramstyle": "named"}


class SQLDialect(Protocol):
    name: str
    paramstyle: str  # "named" | "qmark" | "at" etc.

    def quote_ident(self, ident: str) -> str: ...
    def render(self, plan: Dict[str, Any]) -> SQLRenderResult: ...
