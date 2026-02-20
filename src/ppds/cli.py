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
    th = policy["thresholds"]

    # defaults (from your demo)
    tau_boundary = {
        Boundary.LOCAL: 0.90,
        Boundary.SHUFFLE: 0.70,
        Boundary.CENTRAL: 0.55,
    }
    tau_granularity = {
        Granularity.ITEM: 0.45,
        Granularity.CLUSTER: 0.60,
        Granularity.AGGREGATE: 0.75,
    }

    # override from config (optional)
    for k, v in (th.get("tau_boundary", {}) or {}).items():
        b = Boundary[k] if isinstance(k, str) and k in Boundary.__members__ else Boundary(k)
        tau_boundary[b] = float(v)

    for k, v in (th.get("tau_granularity", {}) or {}).items():
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

def _emit_sql_text(plan_obj: Dict[str, Any], dialect: str) -> str:
    """
    Emit SQL text from an in-memory plan object (no file IO).
    Mirrors cmd_emit_sql() behavior.
    """
    if "decision" not in plan_obj:
        _raise_config_error(
            "PPDS_PLAN_MISSING_DECISION",
            "plan object missing required key: decision",
            details={"keys": sorted(list(plan_obj.keys()))},
            remediation="Regenerate plan.json using `ppds plan` with valid inputs.",
        )

    dec = plan_obj.get("decision", {})
    constraints = plan_obj.get("planner_constraints_json", {})

    header_meta = {
        "schema_version": plan_obj.get("schema_version"),
        "created_at": plan_obj.get("created_at"),
        "policy_hash": plan_obj.get("policy_hash"),
        "input_fingerprint": plan_obj.get("input_fingerprint"),
        "plan_fingerprint": plan_obj.get("plan_fingerprint"),
        "dialect": dialect,
        "boundary": dec.get("boundary"),
        "granularity": dec.get("granularity"),
        "feasible": dec.get("feasible"),
    }
    header = "-- ppds:" + json.dumps(header_meta, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    return (
        header
        + "\n"
        + "-- constraints="
        + json.dumps(constraints, sort_keys=True, ensure_ascii=False)
        + "\n\nSELECT 1 AS ppds_placeholder;\n"
    )


def _feature_id_from_features_obj(features_obj: Dict[str, Any], fallback_stem: str) -> str:
    fid = features_obj.get("feature_id")
    if isinstance(fid, str) and fid.strip():
        return fid.strip()
    return fallback_stem


def _list_feature_files(features_dir: Path) -> List[Path]:
    if not features_dir.exists() or not features_dir.is_dir():
        _raise_config_error(
            "PPDS_FEATURES_DIR_NOT_FOUND",
            f"features-dir not found or not a directory: {features_dir}",
            details={"features_dir": str(features_dir)},
            remediation="Pass an existing directory via --features-dir.",
        )
    files = sorted([p for p in features_dir.iterdir() if p.is_file() and p.suffix.lower() == ".json"])
    if not files:
        _raise_config_error(
            "PPDS_FEATURES_DIR_EMPTY",
            f"No .json feature specs found in: {features_dir}",
            details={"features_dir": str(features_dir)},
            remediation="Put one or more feature spec JSON files in the directory.",
        )
    return files


def cmd_run_batch(args: argparse.Namespace) -> int:
    """
    Run PPDS planning over a directory of feature spec JSONs.

    Output layout:
      out_dir/{feature_id}/plan.json
      out_dir/{feature_id}/query.sql
    Plus an index:
      out_dir/index.json
    """
    policy_obj = _load_json(args.policy)

    # Pre-validate policy shape early
    if "thresholds" not in policy_obj or not isinstance(policy_obj.get("thresholds"), dict):
        _raise_config_error(
            "PPDS_POLICY_INVALID",
            "policy missing required object: thresholds",
            details={"path": args.policy},
            remediation="Ensure policy JSON contains a top-level 'thresholds' object.",
        )

    th = _to_thresholds(policy_obj)
    policy_hash = _sha256_hex(policy_obj)

    features_dir = Path(args.features_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    files = _list_feature_files(features_dir)

    any_failed = False

    for fpath in files:
        try:
            features_obj = _load_json(str(fpath))
            ok, errors = _validate_policy_features(policy_obj, features_obj)
            if not ok:
                raise PPDSException(
                    PPDSProblem(
                        code="PPDS_CONFIG_INVALID",
                        category="config",
                        message="Invalid policy/features configuration",
                        details={"feature_file": str(fpath), "errors": errors},
                        remediation="Fix the feature spec JSON and rerun batch.",
                    ),
                    ExitCode.CONFIG_INVALID,
                )

            feat = _to_feature_spec(features_obj)
            dec = decide(feat, th)

            plan_obj: Dict[str, Any] = {
                "schema_version": 1,
                "created_at": _utc_now_iso(),
                "policy_hash": policy_hash,
                "input_fingerprint": _sha256_hex(features_obj),
                "decision": {
                    "boundary": getattr(dec.boundary, "value", str(dec.boundary)),
                    "granularity": getattr(dec.granularity, "value", str(dec.granularity)),
                    "feasible": bool(dec.feasible),
                    "reason": dec.reason,
                },
                "planner_constraints_json": getattr(dec, "planner_constraints_json", None),
                "scorecard": asdict(dec.scorecard) if hasattr(dec, "scorecard") else None,
            }
            plan_obj["plan_fingerprint"] = _plan_fingerprint(plan_obj)

            feature_id = _feature_id_from_features_obj(features_obj, fpath.stem)
            feature_out = out_dir / feature_id
            feature_out.mkdir(parents=True, exist_ok=True)

            plan_path = feature_out / "plan.json"
            sql_path = feature_out / "query.sql"

            _write_text(plan_path, json.dumps(plan_obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            _write_text(sql_path, _emit_sql_text(plan_obj, args.dialect))

            results.append(
                {
                    "feature_id": feature_id,
                    "feature_file": str(fpath),
                    "status": "accepted" if plan_obj["decision"]["feasible"] else "rejected",
                    "plan_fingerprint": plan_obj["plan_fingerprint"],
                    "plan_path": str(plan_path),
                    "sql_path": str(sql_path),
                }
            )

        except PPDSException as e:
            any_failed = True
            results.append(
                {
                    "feature_id": fpath.stem,
                    "feature_file": str(fpath),
                    "status": "error",
                    "error": _problem_to_dict(e.problem),
                    "exit_code": int(e.exit_code),
                }
            )
            if args.fail_fast:
                break

        except Exception as e:
            any_failed = True
            results.append(
                {
                    "feature_id": fpath.stem,
                    "feature_file": str(fpath),
                    "status": "error",
                    "error": {
                        "code": "PPDS_UNHANDLED_EXCEPTION",
                        "category": "internal",
                        "message": "Unhandled exception in batch",
                        "details": {"error": repr(e)},
                    },
                    "exit_code": int(ExitCode.INTERNAL_ERROR),
                }
            )
            if args.fail_fast:
                break

    index_obj = {
        "schema_version": "ppds.batch/0.1",
        "created_at": _utc_now_iso(),
        "policy_hash": policy_hash,
        "features_dir": str(features_dir),
        "out_dir": str(out_dir),
        "dialect": args.dialect,
        "results": results,
        "ok": not any_failed,
    }

    index_path = out_dir / "index.json"
    _write_text(index_path, json.dumps(index_obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    if args.format in ("json", "jsonl"):
        _print_payload({"ok": not any_failed, "index": str(index_path), "count": len(results)}, args.format)
    else:
        print(f"Wrote batch index: {index_path}")
        print(f"Processed {len(results)} feature specs (ok={not any_failed})")

    return 0 if not any_failed else int(ExitCode.RUNTIME_ERROR)


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
