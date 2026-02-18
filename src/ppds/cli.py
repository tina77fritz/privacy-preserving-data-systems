# src/ppds/cli.py
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .budget import BudgetLedger, SpendEvent
from .errors import ExitCode, PPDSException, PPDSProblem
from .planner import decide, plan_counterfactuals
from .types import (
    Boundary,
    FeatureSpec,
    FieldSpec,
    Granularity,
    JoinKeySpec,
    PolicyThresholds,
)

# =============================================================================
# Helpers
# =============================================================================


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(obj)).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_fingerprint(plan_obj: Dict[str, Any]) -> str:
    tmp = dict(plan_obj)
    tmp.pop("plan_fingerprint", None)
    return _sha256_hex(tmp)


def _problem_to_dict(p: PPDSProblem) -> Dict[str, Any]:
    # Support both dataclass and non-dataclass PPDSProblem implementations.
    if is_dataclass(p):
        d = asdict(p)
    else:
        d = {
            "code": getattr(p, "code", "PPDS_UNKNOWN_ERROR"),
            "category": getattr(p, "category", "internal"),
            "message": getattr(p, "message", "Unknown error"),
            "details": getattr(p, "details", {}),
            "remediation": getattr(p, "remediation", None),
        }
    if d.get("remediation") is None:
        d.pop("remediation", None)
    return d


def _print_payload(payload: Dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str))
    elif fmt == "jsonl":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    else:
        # text mode
        pass


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


def _write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _require_keys(obj: Dict[str, Any], keys: List[str], where: str) -> List[str]:
    missing = [k for k in keys if k not in obj]
    return [f"{where}: missing required key '{k}'" for k in missing]


def _validate_policy_features(policy: Dict[str, Any], features: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    errors += _require_keys(policy, ["thresholds"], "policy")
    errors += _require_keys(features, ["feature_id", "fields"], "features")

    if "fields" in features and not isinstance(features["fields"], list):
        errors.append("features: 'fields' must be a list")
    if "thresholds" in policy and not isinstance(policy["thresholds"], dict):
        errors.append("policy: 'thresholds' must be an object")

    return (len(errors) == 0), errors


def _to_thresholds(policy: Dict[str, Any]) -> PolicyThresholds:
    th = policy["thresholds"]

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
    fields: List[FieldSpec] = []
    for f in (features.get("fields", []) or []):
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

    join_keys: List[JoinKeySpec] = []
    for jk in (features.get("join_keys", []) or []):
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
        if args.format in ("json", "jsonl"):
            _print_payload({"ok": True}, args.format)
        else:
            print("OK: configs are valid")
        return 0

    payload = {"ok": False, "errors": errors}
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
            _print_payload({"ok": False, "errors": errors}, args.format)
        else:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
        return int(ExitCode.CONFIG_INVALID)

    th = _to_thresholds(policy)
    feat = _to_feature_spec(features)

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
        "schema_version": 1,
        "created_at": _utc_now_iso(),
        "policy_hash": _sha256_hex(policy),
        "input_fingerprint": _sha256_hex(features),
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
            {"ok": True, "out": str(args.out), "plan_fingerprint": plan_obj["plan_fingerprint"]},
            args.format,
        )
    else:
        print(f"Wrote plan: {args.out}")

    # Integration tests expect success codes; feasibility is encoded in plan.json.
    return 0


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
        "schema_version": plan_obj.get("schema_version"),
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
        header
        + "\n"
        + "-- constraints="
        + json.dumps(constraints, sort_keys=True, ensure_ascii=False)
        + "\n\nSELECT 1 AS ppds_placeholder;\n"
    )
    _write_text(args.out, sql)

    if args.format in ("json", "jsonl"):
        _print_payload({"ok": True, "out": str(args.out)}, args.format)
    else:
        print(f"Wrote SQL: {args.out}")

    return 0


