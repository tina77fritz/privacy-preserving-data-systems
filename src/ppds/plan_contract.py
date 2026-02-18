from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict


PLAN_SCHEMA_VERSION = "ppds.plan/0.1"


def canonical_json_bytes(obj: Any) -> bytes:
    # stable bytes: sorted keys, no whitespace variance
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_hex_obj(obj: Any) -> str:
    return sha256_hex_bytes(canonical_json_bytes(obj))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    # Important: exclude plan_fingerprint itself from hash computation
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    return sha256_hex_obj(tmp)
