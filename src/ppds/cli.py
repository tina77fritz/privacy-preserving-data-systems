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
        if not isinstance(f, dict):
            raise ValueError("features.fields items must be objects")
        fields.append(
            FieldSpec(
                f["name"],
                f.get("dtype", f.get("type", "string")),
                is_sensitive=bool(f.get("is_sensitive", False)),
                is_identifier=bool(f.get("is_identifier", False)),
            )
        )

    join_keys = []
    for jk in features.get("join_keys", []) or []:
        if not isinstance(jk, dict):
            raise ValueError("features.join_keys items must be objects")
        join_keys.append(
            JoinKeySpec(
                jk["name"],
                stability=float(jk.get("stability", 1.0)),
                ndv_hint=int(jk.get("ndv_hint", 0)),
            )
        )

    return FeatureSpec(
        feature_id=features["feature_id"],
        description=features.get("description", ""),
        fields=fields,
        join_keys=join_keys,
        ttl_days=int(features.get("ttl_days", 0)),
        bucketizations=dict(features.get("bucketizations", {}) or {}),
        policy_tags=list(features.get("policy_tags", []) or []),
        support_hint=dict(features.get("support_hint", {}) or {}),
    )


# =============================================================================
# Commands
# =============================================================================

def cmd_validate(args: argparse.Namespace) -> int:
    policy = _load_json(args.policy)
    features = _load_json(args.features)
    ok, errors = _validate_policy_features(policy, features)

    if ok:
        if args.format == "json":
            print(json.dumps({"ok": True}, indent=2))
        else:
            print("OK: configs are valid")
        return 0

    payload = {"ok": False, "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print("INVALID CONFIG:")
        for e in errors:
            print(f"- {e}")
    return 2


def cmd_plan(args: argparse.Namespace) -> int:
    policy = _load_json(args.policy)
    features = _load_json(args.features)
    ok, errors = _validate_policy_features(policy, features)
    if not ok:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2

    th = _to_thresholds(policy)
    feat = _to_feature_spec(features)
    dec = decide(feat, th)

    # Stable, audit-friendly output contract
    out_obj: Dict[str, Any] = {
        "schema_version": 1,
        "decision": {
            "boundary": getattr(dec.boundary, "value", str(dec.boundary)),
            "granularity": getattr(dec.granularity, "value", str(dec.granularity)),
            "feasible": bool(dec.feasible),
            "reason": dec.reason,
        },
        "planner_constraints_json": getattr(dec, "planner_constraints_json", None),
        "scorecard": asdict(dec.scorecard) if hasattr(dec, "scorecard") else None,
    }

    _write_text(args.out, json.dumps(out_obj, indent=2, default=str))
    print(f"Wrote plan: {args.out}")
    return 0


def cmd_emit_sql(args: argparse.Namespace) -> int:
    plan_obj = _load_json(args.plan)

    # Minimal SQL emission (placeholder). Replace with your real emitter as it matures.
    dec = plan_obj.get("decision", {})
    constraints = plan_obj.get("planner_constraints_json", {})

    sql = (
        f"-- PPDS SQL (dialect={args.dialect})\n"
        f"-- boundary={dec.get('boundary')} granularity={dec.get('granularity')}\n"
        f"-- constraints={constraints}\n\n"
        f"SELECT 1 AS ppds_placeholder;\n"
    )

    _write_text(args.out, sql)
    print(f"Wrote SQL: {args.out}")
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    """
    Preserve your existing demo behavior as `ppds demo`.
    """
    th = PolicyThresholds(
        tau_boundary={Boundary.LOCAL: 0.90, Boundary.SHUFFLE: 0.70, Boundary.CENTRAL: 0.55},
        tau_granularity={Granularity.ITEM: 0.45, Granularity.CLUSTER: 0.60, Granularity.AGGREGATE: 0.75},
        k_min=100,
    )

    f = FeatureSpec(
        feature_id="demo_age_location_ctr",
        description="Demo feature: ctr by age+location with stable join key",
        fields=[
            FieldSpec("age", "int", is_sensitive=True),
            FieldSpec("location", "string", is_sensitive=True),
            FieldSpec("device_model", "string", is_sensitive=False),
        ],
        join_keys=[JoinKeySpec("user_pseudo_id", stability=0.95, ndv_hint=5_000_000)],
        ttl_days=30,
        bucketizations={"age": 80, "location": 500},  # very fine
        policy_tags=["age", "location"],
        support_hint={Granularity.ITEM: 80, Granularity.CLUSTER: 20000, Granularity.AGGREGATE: 10_000_000},
    )

    d = decide(f, th)
    print("\n== Decision ==")
    print(json.dumps({
        "boundary": d.boundary.value,
        "granularity": d.granularity.value,
        "feasible": d.feasible,
        "risk": d.scorecard.risk,
        "components": {"L": d.scorecard.L, "U": d.scorecard.U, "I": d.scorecard.I, "R": d.scorecard.R},
        "contributors": d.scorecard.contributors,
        "reason": d.reason,
    }, indent=2, default=str))

    print("\n== Counterfactuals (target ITEM) ==")
    cfs = plan_counterfactuals(f, th, target_g=Granularity.ITEM)
    for x in cfs[:5]:
        sc = x["scorecard"]
        print(f"- {x['edit']}  feasible={x['feasible_at_target']}  risk={sc.risk:.3f}  (L={sc.L:.2f},U={sc.U:.2f},I={sc.I:.2f},R={sc.R:.2f})")

    print("\n== Budget Ledger demo (30-day cap) ==")
    ledger = BudgetLedger()
    cap = 1.0
    today = date(2026, 1, 30)
    for i in range(9):
        ledger.commit(SpendEvent(f.feature_id, today.replace(day=today.day - i), epsilon=0.1))
    eps30, _ = ledger.window_spend(f.feature_id, 30, today)
    print(f"spent_eps_30d={eps30:.2f} cap={cap:.2f} can_spend_next_0.1={ledger.can_spend(f.feature_id,30,today,cap,0.0,0.1)}")
    print(f"adaptive_eps_for_next_21_releases={ledger.adaptive_eps(f.feature_id,30,today,cap,planned_releases_left=21):.4f}")
    return 0


# =============================================================================
# Entrypoint
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(prog="ppds")
    sub = parser.add_subparsers(dest="cmd", required=False)

    # validate
    p_val = sub.add_parser("validate", help="Validate policy/features configs (fail-closed)")
    p_val.add_argument("--policy", required=True, help="Path to policy JSON")
    p_val.add_argument("--features", required=True, help="Path to feature spec JSON")
    p_val.add_argument("--format", default="text", choices=["text", "json"])
    p_val.set_defaults(func=cmd_validate)

    # plan
    p_plan = sub.add_parser("plan", help="Generate an auditable plan.json")
    p_plan.add_argument("--policy", required=True, help="Path to policy JSON")
    p_plan.add_argument("--features", required=True, help="Path to feature spec JSON")
    p_plan.add_argument("--out", required=True, help="Output path for plan.json")
    p_plan.set_defaults(func=cmd_plan)

    # emit-sql
    p_sql = sub.add_parser("emit-sql", help="Emit SQL from plan.json")
    p_sql.add_argument("--plan", required=True, help="Path to plan.json")
    p_sql.add_argument("--dialect", default="spark")
    p_sql.add_argument("--out", required=True, help="Output path for query.sql")
    p_sql.set_defaults(func=cmd_emit_sql)

    # demo (preserve old behavior)
    p_demo = sub.add_parser("demo", help="Run built-in demo (no configs)")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()

    # If user runs `ppds` with no args, show help and exit non-zero (friendly for CI)
    if not getattr(args, "cmd", None):
        parser.print_help()
        raise SystemExit(2)

    rc = args.func(args)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
