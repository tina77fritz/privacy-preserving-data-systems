from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


PLAN_SCHEMA_VERSION = "ppds.plan/0.1"


def canonical_json_bytes(obj: Any) -> bytes:
    # Stable bytes: sorted keys, no whitespace variance
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_hex_obj(obj: Any) -> str:
    return sha256_hex_bytes(canonical_json_bytes(obj))


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
        # keep logs clean + stable
        return {k: v for k, v in d.items() if v is not None}


def compute_plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    # Exclude plan_fingerprint itself
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    return sha256_hex_obj(tmp)


@dataclass
class PPDSPlan:
    schema_version: str
    created_at: str
    policy_hash: str
    input_fingerprint: str
    plan_fingerprint: str
    status:
