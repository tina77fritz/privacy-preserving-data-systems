# src/ppds/cli.py
"""
PPDS CLI.

This CLI is designed for:
- Local evaluation of an input payload against a privacy policy (YAML).
- CI usage (non-zero exit code on policy violation, when configured).
- Producing an auditable LPS score and an explainable breakdown.

Input formats:
- JSON or YAML
- Provided via:
  1) --input-file PATH
  2) --input-json '{"..."}'
  3) STDIN (if piped)

Exit codes:
- 0: Success (no violation, or violation but policy does not reject)
- 2: Policy violation AND policy.thresholds.reject_on_violation == true
- 1: Usage / input / runtime error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from ppds.config import load_policy_config
from ppds.lps.scorer import compute_lps


def _eprint(*args: Any) -> None:
    """Print to stderr."""
    print(*args, file=sys.stderr)


def _read_stdin_text() -> str:
    """Read all text from STDIN. Returns empty string if STDIN is a TTY."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _load_text_from_file(path: str) -> str:
    """Read a text file as UTF-8."""
    p = Path(path)
    return p.read_text(encoding="utf-8")


def _parse_yaml_or_json(text: str) -> Any:
    """
    Parse YAML or JSON into a Python object.

    YAML is a superset of JSON, so yaml.safe_load handles both.
    """
    try:
        obj = yaml.safe_load(text)
    except Exception as e:
        raise ValueError(f"Failed to parse input as YAML/JSON: {e}") from e
    return obj


def _ensure_mapping(obj: Any) -> Dict[str, Any]:
    """Ensure the parsed input is a dictionary-like mapping."""
    if not isinstance(obj, dict):
        raise ValueError(
            f"Input must be a JSON/YAML object (mapping), got: {type(obj).__name__}"
        )
    return obj


def _serialize_breakdown(breakdown: Any) -> Any:
    """
    Convert a breakdown object into a JSON-serializable structure.

    Supported patterns:
    - breakdown.to_dict()
    - dataclass instance
    - plain dict
    - fallback to __dict__ or str()
    """
    if breakdown is None:
        return None
    if isinstance(breakdown, dict):
        return breakdown
    if hasattr(breakdown, "to_dict") and callable(getattr(breakdown, "to_dict")):
        return breakdown.to_dict()
    if is_dataclass(breakdown):
        return asdict(breakdown)
    if hasattr(breakdown, "__dict__"):
        return dict(breakdown.__dict__)
    return str(breakdown)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PPDS CLI")

    parser.add_argument(
        "--policy",
        required=True,
        help="Path to the policy YAML file (loaded via ppds.config.load_policy_config).",
    )

    parser.add_argument(
        "--lps-threshold",
        type=float,
        help="Override LPS threshold from policy (for controlled evaluation only).",
    )

    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--input-file",
        help="Path to input payload (JSON or YAML).",
    )
    input_group.add_argument(
        "--input-json",
        help="Input payload as an inline JSON string.",
    )

    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format. 'json' is recommended for CI pipelines.",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce stderr noise (still prints violations and errors).",
    )

    return parser


def _resolve_input_payload(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Resolve input payload from:
    1) --input-file
    2) --input-json
    3) STDIN
    """
    if args.input_file:
        text = _load_text_from_file(args.input_file)
        obj = _parse_yaml_or_json(text)
        return _ensure_mapping(obj)

    if args.input_json:
        # Use JSON parsing first for clearer error messages, then fallback to YAML.
        try:
            obj = json.loads(args.input_json)
        except Exception:
            obj = _parse_yaml_or_json(args.input_json)
        return _ensure_mapping(obj)

    stdin_text = _read_stdin_text()
    if stdin_text.strip():
        obj = _parse_yaml_or_json(stdin_text)
        return _ensure_mapping(obj)

    raise ValueError(
        "No input provided. Use --input-file, --input-json, or pipe JSON/YAML via STDIN."
    )


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        policy = load_policy_config(args.policy)

        # Determine the effective threshold.
        threshold = (
            args.lps_threshold
            if args.lps_threshold is not None
            else policy.thresholds.lps_max
        )

        if args.lps_threshold is not None and not args.quiet:
            _eprint(
                f"NOTE: Using overridden LPS threshold {threshold} "
                f"(policy lps_max={policy.thresholds.lps_max})."
            )

        input_data = _resolve_input_payload(args)

        # Assumption: compute_lps accepts a Python mapping and returns (score, breakdown).
        lps_score, breakdown = compute_lps(input_data)
        breakdown_obj = _serialize_breakdown(breakdown)

        violated = bool(lps_score > threshold)

        if args.output == "json":
            out = {
                "lps_score": lps_score,
                "threshold": threshold,
                "violated": violated,
                "reject_on_violation": bool(policy.thresholds.reject_on_violation),
                "breakdown": breakdown_obj,
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"LPS score: {lps_score}")
            print(f"Threshold: {threshold}")
            print("LPS breakdown:")
            print(json.dumps(breakdown_obj, ensure_ascii=False, indent=2))

        if violated:
            _eprint(
                f"Policy violation: LPS {lps_score} exceeds threshold {threshold}"
            )
            if policy.thresholds.reject_on_violation:
                sys.exit(2)

        sys.exit(0)

    except Exception as e:
        _eprint(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
