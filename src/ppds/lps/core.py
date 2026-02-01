from __future__ import annotations
from dataclasses import asdict
from typing import Dict, List, Tuple

from ..types import Boundary, Granularity, FeatureSpec, PolicyThresholds, Scorecard


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_linkability(feature: FeatureSpec) -> Tuple[float, List[Tuple[str, float]]]:
    """
    Linkability: driven by stable join surfaces.
    We score join keys by stability and implied cardinality.
    """
    contrib: List[Tuple[str, float]] = []
    if not feature.join_keys:
        return 0.0, contrib

    # normalize by count
    total = 0.0
    for jk in feature.join_keys:
        # stability is primary; NDV amplifies join power modestly
        ndv_factor = 0.0
        if jk.ndv_hint is not None and jk.ndv_hint > 0:
            # log-ish scaling to avoid dominance
            ndv_factor = min(1.0, (jk.ndv_hint ** 0.5) / 1000.0)
        c = 0.8 * _clamp01(jk.stability) + 0.2 * _clamp01(ndv_factor)
        contrib.append((jk.name, c))
        total += c

    # higher TTL increases temporal linkability (more time to correlate)
    ttl_factor = _clamp01(feature.ttl_days / 90.0)
    L = _clamp01((total / max(1, len(feature.join_keys))) * (0.7 + 0.3 * ttl_factor))
    return L, contrib


def compute_uniqueness(feature: FeatureSpec, g: Granularity, k_min: int) -> Tuple[float, List[Tuple[str, float]]]:
    """
    Uniqueness: small-cell exposure. Higher risk when support is small.
    Uses support_hint if present; otherwise uses conservative approximation from schema complexity.
    """
    contrib: List[Tuple[str, float]] = []
    support = feature.support_hint.get(g)

    if support is not None and support > 0:
        # risk ~ 1 / (support/k_min) capped to 1
        ratio = support / float(k_min)
        U = _clamp01(1.0 / max(1.0, ratio))
        return U, [("support_hint", U)]

    # Cold start: approximate "cell sparsity pressure"
    # based on bucket counts and high-cardinality dimensions.
    pressure = 0.0
    for f in feature.fields:
        if f.is_identifier:
            pressure += 1.0
            contrib.append((f.name, 1.0))
            continue

        buckets = feature.bucketizations.get(f.name)
        if buckets is not None:
            # more buckets => more sparsity risk
            c = _clamp01(buckets / 200.0)
            pressure += c
            contrib.append((f.name, c))
        elif f.cardinality_hint is not None:
            c = _clamp01((f.cardinality_hint ** 0.5) / 200.0)
            pressure += c
            contrib.append((f.name, c))
        else:
            # unknown dimension: treat as moderate
            c = 0.15
            pressure += c
            contrib.append((f.name, c))

    # granularity affects effective cell count
    g_factor = {Granularity.ITEM: 1.0, Granularity.CLUSTER: 0.6, Granularity.AGGREGATE: 0.25}[g]
    U = _clamp01((pressure / max(1, len(feature.fields))) * g_factor)
    return U, contrib


def compute_inferability(feature: FeatureSpec) -> Tuple[float, List[Tuple[str, float]]]:
    """
    Inferability: proxy leakage toward sensitive attributes.
    Cold start uses a conservative proxy score based on presence of sensitive fields and combinations.
    """
    contrib: List[Tuple[str, float]] = []
    sens = [f for f in feature.fields if f.is_sensitive]
    if not sens:
        return 0.05, [("no_sensitive_declared", 0.05)]

    # More sensitive fields and higher granularity-like bucket counts increases proxy risk
    base = 0.15 + 0.12 * min(5, len(sens))
    for f in sens:
        buckets = feature.bucketizations.get(f.name)
        c = 0.25
        if buckets is not None:
            c = _clamp01(0.15 + buckets / 500.0)
        contrib.append((f.name, c))
        base += 0.05 * c

    # join keys amplify inferability through cross-table enrichment
    jk_amp = 0.0
    if feature.join_keys:
        jk_amp = 0.15 * _clamp01(sum(jk.stability for jk in feature.join_keys) / len(feature.join_keys))
    I = _clamp01(base + jk_amp)
    return I, contrib


def compute_policy_penalty(feature: FeatureSpec) -> Tuple[float, List[Tuple[str, float]]]:
    """
    Policy penalty: rule-based "regulated dimension" multiplier.
    """
    contrib: List[Tuple[str, float]] = []
    penalty = 0.0
    tag_weights = {
        "health": 0.50,
        "precise_location": 0.45,
        "financial": 0.40,
        "children": 0.60,
        "age": 0.20,
        "gender": 0.15,
        "location": 0.20,
    }
    for t in feature.policy_tags:
        w = tag_weights.get(t, 0.10)
        contrib.append((t, w))
        penalty += w
    return _clamp01(penalty), contrib


def compute_scorecard(feature: FeatureSpec, g: Granularity, th: PolicyThresholds) -> Scorecard:
    L, cL = compute_linkability(feature)
    U, cU = compute_uniqueness(feature, g=g, k_min=th.k_min)
    I, cI = compute_inferability(feature)
    R, cR = compute_policy_penalty(feature)

    risk = _clamp01(th.alpha_L * L + th.alpha_U * U + th.alpha_I * I + th.alpha_R * R)
    return Scorecard(
        L=L, U=U, I=I, R=R, risk=risk,
        contributors={"L": cL, "U": cU, "I": cI, "R": cR}
    )


def feasible_boundary(score: Scorecard, b: Boundary, th: PolicyThresholds) -> bool:
    return score.risk <= th.tau_boundary[b]


def feasible_granularity(score: Scorecard, g: Granularity, th: PolicyThresholds) -> bool:
    return score.risk <= th.tau_granularity[g]
