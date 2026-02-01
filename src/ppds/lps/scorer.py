"""
CLI-facing LPS scorer: computes a single LPS risk score from an input payload.

Accepts a dict payload (e.g., from JSON/YAML input) and returns (score, breakdown).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from ..types import (
    Boundary,
    FieldSpec,
    Granularity,
    JoinKeySpec,
    PolicyThresholds,
)
from .core import compute_scorecard


def _payload_to_feature(payload: Dict[str, Any]) -> Tuple[Any, Granularity, PolicyThresholds]:
    """
    Build FeatureSpec, Granularity, and PolicyThresholds from a payload dict.

    Supports both full feature_spec structure and minimal payloads.
    Falls back to a conservative default when structure is incomplete.
    """
    from ..types import FeatureSpec

    th = PolicyThresholds(
        tau_boundary={b: 0.9 for b in Boundary},
        tau_granularity={g: 0.75 for g in Granularity},
        k_min=int(payload.get("k_min", 100)),
    )

    # Try to parse feature_spec from payload
    fs = payload.get("feature_spec") or payload.get("feature")
    if isinstance(fs, dict):
        fields = []
        for f in fs.get("fields", []):
            if isinstance(f, dict):
                fields.append(
                    FieldSpec(
                        name=f.get("name", "unknown"),
                        dtype=f.get("dtype", "string"),
                        is_sensitive=bool(f.get("is_sensitive", False)),
                        is_identifier=bool(f.get("is_identifier", False)),
                        cardinality_hint=f.get("cardinality_hint"),
                    )
                )
        join_keys = []
        for jk in fs.get("join_keys", []):
            if isinstance(jk, dict):
                join_keys.append(
                    JoinKeySpec(
                        name=jk.get("name", "id"),
                        stability=float(jk.get("stability", 0.8)),
                        ndv_hint=jk.get("ndv_hint"),
                    )
                )
        feature = FeatureSpec(
            feature_id=fs.get("feature_id", "default"),
            description=fs.get("description", ""),
            fields=fields or [FieldSpec("default", "string", is_sensitive=False)],
            join_keys=join_keys,
            ttl_days=int(fs.get("ttl_days", 30)),
            bucketizations=dict(fs.get("bucketizations", {})),
            policy_tags=list(fs.get("policy_tags", [])),
        )
    else:
        # Minimal default feature for cold start
        feature = FeatureSpec(
            feature_id=payload.get("feature_id", "default"),
            description="",
            fields=[FieldSpec("default", "string", is_sensitive=True)],
            join_keys=[],
            ttl_days=30,
            policy_tags=payload.get("policy_tags", []),
        )

    g_str = (payload.get("granularity") or payload.get("g") or "AGGREGATE").upper()
    try:
        g = Granularity(g_str)
    except ValueError:
        g = Granularity.AGGREGATE

    return feature, g, th


def compute_lps(payload: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """
    Compute LPS risk score from an input payload.

    Returns:
        (score, breakdown) where score is the aggregated risk (0..1)
        and breakdown is a JSON-serializable dict with component scores.
    """
    feature, g, th = _payload_to_feature(payload)
    scorecard = compute_scorecard(feature, g, th)

    breakdown = {
        "L": scorecard.L,
        "U": scorecard.U,
        "I": scorecard.I,
        "R": scorecard.R,
        "risk": scorecard.risk,
        "contributors": scorecard.contributors,
    }
    return scorecard.risk, breakdown
