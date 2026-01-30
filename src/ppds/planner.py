from __future__ import annotations
from dataclasses import replace
from typing import Dict, List, Tuple

from .types import Boundary, Granularity, FeatureSpec, PolicyThresholds, Decision
from .lps import compute_scorecard, feasible_boundary, feasible_granularity


EDIT_BUCKETIZE = "bucketize"
EDIT_DROP_FIELD = "drop_field"
EDIT_DOWNGRADE_GRANULARITY = "downgrade_granularity"


def decide(feature: FeatureSpec, th: PolicyThresholds) -> Decision:
    """
    Choose the finest feasible granularity under the least restrictive feasible boundary.
    (You can invert preference ordering if your org prefers Central over Shuffle, etc.)
    """
    # Boundary preference: CENTRAL (best utility) -> SHUFFLE -> LOCAL
    boundary_order = [Boundary.CENTRAL, Boundary.SHUFFLE, Boundary.LOCAL]
    gran_order = [Granularity.ITEM, Granularity.CLUSTER, Granularity.AGGREGATE]

    best = None
    for b in boundary_order:
        for g in gran_order:
            sc = compute_scorecard(feature, g=g, th=th)
            if feasible_boundary(sc, b, th) and feasible_granularity(sc, g, th):
                return Decision(boundary=b, granularity=g, feasible=True, scorecard=sc, reason="feasible")
            best = best or (b, g, sc)

    # If nothing feasible, return most conservative recommendation
    b, g, sc = best
    return Decision(boundary=Boundary.LOCAL, granularity=Granularity.AGGREGATE, feasible=False, scorecard=sc,
                    reason="no_feasible_option_under_thresholds")


def plan_counterfactuals(feature: FeatureSpec, th: PolicyThresholds, target_g: Granularity = Granularity.ITEM) -> List[Dict]:
    """
    Return candidate edits with predicted scorecards, ordered by lowest risk then minimal edit size.
    """
    candidates: List[Tuple[str, FeatureSpec]] = []

    # 1) Bucketization coarsen for sensitive dims
    for f in feature.fields:
        if f.is_sensitive:
            cur = feature.bucketizations.get(f.name)
            if cur is not None:
                # coarsen by halving bucket count (>=2)
                new_b = max(2, cur // 2)
                if new_b != cur:
                    new_feat = replace(feature, bucketizations={**feature.bucketizations, f.name: new_b})
                    candidates.append((f"{EDIT_BUCKETIZE}:{f.name}:{cur}->{new_b}", new_feat))

    # 2) Drop one high-risk dimension (start with identifiers or sensitive)
    for f in feature.fields:
        if f.is_identifier or f.is_sensitive:
            new_fields = [x for x in feature.fields if x.name != f.name]
            new_buck = {k: v for k, v in feature.bucketizations.items() if k != f.name}
            new_feat = replace(feature, fields=new_fields, bucketizations=new_buck)
            candidates.append((f"{EDIT_DROP_FIELD}:{f.name}", new_feat))

    # 3) Granularity downgrade options are evaluated in decision(), but here we provide explicit “accept downgrade”
    # as a suggestion if target is infeasible.

    out = []
    for edit, f2 in candidates:
        sc = compute_scorecard(f2, g=target_g, th=th)
        ok = feasible_granularity(sc, target_g, th)
        out.append({
            "edit": edit,
            "target_granularity": target_g.value,
            "feasible_at_target": ok,
            "scorecard": sc,
        })

    # Sort: feasible first, then lower risk
    out.sort(key=lambda x: (not x["feasible_at_target"], x["scorecard"].risk))
    return out
