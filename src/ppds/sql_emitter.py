# src/ppds/sql_emitter.py
"""
SQL emitter for PPDS warehouse integration.

This module generates SQL-compatible, parameterized snippets based on a routing decision.

Design goals:
- Warehouse-friendly: produce INSERT...SELECT snippets that can be executed by schedulers.
- Parameterized: support named parameters for filters (e.g., run_date).
- Deterministic: stable column ordering and stable formatting across runs.
- Dialect-aware: basic placeholder style support (BigQuery, Postgres/Redshift, Snowflake).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SqlEmitConfig:
    """
    Configuration for emitting SQL snippets.
    """
    dialect: str = "postgres"          # "postgres" | "redshift" | "snowflake" | "bigquery"
    param_style: str = "named"         # "named" only (e.g., :run_date or @run_date)
    include_metadata_columns: bool = True
    float_ndigits: int = 8


@dataclass(frozen=True)
class SqlRoutingDecision:
    """
    Minimal routing decision for SQL emission.

    route:
      - "ALLOW": write to the destination table
      - "QUARANTINE": write to quarantine table with metadata
      - "REJECT": do not emit executable SQL (emit comment-only SQL)
    """
    route: str
    selected_columns: List[str]        # columns selected from source (stable order already)
    dropped_columns: List[str]
    reason_codes: List[str]            # structured reason codes
    lps_score: Optional[float]
    threshold: Optional[float]
    policy_sha256: Optional[str]
    policy_path: Optional[str]


def _param_name(dialect: str, name: str) -> str:
    """
    Named parameter placeholder.
    - Postgres/Redshift/Snowflake often support :name via client libraries or drivers.
    - BigQuery uses @name.
    """
    if dialect.lower() == "bigquery":
        return f"@{name}"
    return f":{name}"


def _quote_ident(dialect: str, ident: str) -> str:
    """
    Quote an identifier if needed.

    For simplicity, we quote with double-quotes for most SQL dialects and backticks for BigQuery.
    Callers should pass fully-qualified names as needed (e.g., schema.table).
    """
    if dialect.lower() == "bigquery":
        # BigQuery uses backticks for identifiers.
        return f"`{ident}`"
    return f'"{ident}"'


def _format_metadata_columns(dialect: str) -> Tuple[List[str], List[str]]:
    """
    Returns:
      - destination column names (metadata columns)
      - select expressions for metadata columns
    """
    # These are generic and can be adapted to your warehouse schema.
    dest_cols = ["ppds_policy_sha256", "ppds_lps_score", "ppds_threshold", "ppds_reason_codes"]
    select_exprs = [
        _param_name(dialect, "ppds_policy_sha256"),
        _param_name(dialect, "ppds_lps_score"),
        _param_name(dialect, "ppds_threshold"),
        _param_name(dialect, "ppds_reason_codes_json"),
    ]
    return dest_cols, select_exprs


def emit_insert_select_sql(
    *,
    decision: SqlRoutingDecision,
    source_table: str,
    dest_table: Optional[str],
    quarantine_table: Optional[str],
    where_clause: Optional[str] = None,
    config: Optional[SqlEmitConfig] = None,
) -> str:
    """
    Emit an INSERT...SELECT SQL snippet based on decision.route.

    Parameters:
    - source_table: required, can be templated (e.g., {{ source_table }})
    - dest_table: required when route == "ALLOW"
    - quarantine_table: required when route == "QUARANTINE"
    - where_clause: optional, should be a SQL fragment using named params (e.g., "dt = :run_date")
    - config: SqlEmitConfig

    Note:
    - This function does not validate table existence.
    - Table names cannot be bound parameters in most warehouses; pass templated identifiers if needed.
    """
    cfg = config or SqlEmitConfig()
    dialect = cfg.dialect.lower()

    # Deterministic: assume decision.selected_columns is already stable.
    selected_cols = list(decision.selected_columns)

    header_lines = [
        "-- PPDS SQL Snippet (parameterized)",
        f"-- route={decision.route}",
        f"-- policy_path={decision.policy_path or ''}",
        f"-- policy_sha256={decision.policy_sha256 or ''}",
        f"-- lps_score={decision.lps_score if decision.lps_score is not None else ''}",
        f"-- threshold={decision.threshold if decision.threshold is not None else ''}",
        f"-- reason_codes={','.join(decision.reason_codes)}",
        "-- Parameters expected (named):",
        f"--   {_param_name(dialect, 'run_date')} (optional; only if used in WHERE clause)",
        f"--   {_param_name(dialect, 'ppds_policy_sha256')}, {_param_name(dialect, 'ppds_lps_score')}, {_param_name(dialect, 'ppds_threshold')}, {_param_name(dialect, 'ppds_reason_codes_json')} (if metadata enabled)",
        "--",
    ]

    if decision.route == "REJECT":
        # Emit comment-only SQL (non-executable by design).
        header_lines.append("-- REJECT route: no INSERT statement emitted.")
        if decision.dropped_columns:
            header_lines.append(f"-- dropped_columns={','.join(decision.dropped_columns)}")
        return "\n".join(header_lines)

    # Choose target table based on route.
    if decision.route == "ALLOW":
        if not dest_table:
            raise ValueError("dest_table is required when decision.route == 'ALLOW'")
        target = dest_table
    elif decision.route == "QUARANTINE":
        if not quarantine_table:
            raise ValueError("quarantine_table is required when decision.route == 'QUARANTINE'")
        target = quarantine_table
    else:
        raise ValueError(f"Unknown decision.route: {decision.route}")

    # Destination columns (data columns)
    dest_data_cols = selected_cols[:]
    select_data_exprs = [c for c in selected_cols]  # 1:1 mapping by default

    # Optional metadata columns
    dest_meta_cols: List[str] = []
    select_meta_exprs: List[str] = []
    if cfg.include_metadata_columns:
        dest_meta_cols, select_meta_exprs = _format_metadata_columns(dialect)

    dest_cols_all = dest_data_cols + dest_meta_cols
    select_exprs_all = select_data_exprs + select_meta_exprs

    # Format identifiers (quote column names, but not expressions).
    # If your columns include expressions, you should pass already-formed SQL fragments.
    dest_cols_sql = ", ".join(_quote_ident(dialect, c) for c in dest_cols_all)
    select_exprs_sql = ", ".join(select_exprs_all)

    # Source table should be passed as already-qualified name or template.
    source_sql = source_table

    sql_lines = header_lines + [
        f"INSERT INTO {target} ({dest_cols_sql})",
        f"SELECT {select_exprs_sql}",
        f"FROM {source_sql}",
    ]

    if where_clause:
        sql_lines.append(f"WHERE {where_clause}")

    sql_lines.append(";")
    return "\n".join(sql_lines)
