from ppds.types import FieldSpec, FeatureSpec, JoinKeySpec, PolicyThresholds, Boundary, Granularity
from ppds.planner import decide, plan_counterfactuals

def thresholds():
    return PolicyThresholds(
        tau_boundary={Boundary.LOCAL: 0.9, Boundary.SHUFFLE: 0.7, Boundary.CENTRAL: 0.55},
        tau_granularity={Granularity.ITEM: 0.45, Granularity.CLUSTER: 0.6, Granularity.AGGREGATE: 0.75},
        k_min=100,
    )

def test_decide_returns_some_recommendation():
    th = thresholds()
    f = FeatureSpec(
        feature_id="f",
        description="sensitive + join key",
        fields=[FieldSpec("age","int", is_sensitive=True), FieldSpec("zip","string", is_sensitive=True)],
        join_keys=[JoinKeySpec("uid", stability=0.9)],
        bucketizations={"age": 80, "zip": 500},
        policy_tags=["age","location"],
        support_hint={Granularity.ITEM: 50, Granularity.CLUSTER: 10_000, Granularity.AGGREGATE: 10_000_000},
    )
    d = decide(f, th)
    assert d.boundary in {Boundary.CENTRAL, Boundary.SHUFFLE, Boundary.LOCAL}
    assert d.granularity in {Granularity.ITEM, Granularity.CLUSTER, Granularity.AGGREGATE}

def test_counterfactuals_produced():
    th = thresholds()
    f = FeatureSpec(
        feature_id="f",
        description="sensitive buckets",
        fields=[FieldSpec("age","int", is_sensitive=True)],
        bucketizations={"age": 80},
        policy_tags=["age"],
    )
    cfs = plan_counterfactuals(f, th, target_g=Granularity.ITEM)
    assert len(cfs) > 0
    # some edit should coarsen age buckets
    assert any("bucketize:age" in x["edit"] for x in cfs)
