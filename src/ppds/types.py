from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Boundary(str, Enum):
    LOCAL = "LOCAL"
    SHUFFLE = "SHUFFLE"
    CENTRAL = "CENTRAL"


class Granularity(str, Enum):
    ITEM = "ITEM"
    CLUSTER = "CLUSTER"
    AGGREGATE = "AGGREGATE"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    dtype: str  # "int", "float", "string", "enum", "timestamp"
    is_sensitive: bool = False
    is_identifier: bool = False
    cardinality_hint: Optional[int] = None  # optional, e.g., NDV guess


@dataclass(frozen=True)
class JoinKeySpec:
    name: str
    stability: float  # 0..1 higher = more stable across windows
    ndv_hint: Optional[int] = None


@dataclass
class FeatureSpec:
    feature_id: str
    description: str
    fields: List[FieldSpec]
    join_keys: List[JoinKeySpec] = field(default_factory=list)
    ttl_days: int = 30
    bucketizations: Dict[str, int] = field(default_factory=dict)  # field -> bucket_count
    privacy_unit: str = "user"  # "user"|"device"|...
    policy_tags: List[str] = field(default_factory=list)  # "age","gender","location","health",...
    # support hints by granularity (if known); otherwise None for cold start
    support_hint: Dict[Granularity, Optional[int]] = field(
        default_factory=lambda: {Granularity.ITEM: None, Granularity.CLUSTER: None, Granularity.AGGREGATE: None}
    )


@dataclass(frozen=True)
class DPConfig:
    boundary: Boundary
    epsilon: float
    delta: float = 0.0
    window_days: int = 30


@dataclass(frozen=True)
class PolicyThresholds:
    # risk caps (0..1 scale)
    tau_boundary: Dict[Boundary, float]
    tau_granularity: Dict[Granularity, float]
    # k threshold for uniqueness guardrails
    k_min: int = 100
    # weights for aggregated risk
    alpha_L: float = 0.30
    alpha_U: float = 0.35
    alpha_I: float = 0.25
    alpha_R: float = 0.10


@dataclass(frozen=True)
class Scorecard:
    L: float
    U: float
    I: float
    R: float
    risk: float
    contributors: Dict[str, List[Tuple[str, float]]]  # component -> [(field, contribution)]


@dataclass(frozen=True)
class Decision:
    boundary: Boundary
    granularity: Granularity
    feasible: bool
    scorecard: Scorecard
    reason: str
