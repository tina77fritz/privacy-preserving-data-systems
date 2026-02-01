from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from typing import Any, Dict, List, Tuple, Union

from .types import Boundary, Granularity, FeatureSpec, PolicyThresholds, Decision
from .lps import compute_scorecard, feasible_boundary, feasible_granularity


EDIT_BUCKETIZE = "bucketize"
EDIT_DROP_FIELD = "drop_field"
EDIT_DOWNGRADE_GRANULARITY = "downgrade_granularity"


# =============================================================================
# Planner Binding (ContractBundle/Decision -> PlannerConstraint)
# =============================================================================

KeyList = Union[List[str], str]  # list[str] or "*" for "all"


@dataclass(frozen=True)
class PlannerConstraint:
    """
    Planner-enforceable logical constraints compiled from a privacy decision.

    NOTE: This is *logical representation binding* (allowed keys/joins/support),
    not TiDB physical plan binding (join order, index hints, etc.).
    """
    boundary: str
    granularity: str
    forbid_group_by_keys: KeyList
    forbid_joins_on: KeyList
    min_group_cardinality: int
    require_pre_aggregation: bool

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compile_to_planner_constraints(
    feature: FeatureSpec,
    decision: Decision,
    th: PolicyThresholds,
) -> PlannerConstraint:
    """
    Compile (feature spec + decision + thresholds) -> PlannerConstraint.

    This makes the "binding" explicit:
    - If granularity != ITEM, forbid grouping by item-level identifiers.
    - If CLUSTER or AGGREGATE, enforce a minimum support threshold (k).
    - Optionally forbid join keys when linkability is deemed high risk (policy-driven).

    IMPORTANT: This function does NOT parse SQL. It outputs a constraint artifact
    that a database planner/runtime gate can validate against a plan signature.
    """
    g = decision.granularity
    b = decision.boundary

    # Heuristic defaults (keep minimal / conservative)
    item_level_keys = [f.name for f in feature.fields if getattr(f, "is_identifier", False)]
    join_keys = [jk.name for jk in getattr(feature, "join_keys", [])]  # optional field on FeatureSpec

    # Use policy k_min if present; otherwise fallback
    k_min = int(getattr(th, "k_min", 1))

    g_name = getattr(g, "value", str(g))
    b_name = getattr(b, "value", str(b))

    if g == Granularity.ITEM:
        return PlannerConstraint(
            boundary=str(b_name),
            granularity=str(g_name),
            forbid_group_by_keys=[],
            forbid_joins_on=[],
            min_group_cardinality=1,
            require_pre_aggregation=False,
        )

    if g == Granularity.CLUSTER:
        return PlannerConstraint(
            boundary=str(b_name),
            granularity=str(g_name),
            forbid_group_by_keys=item_level_keys,      # cannot group by item-level ids
            forbid_joins_on=join_keys or [],           # policy may tighten this later
            min_group_cardinality=max(k_min, 2),
            require_pre_aggregation=True,
        )

    # AGGREGATE
    return PlannerConstraint(
        boundary=str(b_name),
        granularity=str(g_name),
        forbid_group_by_keys="*",                     # no grouping keys exposed at release
        forbid_joins_on="*",                          # no joins at release
        min_group_cardinality=max(k_min, 2),
        require_pre_aggregation=True,
    )


def _attach_planner_constraints(dec: Decision, pc: PlannerConstraint) -> Decision:
    """
    Attach constraints to Decision in a backward-compatible way.

    If Decision dataclass already has these fields, we use `replace`.
    If not, we attach dynamically so callers can still access:
      - decision.planner_constraint
      - decision.planner_constraints_json
    """
    payload = pc.to_json_dict()

    return replace(dec, planner_constraint=pc, planner_constraints_json=payload)
    # # 1) Try dataclass field update (preferred for clean typing)
    # try:
    #     return replace(dec, planner_constraint=pc, planner_constraints_json=payload)  # type: ignore[arg-type]
    # except TypeError:
    #     pass

    # # 2) Fallback: dynamic attributes (keeps API stable without changing .types)
    # setattr(dec, "planner_constraint", pc)
    # setattr(dec, "planner_constraints_json", payload)
    # return dec


# =============================================================================
# Planner
# =============================================================================

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
                dec = Decision(boundary=b, granularity=g, feasible=True, scorecard=sc, reason="feasible")
                pc = compile_to_planner_constraints(feature, dec, th)
                return _attach_planner_constraints(dec, pc)
            best = best or (b, g, sc)

    # If nothing feasible, return most conservative recommendation
    b, g, sc = best
    dec = Decision(
        boundary=Boundary.LOCAL,
        granularity=Granularity.AGGREGATE,
        feasible=False,
        scorecard=sc,
        reason="no_feasible_option_under_thresholds",
    )
    pc = compile_to_planner_constraints(feature, dec, th)
    return _attach_planner_constraints(dec, pc)


def plan_counterfactuals(
    feature: FeatureSpec,
    th: PolicyThresholds,
    target_g: Granularity = Granularity.ITEM,
) -> List[Dict]:
    """
    Return candidate edits with predicted scorecards, ordered by lowest risk then minimal edit size.
    Also emits the planner constraints that would apply if the edit were accepted.
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

    out = []
    for edit, f2 in candidates:
        sc = compute_scorecard(f2, g=target_g, th=th)
        ok = feasible_granularity(sc, target_g, th)

        # Create a "hypothetical decision" to compile binding constraints for reviewers/tools
        hyp = Decision(
            boundary=Boundary.CENTRAL,   # boundary is decided elsewhere; CENTRAL here is a neutral default
            granularity=target_g,
            feasible=ok,
            scorecard=sc,
            reason="counterfactual_candidate",
        )
        pc = compile_to_planner_constraints(f2, hyp, th)

        out.append({
            "edit": edit,
            "target_granularity": target_g.value,
            "feasible_at_target": ok,
            "scorecard": sc,
            "planner_constraints_json": pc.to_json_dict(),
        })

    # Sort: feasible first, then lower risk
    out.sort(key=lambda x: (not x["feasible_at_target"], x["scorecard"].risk))
    return out
