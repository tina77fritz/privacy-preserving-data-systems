# src/ppds/cli.py
"""
PPDS CLI with fail-closed policy gate.

Key behaviors (commit requirements):
- Enforce hard rejection when inputs violate LPS thresholds (default: exit code 2).
- Emit structured rejection reasons for audit review (JSON output).
- Ensure deterministic behavior across runs (stable serialization + float rounding + optional RNG seeding).

Exit codes:
- 0: ALLOW
- 2: REJECT (policy gate fail-closed)
- 1: CLI usage error (arg parsing only; gate failures still return 2)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ppds.config import load_policy_config
from ppds.lps.scorer import compute_lps
from ppds.policy_gate import evaluate_policy_gate, EXIT_ALLOW, EXIT_REJECT


def _eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _read_file_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def _read_file_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _read_stdin_text() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _parse_yaml_or_json(text: str) -> Any:
    # YAML is a superset of JSON; safe_load handles both deterministically.
    return yaml.safe_load(text)


def _ensure_mapping(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"Input must be a JSON/YAML object (mapping), got: {type(obj).__name__}")
    return obj


def _resolve_input_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        obj = _parse_yaml_or_json(_read_file_text(args.input_file))
        return _ensure_mapping(obj)

    if args.input_json:
        # Prefer JSON parsing for clearer errors; fallback to YAML.
        try:
            obj = json.loads(args.input_json)
        except Exception:
            obj = _parse_yaml_or_json(args.input_json)
        return _ensure_mapping(obj)

    stdin_text = _read_stdin_text()
    if stdin_text.strip():
        obj = _parse_yaml_or_json(stdin_text)
        return _ensure_mapping(obj)

    raise ValueError("No input provided. Use --input-file, --input-json, or pipe JSON/YAML via STDIN.")


def _seed_determinism(seed: int) -> None:
    """
    Best-effort determinism:
    - Seed Python RNG
    - Seed NumPy RNG if available
    Note: PYTHONHASHSEED must be set before interpreter start to fully control hash randomization.
    We still avoid hash-order dependence by producing canonicalized, key-sorted JSON outputs.
    """
    random.seed(seed)
    try:
        import numpy as np  # type: ignore
        np.random.seed(seed)
    except Exception:
        pass


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PPDS CLI (fail-closed policy gate)")

    p.add_argument("--policy", required=True, help="Path to the policy YAML file.")
    p.add_argument(
        "--lps-threshold",
        type=float,
        help="Override LPS threshold from policy (for controlled evaluation only).",
    )

    # Fail-closed by default.
    p.add_argument(
        "--soft-fail",
        action="store_true",
        help="Do not hard-reject on violation (kept only for controlled evaluation).",
    )

    p.add_argument(
        "--float-ndigits",
        type=int,
        default=8,
        help="Number of digits to round floats for deterministic JSON output.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for deterministic behavior (best-effort).",
    )

    inp = p.add_mutually_exclusive_group(required=False)
    inp.add_argument("--input-file", help="Path to input payload (JSON or YAML).")
    inp.add_argument("--input-json", help="Input payload as an inline JSON string.")

    p.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format. JSON is recommended for CI/audit pipelines.",
    )

    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        _seed_determinism(args.seed)

        # Load policy (typed config)
        policy = load_policy_config(args.policy)

        # Also load raw policy bytes for checksum/audit metadata.
        policy_bytes = _read_file_bytes(args.policy)

        input_payload = _resolve_input_payload(args)

        decision = evaluate_policy_gate(
            policy_path=args.policy,
            policy_bytes=policy_bytes,
            policy_threshold=policy.thresholds.lps_max,
            input_payload=input_payload,
            compute_lps_fn=compute_lps,
            threshold_override=args.lps_threshold,
            hard_reject=not args.soft_fail,
            float_ndigits=int(args.float_ndigits),
        )

        if args.output == "json":
            print(decision.to_json(sort_keys=True, indent=2))
        else:
            # Human-readable text output (still deterministic because JSON inside is canonicalized).
            print(f"Decision: {decision.decision}")
            print(f"Exit code: {decision.exit_code}")
            print("Details:")
            print(decision.to_json(sort_keys=True, indent=2))

        sys.exit(decision.exit_code)

    except Exception as e:
        # This is a CLI-level error (e.g., invalid args, missing files).
        # We keep it distinct from gate evaluation errors, which are handled fail-closed inside the gate.
        _eprint(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
