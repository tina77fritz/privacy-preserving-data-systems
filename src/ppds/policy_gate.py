"""
Fail-closed policy gate for PPDS.

Design goals:
- Fail-closed: if evaluation cannot be completed safely, default to REJECT.
- Structured reasons: machine-readable rejection reasons for audits and CI.
- Deterministic behavior: stable serialization, stable key ordering, stable float rounding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple, Union


EXIT_ALLOW = 0
EXIT_REJECT = 2


@dataclass(frozen=True)
class RejectionReason:
    """
    A structured reason for rejection (or evaluation failure).

    code: Stable identifier for programmatic checks (e.g., CI assertions).
    message: Human-readable explanation.
    details: Arbitrary JSON-serializable payload for audit/debug.
    """
    code: str
    message: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class GateDecision:
    """
    Structured policy gate decision output.

    decision: "ALLOW" or "REJECT"
    exit_code: process exit code (0 allow, 2 reject)
    reasons: structured reasons list (empty for allow)
    """
    decision: str
    exit_code: int
    policy: Dict[str, Any]
    lps: Dict[str, Any]
    reasons: List[RejectionReason]

    def to_json_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert dataclass reasons explicitly to dict for stable serialization.
        d["reasons"] = [asdict(r) for r in self.reasons]
        return d

    def to_json(self, *, sort_keys: bool = True, indent: int = 2) -> str:
        canonical = canonicalize(self.to_json_dict())
        return json.dumps(canonical, ensure_ascii=False, sort_keys=sort_keys, indent=indent)


def sha256_file_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def canonicalize(obj: Any, *, float_ndigits: int = 8) -> Any:
    """
    Convert obj into a JSON-serializable, deterministic representation:
    - dict keys sorted
    - dataclasses converted to dict
    - objects with to_dict() converted
    - floats rounded to float_ndigits
    """
    if obj is None:
        return None

    # Preserve booleans and ints
    if isinstance(obj, (bool, int, str)):
        return obj

    # Round floats deterministically
    if isinstance(obj, float):
        return round(obj, float_ndigits)

    # Lists / tuples: preserve order (caller is responsible for stable ordering)
    if isinstance(obj, (list, tuple)):
        return [canonicalize(x, float_ndigits=float_ndigits) for x in obj]

    # Dataclass -> dict
    if is_dataclass(obj):
        return canonicalize(asdict(obj), float_ndigits=float_ndigits)

    # Objects with to_dict
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        return canonicalize(obj.to_dict(), float_ndigits=float_ndigits)

    # Dict: sort keys
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k in sorted(obj.keys(), key=lambda x: str(x)):
            out[str(k)] = canonicalize(obj[k], float_ndigits=float_ndigits)
        return out

    # Fallback: try __dict__, otherwise string
    if hasattr(obj, "__dict__"):
        return canonicalize(dict(obj.__dict__), float_ndigits=float_ndigits)

    return str(obj)


def evaluate_policy_gate(
    *,
    policy_path: str,
    policy_bytes: bytes,
    policy_threshold: float,
    input_payload: Dict[str, Any],
    compute_lps_fn,
    threshold_override: Optional[float] = None,
    hard_reject: bool = True,
    float_ndigits: int = 8,
) -> GateDecision:
    """
    Evaluate the policy gate in a fail-closed manner.

    Parameters:
    - policy_path: path string (for audit metadata)
    - policy_bytes: raw policy file bytes (used to compute sha256 checksum)
    - policy_threshold: threshold from policy (lps_max)
    - input_payload: parsed input payload (dict)
    - compute_lps_fn: function(input_payload) -> (score: float, breakdown: any)
    - threshold_override: optional override threshold (evaluation only)
    - hard_reject: if True, any threshold violation returns REJECT (exit 2)
    - float_ndigits: rounding precision used in deterministic output

    Fail-closed behavior:
    - Any exception in compute_lps_fn or data conversion yields REJECT with reason EVALUATION_ERROR.
    """
    effective_threshold = threshold_override if threshold_override is not None else policy_threshold
    policy_hash = sha256_file_bytes(policy_bytes)

    policy_meta = canonicalize(
        {
            "path": policy_path,
            "sha256": policy_hash,
            "threshold_policy": policy_threshold,
            "threshold_effective": effective_threshold,
            "hard_reject": bool(hard_reject),
        },
        float_ndigits=float_ndigits,
    )

    # Default output placeholders (filled after evaluation).
    lps_meta: Dict[str, Any] = {"score": None, "breakdown": None}

    reasons: List[RejectionReason] = []

    try:
        lps_score, breakdown = compute_lps_fn(input_payload)
        lps_meta = canonicalize(
            {"score": lps_score, "breakdown": breakdown},
            float_ndigits=float_ndigits,
        )

        violated = bool(lps_meta["score"] > effective_threshold)

        if violated:
            reasons.append(
                RejectionReason(
                    code="LPS_THRESHOLD_EXCEEDED",
                    message="Input violates LPS threshold.",
                    details={
                        "lps_score": lps_meta["score"],
                        "threshold_effective": effective_threshold,
                        "threshold_policy": policy_threshold,
                        "threshold_override": threshold_override,
                    },
                )
            )
            return GateDecision(
                decision="REJECT" if hard_reject else "ALLOW",
                exit_code=EXIT_REJECT if hard_reject else EXIT_ALLOW,
                policy=policy_meta,
                lps=lps_meta,
                reasons=reasons,
            )

        # No violation => allow.
        return GateDecision(
            decision="ALLOW",
            exit_code=EXIT_ALLOW,
            policy=policy_meta,
            lps=lps_meta,
            reasons=[],
        )

    except Exception as e:
        # Fail-closed: if evaluation fails, reject (do not risk leaking unsafe outputs).
        reasons.append(
            RejectionReason(
                code="EVALUATION_ERROR",
                message="Policy gate evaluation failed; failing closed.",
                details={"error": str(e)},
            )
        )
        return GateDecision(
            decision="REJECT",
            exit_code=EXIT_REJECT,
            policy=policy_meta,
            lps=canonicalize(lps_meta, float_ndigits=float_ndigits),
            reasons=reasons,
        )
