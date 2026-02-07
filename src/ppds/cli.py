from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict

from .types import (
    FieldSpec,
    JoinKeySpec,
    FeatureSpec,
    PolicyThresholds,
    Boundary,
    Granularity,
)
from .planner import decide, plan_counterfactuals
from .budget import BudgetLedger, SpendEvent


# =============================================================================
# Helpers
# =============================================================================

def _load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Config must be a JSON object at top-level: {path}")
    return obj


def _write_text(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _require_keys(obj: Dict[str, Any], keys: list[str], where: str) -> list[str]:
    missing = [k for k in keys if k not in obj]
    return [f"{where}: missing required key '{k}'" for k in missing]


def _validate_policy_features(policy: Dict[str, Any], features: Dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Minimal fail-closed validation. Keep this conservative and expand later.
    Must match what your downstream constructors expect.
    """
    errors: list[str] = []
    errors += _require_keys(policy, ["thresholds"], "policy")
    errors += _require_keys(features, ["feature_id", "fields"], "features")

    if "fields" in features and not isinstance(features["fields"], list):
        errors.append("features: 'fields' must be a list")
    if "thresholds" in policy and not isinstance(policy["thresholds"], dict):
        errors.append("policy: 'thresholds' must be an object")

    return (len(errors) == 0), errors


def _to_thresholds(policy: Dict[str, Any]) -> PolicyThresholds:
    """
    Build PolicyThresholds from JSON.

    Expected schema:
    {
      "thresholds": {
        "k_min": 100,
        "tau_boundary": {"LOCAL": 0.9, "SHUFFLE": 0.7, "CENTRAL": 0.55},
        "tau_granularity": {"ITEM": 0.45, "CLUSTER": 0.60, "AGGREGATE": 0.75}
      }
    }
    """
    th = policy["thresholds"]

    tau_b_raw = th.get("tau_boundary", {})
    tau_g_raw = th.get("tau_granularity", {})

    tau_boundary = {}
    for k, v in tau_b_raw.items():
        # allow either enum name strings or enum values
        b = Boundary[k] if isinstance(k, str) and k in Boundary.__members__ else Boundary(k)
        tau_boundary[b] = float(v)

    tau_granularity = {}
    for k, v in tau_g_raw.items():
        g = Granularity[k] if isinstance(k, str) and k in Granularity.__members__ else Granularity(k)
        tau_granularity[g] = float(v)

    return PolicyThresholds(
        tau_boundary=tau_boundary,
        tau_granularity=tau_granularity,
        k_min=int(th.get("k_min", 1)),
    )


def _to_feature_spec(features: Dict[str, Any]) -> FeatureSpec:
    """
    Build FeatureSpec from JSON.

    Expected minimal schema:
    {
      "feature_id": "...",
      "fields": [{"name": "...", "dtype": "...", "is_sensitive": true, "is_identifier": false}, ...],
      "bucketizations": {"age": 80},
      "join_keys": [{"name": "...", "stability": 0.95, "ndv_hint": 5000000}],
      ...
    }
    """
    fields = []
    for f in features.get("fields", []):
        # accept either dict form or list/tuple form; keep strict defaults
        if not isin
