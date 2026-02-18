from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ppds.plan_contract import fingerprint
from ppds.sql.dialects.registry import get as get_dialect


def _ppds_header_comment(plan_dict: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> str:
    meta = {
        "ppds_schema_version": plan_dict.get("schema_version"),
        "policy_hash": plan_dict.get("policy_hash"),
        "input_fingerprint": plan_dict.get("input_fingerprint"),
        "plan_fingerprint": plan_dict.get("plan_fingerprint") or fingerprint(plan_dict),
        "status": plan_dict.get("status"),
    }
    if extra:
        meta.update(extra)
    # keep single-line JSON for log/warehouse audit
    meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"-- ppds:{meta_json}"


def emit_sql(plan_dict: Dict[str, Any], dialect_name: str) -> Dict[str, Any]:
    dialect = get_dialect(dialect_name)
    rendered = dialect.render(plan_dict)
    header = _ppds_header_comment(plan_dict, {"dialect": getattr(dialect, "name", dialect_name)})
    sql = header + "\n" + rendered.sql.strip() + "\n"
    return {
        "sql": sql,
        "params": rendered.params,
        "metadata": rendered.metadata,
    }
