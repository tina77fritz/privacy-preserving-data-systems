from datetime import date, timedelta
from ppds.budget import BudgetLedger, SpendEvent

def test_sliding_window_spend():
    ledger = BudgetLedger()
    fid = "f"
    today = date(2026, 1, 30)
    for i in range(40):
        ledger.commit(SpendEvent(fid, today - timedelta(days=i), epsilon=0.1))
    eps30, _ = ledger.window_spend(fid, 30, today)
    assert abs(eps30 - 3.0) < 1e-9  # 30 * 0.1

def test_adaptive_eps_decreases():
    ledger = BudgetLedger()
    fid = "f"
    today = date(2026, 1, 30)
    cap = 1.0
    # spend 0.9 already
    for i in range(9):
        ledger.commit(SpendEvent(fid, today - timedelta(days=i), epsilon=0.1))
    eps = ledger.adaptive_eps(fid, 30, today, cap, planned_releases_left=21)
    assert eps > 0.0 and eps < 0.1
