from __future__ import annotations

from typing import Any, Dict
from .base import SQLDialect, SQLRenderResult
from .registry import register


class SparkDialect:
    name = "spark"
    paramstyle = "named"  # use :param

    def quote_ident(self, ident: str) -> str:
        # Spark SQL supports backticks
        return f"`{ident}`"

    def render(self, plan: Dict[str, Any]) -> SQLRenderResult:
        # Minimal example: plan["decisions"]["select"] and ["from"]
        decisions = plan.get("decisions", {})
        select_cols = decisions.get("select", ["*"])
        from_table = decisions.get("from")
        if not from_table:
            raise ValueError("plan.decisions.from is required for Spark SQL render")

        sql = f"SELECT {', '.join(select_cols)} FROM {from_table}"
        params: Dict[str, Any] = decisions.get("params", {})
        meta = {"dialect": self.name, "paramstyle": self.paramstyle}
        return SQLRenderResult(sql=sql, params=params, metadata=meta)


register(SparkDialect())
