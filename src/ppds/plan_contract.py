from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


PLAN_SCHEMA_VERSION = "ppds.plan/0.1"


def _canonical_json_bytes(obj: Any) -> bytes:
    # stable bytes for hashing: sorted keys + no whitespace variance
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def compute_plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    # exclude the fingerprint field itself
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    return _sha256_hex(tmp)


@dataclass
class PPDSPlan:
    schema_version: str
    created_at: str
    policy_hash: str
    input_fingerprint: str
    plan_fingerprint: str
    status: str  # "accepted" | "rejected"
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
        policy_obj: Dict[str, Any],
        input_obj: Dict[str, Any],
        status: str,
        decisions: Dict[str, Any],
        rejection_reasons: Optional[List[RejectionReason]] = None,
        created_at: Optional[str] = None,
    ) -> "PPDSPlan":
        plan = PPDSPlan(
            schema_version=PLAN_SCHEMA_VERSION,
            created_at=created_at or utc_now_iso(),
            policy_hash=_sha256_hex(policy_obj),
            input_fingerprint=_sha256_hex(input_obj),
            plan_fingerprint="",
            status=status,
            decisions=decisions,
            rejection_reasons=rejection_reasons or [],
        )
        # set deterministic fingerprint
        plan.plan_fingerprint = plan.to_dict()["plan_fingerprint"]
        return plan