def cmd_demo(args: argparse.Namespace) -> int:
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
        bucketizations={"age": 80, "location": 500},
        policy_tags=["age", "location"],
        support_hint={Granularity.ITEM: 80, Granularity.CLUSTER: 20000, Granularity.AGGREGATE: 10_000_000},
    )

    d = decide(f, th)
    out = {
        "boundary": d.boundary.value,
        "granularity": d.granularity.value,
        "feasible": d.feasible,
        "risk": d.scorecard.risk,
        "components": {"L": d.scorecard.L, "U": d.scorecard.U, "I": d.scorecard.I, "R": d.scorecard.R},
        "contributors": d.scorecard.contributors,
        "reason": d.reason,
    }

    if args.format in ("json", "jsonl"):
        _print_payload(out, args.format)
        return 0

    print(json.dumps(out, indent=2, default=str))

    cfs = plan_counterfactuals(f, th, target_g=Granularity.ITEM)
    for x in cfs[:5]:
        sc = x["scorecard"]
        print(
            "- {} feasible={} risk={:.3f} (L={:.2f},U={:.2f},I={:.2f},R={:.2f})".format(
                x["edit"],
                x["feasible_at_target"],
                sc.risk,
                sc.L,
                sc.U,
                sc.I,
                sc.R,
            )
        )

    ledger = BudgetLedger()
    cap = 1.0
    today = date(2026, 1, 30)
    for i in range(9):
        ledger.commit(SpendEvent(f.feature_id, today.replace(day=today.day - i), epsilon=0.1))
    eps30, _ = ledger.window_spend(f.feature_id, 30, today)
    print(
        "spent_eps_30d={:.2f} cap={:.2f} can_spend_next_0.1={}".format(
            eps30,
            cap,
            ledger.can_spend(f.feature_id, 30, today, cap, 0.0, 0.1),
        )
    )
    print(
        "adaptive_eps_for_next_21_releases={:.4f}".format(
            ledger.adaptive_eps(f.feature_id, 30, today, cap, planned_releases_left=21)
        )
    )
    return 0


# =============================================================================
# Parser + entrypoint
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ppds")
    sub = parser.add_subparsers(dest="cmd", required=False)

    fmt_choices = ["text", "json", "jsonl"]

    p_val = sub.add_parser("validate", help="Validate policy/features configs")
    p_val.add_argument("--policy", required=True)
    p_val.add_argument("--features", required=True)
    # define per-subcommand so tests can pass it after command name
    p_val.add_argument("--format", default="text", choices=fmt_choices)
    p_val.set_defaults(func=cmd_validate)

    p_plan = sub.add_parser("plan", help="Generate an auditable plan.json")
    p_plan.add_argument("--policy", required=True)
    p_plan.add_argument("--features", required=True)
    p_plan.add_argument("--out", required=True)
    p_plan.add_argument("--format", default="text", choices=fmt_choices)
    p_plan.set_defaults(func=cmd_plan)

    p_sql = sub.add_parser("emit-sql", help="Emit SQL from plan.json")
    p_sql.add_argument("--plan", required=True)
    p_sql.add_argument("--dialect", default="spark")
    p_sql.add_argument("--out", required=True)
    p_sql.add_argument("--format", default="text", choices=fmt_choices)
    p_sql.set_defaults(func=cmd_emit_sql)

    p_demo = sub.add_parser("demo", help="Run built-in demo")
    p_demo.add_argument("--format", default="text", choices=fmt_choices)
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Console-script entrypoint: the installed `ppds` script imports this symbol.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2

    try:
        return int(args.func(args))
    except PPDSException as e:
        payload = {"ok": False, "error": _problem_to_dict(e.problem), "exit_code": int(e.exit_code)}
        fmt = getattr(args, "format", "text")
        if fmt in ("json", "jsonl"):
            _print_payload(payload, fmt)
        else:
            err = payload["error"]
            print(f"ERROR[{err.get('code','PPDS_ERROR')}]: {err.get('message')}", file=sys.stderr)
            if err.get("remediation"):
                print(f"REMEDIATION: {err['remediation']}", file=sys.stderr)
            print(f"DETAILS: {err.get('details', {})}", file=sys.stderr)
        return int(e.exit_code)
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
        fmt = getattr(args, "format", "text")
        if fmt in ("json", "jsonl"):
            _print_payload(payload, fmt)
        else:
            print(f"ERROR: {repr(e)}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
