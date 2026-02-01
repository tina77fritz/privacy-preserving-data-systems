# src/ppds/routing_engine.py
"""
Routing engine for PPDS SQL emission.

This is intentionally minimal: it turns the policy gate result into a SQL routing decision.

Routing semantics (MVP):
- If policy gate ALLOW: route="ALLOW" (write to destination)
- If policy gate REJECT but a quarantine table is available: route="QUARANTINE"
- If policy gate REJECT and no quarantine: route="REJECT"

Column selection semantics (MVP):
- If policy.allowed_dimensions is non-empty: select only those columns (intersection with input keys)
- Always drop policy.blocked_dimensions (if present in input)
- Remaining columns are selected in deterministic order (sorted)

This is meant for warehouse integration where the input payload keys represent available columns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ppds.sql_emitter import SqlRoutingDecision


@dataclass(frozen=True)
class GateResult:
    """
    Minimal interface expected from a policy gate evaluation.
    """
    decision: str                     # "ALLOW" or "REJECT"
    policy_path: Optional[str]
    policy_sha256: Optional[str]
    lps_score: Optional[float]
    threshold: Optional[float]
    reason_codes: List[str]


def build_sql_routing_decision(
    *,
    gate: GateResult,
    input_payload: Dict[str, Any],
    policy_allowed_dimensions: List[str],
    policy_blocked_dimensions: List[str],
    quarantine_available: bool,
) -> SqlRoutingDecision:
    """
    Convert gate result + policy lists + input payload keys into an SqlRoutingDecision.

    Determinism:
    - Output column lists are sorted for stable ordering across runs.
    """
    input_cols = sorted([str(k) for k in input_payload.keys()])

    blocked = set(str(x) for x in policy_blocked_dimensions or [])
    allowed_list = [str(x) for x in (policy_allowed_dimensions or [])]

    # Start with columns allowed by policy (if allowlist exists) or all columns.
    if allowed_list:
        allowed_set = set(allowed_list)
        selected = [c for c in input_cols if c in allowed_set]
        dropped_not_allowed = [c for c in input_cols if c not in allowed_set]
    else:
        selected = input_cols[:]
        dropped_not_allowed = []

    # Drop blocked columns regardless.
    selected = [c for c in selected if c not in blocked]
    dropped_blocked = [c for c in input_cols if c in blocked]

    dropped = sorted(set(dropped_not_allowed + dropped_blocked))

    # Decide route.
    if gate.decision == "ALLOW":
        route = "ALLOW"
    else:
        route = "QUARANTINE" if quarantine_available else "REJECT"

    return SqlRoutingDecision(
        route=route,
        selected_columns=selected,
        dropped_columns=dropped,
        reason_codes=gate.reason_codes,
        lps_score=gate.lps_score,
        threshold=gate.threshold,
        policy_sha256=gate.policy_sha256,
        policy_path=gate.policy_path,
    )


def serialize_reason_codes_json(reason_codes: List[str]) -> str:
    """
    Serialize reason codes as a JSON array string for ppds_reason_codes_json parameter.
    """
    # Stable output: sort reason codes.
    stable = sorted(set(reason_codes))
    return json.dumps(stable, ensure_ascii=False, separators=(",", ":"))
