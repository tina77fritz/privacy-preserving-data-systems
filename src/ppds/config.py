"""
Policy config loading for PPDS CLI.

Loads YAML/JSON policy files and returns typed config objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass(frozen=True)
class PolicyThresholdsConfig:
    """CLI-level thresholds for LPS evaluation."""

    lps_max: float = 0.5
    reject_on_violation: bool = True


@dataclass(frozen=True)
class PolicyConfig:
    """Loaded policy configuration."""

    raw: Dict[str, Any]
    thresholds: PolicyThresholdsConfig

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PolicyConfig:
        th = d.get("thresholds") or {}
        thresholds = PolicyThresholdsConfig(
            lps_max=float(th.get("lps_max", 0.5)),
            reject_on_violation=bool(th.get("reject_on_violation", True)),
        )
        return cls(raw=d, thresholds=thresholds)


def load_policy_config(path: str) -> PolicyConfig:
    """
    Load a policy configuration from a YAML or JSON file.

    The file must contain a mapping. If a 'thresholds' key exists, it may
    specify lps_max and reject_on_violation for CLI behavior.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    obj = yaml.safe_load(text)
    if not isinstance(obj, dict):
        raise ValueError(f"Policy file must be a YAML/JSON object, got {type(obj).__name__}")
    return PolicyConfig.from_dict(obj)
