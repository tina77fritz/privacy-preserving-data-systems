from __future__ import annotations
import json
from dataclasses import asdict
from datetime import date

from .types import FieldSpec, JoinKeySpec, FeatureSpec, PolicyThresholds, Boundary, Granularity
from .planner import decide, plan_counterfactuals
from .budget import BudgetLedger, SpendEvent


def main():
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
    # commit 9 days of eps=0.1
    for i in range(9):
        ledger.commit(SpendEvent(f.feature_id, today.replace(day=today.day - i), epsilon=0.1))
    eps30, _ = ledger.window_spend(f.feature_id, 30, today)
    print(f"spent_eps_30d={eps30:.2f} cap={cap:.2f} can_spend_next_0.1={ledger.can_spend(f.feature_id,30,today,cap,0.0,0.1)}")
    print(f"adaptive_eps_for_next_21_releases={ledger.adaptive_eps(f.feature_id,30,today,cap,planned_releases_left=21):.4f}")


if __name__ == "__main__":
    main()
