from ppds.types import FieldSpec, JoinKeySpec, FeatureSpec, PolicyThresholds, Boundary, Granularity
from ppds.lps import compute_scorecard

def thresholds():
    return PolicyThresholds(
        tau_boundary={Boundary.LOCAL: 0.9, Boundary.SHUFFLE: 0.7, Boundary.CENTRAL: 0.55},
        tau_granularity={Granularity.ITEM: 0.45, Granularity.CLUSTER: 0.6, Granularity.AGGREGATE: 0.75},
        k_min=100,
    )

def test_scorecard_increases_with_stable_join_key():
    th = thresholds()
    f0 = FeatureSpec(
        feature_id="f0",
        description="no join key",
        fields=[FieldSpec("x","int")],
    )
    f1 = FeatureSpec(
        feature_id="f1",
        description="has stable join key",
        fields=[FieldSpec("x","int")],
        join_keys=[JoinKeySpec("uid", stability=0.95, ndv_hint=1_000_000)],
    )
    s0 = compute_scorecard(f0, Granularity.ITEM, th)
    s1 = compute_scorecard(f1, Granularity.ITEM, th)
    assert s1.L > s0.L
    assert s1.risk >= s0.risk

def test_uniqueness_uses_support_hint():
    th = thresholds()
    f = FeatureSpec(
        feature_id="f",
        description="support hint",
        fields=[FieldSpec("x","int")],
        support_hint={Granularity.ITEM: 50, Granularity.CLUSTER: 10_000, Granularity.AGGREGATE: 10_000_000},
    )
    s_item = compute_scorecard(f, Granularity.ITEM, th)
    s_cluster = compute_scorecard(f, Granularity.CLUSTER, th)
    assert s_item.U > s_cluster.U
