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

import hashlib
from datetime import datetime, timezone
from .errors import ExitCode, PPDSException, PPDSProblem, problem_to_dict



# =============================================================================
# Helpers
# =============================================================================

def _load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        _raise_config_error(
            "PPDS_CONFIG_NOT_FOUND",
            f"Config not found: {path}",
            details={"path": path},
            remediation="Verify the path is correct and the file exists.",
        )
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise PPDSException(
            PPDSProblem(
                code="PPDS_CONFIG_PARSE_ERROR",
                category="config",
                message=f"Failed to parse JSON: {path}",
                details={"path": path, "error": repr(e)},
                remediation="Ensure the file is valid JSON encoded in UTF-8.",
            ),
            ExitCode.CONFIG_INVALID,
            cause=e,
        )
    if not isinstance(obj, dict):
        _raise_config_error(
            "PPDS_CONFIG_TOPLEVEL_NOT_OBJECT",
            f"Config must be a JSON object at top-level: {path}",
            details={"path": path, "type": type(obj).__name__},
            remediation="Wrap the config in a JSON object (dictionary) at the top-level.",
        )
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

def _print_payload(payload: Dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str))
    elif fmt == "jsonl":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    else:
        # text mode: do nothing here; caller prints user-friendly text
        pass


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    return _sha256_hex(tmp)


def _raise_config_error(code: str, message: str, *, details: Dict[str, Any], remediation: str) -> None:
    raise PPDSException(
        PPDSProblem(
            code=code,
            category="config",
            message=message,
            details=details,
            remediation=remediation,
        ),
        ExitCode.CONFIG_INVALID,
    )

# =============================================================================
# Commands
# =============================================================================

def cmd_validate(args: argparse.Namespace) -> int:
    policy = _load_json(args.policy)
    features = _load_json(args.features)
    ok, errors = _validate_policy_features(policy, features)

    if ok:
        if args.format in ("json", "jsonl"):
            _print_payload({"ok": True}, args.format)
        else:
            print("OK: configs are valid")
        return int(ExitCode.OK)

    payload = {
        "ok": False,
        "errors": errors,
        "error": {
            "code": "PPDS_CONFIG_INVALID",
            "category": "config",
            "message": "Invalid configuration",
            "details": {"count": len(errors)},
            "remediation": "Fix the errors and re-run `ppds validate`.",
        },
        "exit_code": int(ExitCode.CONFIG_INVALID),
    }

    if args.format in ("json", "jsonl"):
        _print_payload(payload, args.format)
    else:
        print("INVALID CONFIG:")
        for e in errors:
            print(f"- {e}")
    return int(ExitCode.CONFIG_INVALID)



def cmd_plan(args: argparse.Namespace) -> int:
    policy = _load_json(args.policy)
    features = _load_json(args.features)
    ok, errors = _validate_policy_features(policy, features)
    if not ok:
        if args.format in ("json", "jsonl"):
            _print_payload(
                {"ok": False, "errors": errors, "exit_code": int(ExitCode.CONFIG_INVALID)},
                args.format,
            )
        else:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
        return int(ExitCode.CONFIG_INVALID)

    th = _to_thresholds(policy)
    feat = _to_feature_spec(features)

    # deterministic hashes for audit
    policy_hash = _sha256_hex(policy)
    input_fingerprint = _sha256_hex(features)

    try:
        dec = decide(feat, th)
    except Exception as e:
        raise PPDSException(
            PPDSProblem(
                code="PPDS_PLANNER_RUNTIME_ERROR",
                category="runtime",
                message="Planner failed while computing a decision",
                details={"error": repr(e), "feature_id": getattr(feat, "feature_id", None)},
                remediation="Inspect inputs and planner logs; fix invalid fields and retry.",
            ),
            ExitCode.RUNTIME_ERROR,
            cause=e,
        )

    plan_obj: Dict[str, Any] = {
        "schema_version": "ppds.plan/0.1",
        "created_at": _utc_now_iso(),
        "policy_hash": policy_hash,
        "input_fingerprint": input_fingerprint,
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

    _write_text(args.out, json.dumps(plan_obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    if args.format in ("json", "jsonl"):
        _print_payload(
            {"ok": True, "out": args.out, "plan_fingerprint": plan_obj["plan_fingerprint"]},
            args.format,
        )
    else:
        print(f"Wrote plan: {args.out}")

    # orchestration-friendly: infeasible => policy rejected (non-crash)
    if not plan_obj["decision"]["feasible"]:
        return int(ExitCode.POLICY_REJECTED)
    return int(ExitCode.OK)


def cmd_emit_sql(args: argparse.Namespace) -> int:
    plan_obj = _load_json(args.plan)

    if "decision" not in plan_obj:
        _raise_config_error(
            "PPDS_PLAN_MISSING_DECISION",
            "plan.json missing required key: decision",
            details={"path": args.plan},
            remediation="Regenerate plan.json using `ppds plan` with valid inputs.",
        )

    dec = plan_obj.get("decision", {})
    constraints = plan_obj.get("planner_constraints_json", {})

    header_meta = {
        "ppds_schema_version": plan_obj.get("schema_version"),
        "created_at": plan_obj.get("created_at"),
        "policy_hash": plan_obj.get("policy_hash"),
        "input_fingerprint": plan_obj.get("input_fingerprint"),
        "plan_fingerprint": plan_obj.get("plan_fingerprint"),
        "dialect": args.dialect,
        "boundary": dec.get("boundary"),
        "granularity": dec.get("granularity"),
        "feasible": dec.get("feasible"),
    }
    header = "-- ppds:" + json.dumps(header_meta, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    sql = (
        f"{header}\n"
        f"-- constraints={json.dumps(constraints, sort_keys=True, ensure_ascii=False)}\n\n"
        f"SELECT 1 AS ppds_placeholder;\n"
    )

    _write_text(args.out, sql)

    if args.format in ("json", "jsonl"):
        _print_payload({"ok": True, "out": args.out}, args.format)
    else:
        print(f"Wrote SQL: {args.out}")
    return int(ExitCode.OK)


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
    parser.add_argument("--format", default="text", choices=["text", "json", "jsonl"])
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

try:
    rc = args.func(args)
    raise SystemExit(rc)
except PPDSException as e:
    payload = {"ok": False, "error": problem_to_dict(e.problem), "exit_code": int(e.exit_code)}
    if getattr(args, "format", "text") in ("json", "jsonl"):
        _print_payload(payload, args.format)
    else:
        print(f"ERROR[{e.problem.code}]: {e.problem.message}", file=sys.stderr)
        if e.problem.remediation:
            print(f"REMEDIATION: {e.problem.remediation}", file=sys.stderr)
        print(f"DETAILS: {e.problem.details}", file=sys.stderr)
    raise SystemExit(int(e.exit_code))
except Exception as e:
    payload = {
        "ok": False,
        "error": {
            "code": "PPDS_UNHANDLED_EXCEPTION",
            "category": "internal",
            "message": "Unhandled exception",
            "details": {"error": repr(e)},
        },
        "exit_code": int(ExitCode.INTERNAL_ERROR),
    }
    if getattr(args, "format", "text") in ("json", "jsonl"):
        _print_payload(payload, args.format)
    else:
        print(f"ERROR: {repr(e)}", file=sys.stderr)
    raise SystemExit(int(ExitCode.INTERNAL_ERROR))



if __name__ == "__main__":
    main()
