from ppds.plan_contract import PPDSPlan, RejectionReason

def test_plan_fingerprint_deterministic():
    inp = {"lps": 0.1, "b": 2, "a": 1}
    p1 = PPDSPlan.build(
        policy_hash="h1",
        input_obj=inp,
        status="accepted",
        decisions={"from": "t", "select": ["*"], "params": {"x": 1}},
        rejection_reasons=[],
    ).to_dict()

    # change key order to ensure canonicalization works
    inp2 = {"a": 1, "b": 2, "lps": 0.1}
    p2 = PPDSPlan.build(
        policy_hash="h1",
        input_obj=inp2,
        status="accepted",
        decisions={"select": ["*"], "from": "t", "params": {"x": 1}},
        rejection_reasons=[],
    ).to_dict()

    assert p1["input_fingerprint"] == p2["input_fingerprint"]
    assert p1["plan_fingerprint"] == p2["plan_fingerprint"]
