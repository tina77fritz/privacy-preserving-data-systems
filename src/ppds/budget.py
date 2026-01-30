from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Tuple

@dataclass(frozen=True)
class SpendEvent:
    feature_id: str
    day: date
    epsilon: float
    delta: float = 0.0


class BudgetLedger:
    """
    Sliding-window sequential composition (conservative baseline).
    Replace with RDP accountant later without changing interface.
    """
    def __init__(self):
        self._events: Dict[str, List[SpendEvent]] = {}

    def commit(self, event: SpendEvent) -> None:
        self._events.setdefault(event.feature_id, []).append(event)

    def window_spend(self, feature_id: str, window_days: int, asof: date) -> Tuple[float, float]:
        start = asof - timedelta(days=window_days - 1)
        eps = 0.0
        delt = 0.0
        for e in self._events.get(feature_id, []):
            if start <= e.day <= asof:
                eps += e.epsilon
                delt += e.delta
        return eps, delt

    def can_spend(self, feature_id: str, window_days: int, asof: date, eps_cap: float, delta_cap: float,
                  next_eps: float, next_delta: float = 0.0) -> bool:
        eps, delt = self.window_spend(feature_id, window_days, asof)
        return (eps + next_eps <= eps_cap) and (delt + next_delta <= delta_cap)

    def adaptive_eps(self, feature_id: str, window_days: int, asof: date, eps_cap: float, planned_releases_left: int) -> float:
        eps, _ = self.window_spend(feature_id, window_days, asof)
        remain = max(0.0, eps_cap - eps)
        if planned_releases_left <= 0:
            return 0.0
        return remain / planned_releases_left
