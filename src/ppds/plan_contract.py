# src/ppds/plan_contract.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


PLAN_SCHEMA_VERSION = "ppds.plan/0.1"


# =============================================================================
# Canonicalization + hashing
# =============================================================================

def _canonical_json_bytes(obj: Any) -> bytes:
    """
    Canonical JSON for stable hashing:
    - sort_keys=True ensures deterministic key order
    - separators remove whitespace differences
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _sha256_hex_obj(obj: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_input_fingerprint(input_obj: Dict[str, Any]) -> str:
    """
    Deterministic fingerprint of the input object (order-insensitive).
    """
    return _sha256_hex_obj(input_obj)


def compute_plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    """
    Deterministic fingerprint of the plan contract.

    IMPORTANT for tests/CI:
    - Excludes created_at because it is inherently non-deterministic.
    - Excludes plan_fingerprint itself to avoid recursion.
    """
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    tmp.pop("created_at", None)
    return _sha256_hex_obj(tmp)


# =============================================================================
# Contract types
# =============================================================================

@dataclass(frozen=True)
class RejectionReason:
    code: str
    message: str
    path: Optional[str] = None
    metric: Optional[str] = None
    threshold: Optional[float] = None
    observed: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class PPDSPlan:
    schema_version: str
    created_at: str
    policy_hash: str
    input_fingerprint: str
    plan_fingerprint: str
    status: str
    decisions: Dict[str, Any]
    rejection_reasons: List[RejectionReason]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "policy_hash": self.policy_hash,
            "input_fingerprint": self.input_fingerprint,
            "status": self.status,
            "decisions": self.decisions,
            "rejection_reasons": [r.to_dict() for r in self.rejection_reasons],
        }
        d["plan_fingerprint"] = compute_plan_fingerprint(d)
        return d

    @staticmethod
    def build(
        *,
        policy_hash: str,
        input_obj: Dict[str, Any],
        status: str,
        decisions: Dict[str, Any],
        rejection_reasons: Optional[List[RejectionReason]] = None,
        created_at: Optional[str] = None,
        schema_version: str = PLAN_SCHEMA_VERSION,
    ) -> "PPDSPlan":
        plan = PPDSPlan(
            schema_version=schema_version,
            created_at=created_at or utc_now_iso(),
            policy_hash=str(policy_hash),
            input_fingerprint=compute_input_fingerprint(input_obj),
            plan_fingerprint="",
            status=str(status),
            decisions=decisions,
            rejection_reasons=rejection_reasons or [],
        )

        # Set a deterministic fingerprint (excludes created_at by design).
        plan.plan_fingerprint = compute_plan_fingerprint(plan.to_dict())
        return plan
