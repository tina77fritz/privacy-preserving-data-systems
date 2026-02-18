from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional


class ExitCode(int, Enum):
    OK = 0
    CONFIG_INVALID = 10
    POLICY_REJECTED = 20
    RUNTIME_ERROR = 30
    DEPENDENCY_ERROR = 40
    INTERNAL_ERROR = 50


@dataclass(frozen=True)
class PPDSProblem:
    code: str                 # stable machine code, e.g. "PPDS_POLICY_THRESHOLD_EXCEEDED"
    category: str             # "config" | "policy" | "runtime" | "dependency" | "internal"
    message: str              # short human message
    details: Dict[str, Any]   # structured details for audit/debug
    remediation: Optional[str] = None  # actionable next step


class PPDSException(Exception):
    def __init__(
        self,
        problem: PPDSProblem,
        exit_code: ExitCode,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(problem.message)

from dataclasses import asdict
from typing import Any, Dict

def problem_to_dict(p: "PPDSProblem") -> Dict[str, Any]:
    d = asdict(p)
    if d.get("remediation") is None:
        d.pop("remediation", None)
    return d
