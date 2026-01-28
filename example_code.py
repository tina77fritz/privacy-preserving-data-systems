"""
Minimal Reference Implementation (Python) for:
Catalog Update → LPS Scoring → Granularity Selection → Contract Issuance → Runtime Ingest → Materialization → Re-evaluation

This is a **spec-aligned, engineering-friendly skeleton**:
- Controller plane decides (offline batch jobs).
- Runtime plane enforces (ingest/materialize).
- Uses SQLite for persistence (replace with KWDB tables / jobs in production).
- DP calibration is stubbed (pluggable).

Run:
  python privacy_controller.py  

Notes:
- This is not a production security implementation.
- The goal is to make the end-to-end control flow executable and testable.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

# -----------------------------
# Constants / Enums (simple)
# -----------------------------
BOUNDARIES = ("LOCAL", "SHUFFLE", "CENTRAL")
GRANULARITIES = ("ITEM", "CLUSTER", "AGGREGATE")

GRAN_ORDER = {"ITEM": 0, "CLUSTER": 1, "AGGREGATE": 2}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def now_ts() -> int:
    return int(time.time())


def g_at_least(g: str, min_g: str) -> bool:
    return GRAN_ORDER[g] >= GRAN_ORDER[min_g]


def coarsest(grans: List[str]) -> str:
    return sorted(grans, key=lambda x: GRAN_ORDER[x], reverse=True)[0]


def finest(grans: List[str]) -> str:
    return sorted(grans, key=lambda x: GRAN_ORDER[x])[0]


# -----------------------------
# Data Models
# -----------------------------
@dataclass(frozen=True)
class FeatureDef:
    feature_id: str
    feature_version: str
    owner: str
    query_type: str  # e.g., "MEAN_BOUNDED_0_1", "COUNT"
    join_keys: List[str]
    retention_days: int
    sensitivity_tags: Set[str]  # e.g., {"demographics", "precise_location"}
    boundary_capabilities: Set[str]  # {"LOCAL","SHUFFLE","CENTRAL"}
    granularity_candidates: Set[str]  # {"ITEM","CLUSTER","AGGREGATE"}


@dataclass(frozen=True)
class PolicyConfig:
    policy_version: str
    # Weights
    w_link: float
    w_uniq: float
    w_infer: float
    w_policy: float

    # Linkability factors
    a_id: float
    a_join: float
    a_ttl: float
    deg_max: int
    retention_days_max: int

    # Thresholds / bands
    band_mid: float
    band_high: float
    min_support_floor: int
    distinct_drift_threshold: int
    infer_default: float
    infer_high: float
    tau_lps: float

    # DP params (simple)
    central_sigma: float  # Gaussian noise multiplier (stub)
    min_support_threshold: int


@dataclass(frozen=True)
class StatsSnapshot:
    feature_id: str
    window_id: str
    granularity: str
    n_obs: int
    n_distinct_est: int
    min_support_est: int
    tail_mass_est: float
    approx_variance: float  # sampling / signal proxy


@dataclass(frozen=True)
class ProbeResult:
    feature_id: str
    probe_run_id: str
    metrics: Dict[str, float]  # e.g., {"gender": AUC}


@dataclass(frozen=True)
class LPSScorecard:
    run_id: str
    feature_id: str
    feature_version: str
    s_link: float
    s_uniq: float
    s_infer: float
    s_policy: float
    lps_total: float
    admissible_set: List[Tuple[str, str]]  # list of (boundary, granularity)
    min_granularity: str
    reason_codes: List[str]
    lps_version: str
    policy_version: str
    computed_at: int


@dataclass(frozen=True)
class RoutingDecision:
    feature_id: str
    selected_boundary: str
    selected_granularity: str
    dp_mechanism: str
    dp_parameters: Dict[str, Any]
    aggregation_keys: List[str]
    join_policy: Dict[str, Any]
    retention_policy: Dict[str, Any]
    decision_reason_codes: List[str]
    contract_version: str
    issued_at: int


@dataclass(frozen=True)
class RuntimeContract:
    feature_id: str
    contract_version: str
    boundary: str
    granularity: str
    aggregation_keys: List[str]
    dp_mechanism: str
    dp_parameters: Dict[str, Any]
    join_policy: Dict[str, Any]
    retention_policy: Dict[str, Any]
    allow_downgrade_to: List[Tuple[str, str]]  # list of (boundary, granularity)
    active: bool


# -----------------------------
# Persistence Layer (SQLite)
# -----------------------------
class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_features (
              feature_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_stats_ts (
              feature_id TEXT NOT NULL,
              window_id TEXT NOT NULL,
              granularity TEXT NOT NULL,
              n_obs INTEGER NOT NULL,
              n_distinct_est INTEGER NOT NULL,
              min_support_est INTEGER NOT NULL,
              tail_mass_est REAL NOT NULL,
              approx_variance REAL NOT NULL,
              PRIMARY KEY(feature_id, window_id, granularity)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS probe_results (
              feature_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lps_scorecards (
              feature_id TEXT NOT NULL,
              computed_at INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(feature_id, computed_at)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS routing_decisions (
              feature_id TEXT NOT NULL,
              issued_at INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(feature_id, issued_at)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_contracts (
              feature_id TEXT NOT NULL,
              contract_version TEXT NOT NULL,
              active INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(feature_id, contract_version)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_staging (
              boundary TEXT NOT NULL,
              feature_id TEXT NOT NULL,
              granularity TEXT NOT NULL,
              window_id TEXT NOT NULL,
              cell_key TEXT NOT NULL,
              clicks INTEGER NOT NULL,
              impressions INTEGER NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS materialized_features (
              boundary TEXT NOT NULL,
              feature_id TEXT NOT NULL,
              granularity TEXT NOT NULL,
              window_id TEXT NOT NULL,
              cell_key TEXT NOT NULL,
              value REAL NOT NULL,
              contract_version TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
              ts INTEGER NOT NULL,
              event_type TEXT NOT NULL,
              feature_id TEXT NOT NULL,
              details_json TEXT NOT NULL
            );
            """
        )

        self.conn.commit()

    # ---- Catalog
    def upsert_feature(self, f: FeatureDef) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO catalog_features(feature_id, payload_json) VALUES (?,?)",
            (f.feature_id, json.dumps(dataclasses.asdict(f))),
        )
        self.conn.commit()

    def get_feature(self, feature_id: str) -> FeatureDef:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT payload_json FROM catalog_features WHERE feature_id=?",
            (feature_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Feature not found: {feature_id}")
        payload = json.loads(row["payload_json"])
        payload["sensitivity_tags"] = set(payload["sensitivity_tags"])
        payload["boundary_capabilities"] = set(payload["boundary_capabilities"])
        payload["granularity_candidates"] = set(payload["granularity_candidates"])
        return FeatureDef(**payload)

    def list_features(self) -> List[str]:
        cur = self.conn.cursor()
        rows = cur.execute("SELECT feature_id FROM catalog_features").fetchall()
        return [r["feature_id"] for r in rows]

    # ---- Stats
    def upsert_stats(self, s: StatsSnapshot) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO feature_stats_ts
            (feature_id, window_id, granularity, n_obs, n_distinct_est, min_support_est, tail_mass_est, approx_variance)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                s.feature_id,
                s.window_id,
                s.granularity,
                s.n_obs,
                s.n_distinct_est,
                s.min_support_est,
                s.tail_mass_est,
                s.approx_variance,
            ),
        )
        self.conn.commit()

    def get_stats(self, feature_id: str, window_id: str, granularity: str) -> Optional[StatsSnapshot]:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT feature_id, window_id, granularity, n_obs, n_distinct_est, min_support_est, tail_mass_est, approx_variance
            FROM feature_stats_ts WHERE feature_id=? AND window_id=? AND granularity=?
            """,
            (feature_id, window_id, granularity),
        ).fetchone()
        if not row:
            return None
        return StatsSnapshot(**dict(row))

    # ---- Probe
    def upsert_probe(self, p: ProbeResult) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO probe_results(feature_id, payload_json) VALUES (?,?)",
            (p.feature_id, json.dumps(dataclasses.asdict(p))),
        )
        self.conn.commit()

    def get_probe(self, feature_id: str) -> Optional[ProbeResult]:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT payload_json FROM probe_results WHERE feature_id=?",
            (feature_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        return ProbeResult(**payload)

    # ---- LPS
    def append_lps_scorecard(self, sc: LPSScorecard) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO lps_scorecards(feature_id, computed_at, payload_json) VALUES (?,?,?)",
            (sc.feature_id, sc.computed_at, json.dumps(dataclasses.asdict(sc))),
        )
        self.conn.commit()

    def read_latest_lps(self, feature_id: str) -> Optional[LPSScorecard]:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT payload_json FROM lps_scorecards
            WHERE feature_id=?
            ORDER BY computed_at DESC LIMIT 1
            """,
            (feature_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["admissible_set"] = [tuple(x) for x in payload["admissible_set"]]
        return LPSScorecard(**payload)

    # ---- Routing decisions
    def append_routing_decision(self, rd: RoutingDecision) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO routing_decisions(feature_id, issued_at, payload_json) VALUES (?,?,?)",
            (rd.feature_id, rd.issued_at, json.dumps(dataclasses.asdict(rd))),
        )
        self.conn.commit()

    def read_latest_routing_decision(self, feature_id: str) -> Optional[RoutingDecision]:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT payload_json FROM routing_decisions
            WHERE feature_id=?
            ORDER BY issued_at DESC LIMIT 1
            """,
            (feature_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        return RoutingDecision(**payload)

    # ---- Contracts
    def append_runtime_contract(self, c: RuntimeContract) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO runtime_contracts(feature_id, contract_version, active, payload_json) VALUES (?,?,?,?)",
            (c.feature_id, c.contract_version, 1 if c.active else 0, json.dumps(dataclasses.asdict(c))),
        )
        # deactivate older active contracts for feature
        cur.execute(
            """
            UPDATE runtime_contracts SET active=0
            WHERE feature_id=? AND contract_version<>?
            """,
            (c.feature_id, c.contract_version),
        )
        self.conn.commit()

    def read_active_contract(self, feature_id: str) -> Optional[RuntimeContract]:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT payload_json FROM runtime_contracts
            WHERE feature_id=? AND active=1
            ORDER BY contract_version DESC LIMIT 1
            """,
            (feature_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["allow_downgrade_to"] = [tuple(x) for x in payload["allow_downgrade_to"]]
        return RuntimeContract(**payload)

    # ---- Runtime staging / materialization
    def stage_event(
        self,
        boundary: str,
        feature_id: str,
        granularity: str,
        window_id: str,
        cell_key: str,
        clicks: int,
        impressions: int,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO runtime_staging(boundary, feature_id, granularity, window_id, cell_key, clicks, impressions)
            VALUES (?,?,?,?,?,?,?)
            """,
            (boundary, feature_id, granularity, window_id, cell_key, clicks, impressions),
        )
        self.conn.commit()

    def read_staged(
        self, boundary: str, feature_id: str, granularity: str, window_id: str
    ) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT cell_key, clicks, impressions
            FROM runtime_staging
            WHERE boundary=? AND feature_id=? AND granularity=? AND window_id=?
            """,
            (boundary, feature_id, granularity, window_id),
        ).fetchall()
        return rows

    def write_materialized(
        self,
        boundary: str,
        feature_id: str,
        granularity: str,
        window_id: str,
        cell_key: str,
        value: float,
        contract_version: str,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO materialized_features(boundary, feature_id, granularity, window_id, cell_key, value, contract_version)
            VALUES (?,?,?,?,?,?,?)
            """,
            (boundary, feature_id, granularity, window_id, cell_key, value, contract_version),
        )
        self.conn.commit()

    # ---- Audit
    def audit(self, event_type: str, feature_id: str, details: Dict[str, Any]) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO audit_log(ts, event_type, feature_id, details_json) VALUES (?,?,?,?)",
            (now_ts(), event_type, feature_id, json.dumps(details)),
        )
        self.conn.commit()


# -----------------------------
# DP Utilities (stubbed)
# -----------------------------
def auc_to_risk(auc: float) -> float:
    # risk = 0 at AUC=0.5, risk=1 at AUC=1.0 (linear)
    return clamp01(max(0.0, 2.0 * (auc - 0.5)))


def gaussian_noise(std: float) -> float:
    # Use Python's random.gauss for minimal demo
    return random.gauss(0.0, std)


# -----------------------------
# Controller Plane
# -----------------------------
class Controller:
    def __init__(self, store: Store, policy: PolicyConfig):
        self.store = store
        self.policy = policy

    def on_catalog_update(self, new_features: List[FeatureDef]) -> None:
        for f in new_features:
            self._validate_feature(f)
            self.store.upsert_feature(f)
            self.store.audit("CATALOG_UPSERT", f.feature_id, {"feature_version": f.feature_version})

    def _validate_feature(self, f: FeatureDef) -> None:
        assert f.feature_id, "feature_id required"
        assert f.feature_version, "feature_version required"
        assert f.query_type in ("MEAN_BOUNDED_0_1", "COUNT"), "unsupported query_type"
        assert f.retention_days >= 0, "retention_days must be non-negative"
        assert f.boundary_capabilities.issubset(set(BOUNDARIES))
        assert f.granularity_candidates.issubset(set(GRANULARITIES))

    # -------- LPS Scoring (docs/06) --------
    def run_lps_scoring_batch(self, feature_ids: List[str], window_w1: str = "W1", window_w0: str = "W0") -> None:
        run_id = f"lpsrun_{now_ts()}"
        for fid in feature_ids:
            f = self.store.get_feature(fid)
            w1 = self._best_stats(fid, window_w1)  # for drift checks, etc.
            w0 = self._best_stats(fid, window_w0)
            probe = self.store.get_probe(fid)

            s_link, rc_link = self._compute_linkability(f)
            s_uniq, rc_uniq = self._compute_uniqueness(fid, w1, w0)
            s_infer, rc_infer = self._compute_inferability(probe)
            s_policy, rc_policy, hard = self._compute_policy_penalty(f)

            lps_total = (
                self.policy.w_link * s_link
                + self.policy.w_uniq * s_uniq
                + self.policy.w_infer * s_infer
                + self.policy.w_policy * s_policy
            )

            admissible_set, min_g = self._derive_admissible_set(f, lps_total, hard)

            sc = LPSScorecard(
                run_id=run_id,
                feature_id=fid,
                feature_version=f.feature_version,
                s_link=s_link,
                s_uniq=s_uniq,
                s_infer=s_infer,
                s_policy=s_policy,
                lps_total=lps_total,
                admissible_set=sorted(list(admissible_set)),
                min_granularity=min_g,
                reason_codes=rc_link + rc_uniq + rc_infer + rc_policy,
                lps_version="lps_v1",
                policy_version=self.policy.policy_version,
                computed_at=now_ts(),
            )
            self.store.append_lps_scorecard(sc)
            self.store.audit("LPS_SCORED", fid, {"lps_total": lps_total, "min_granularity": min_g})

    def _best_stats(self, fid: str, window_id: str) -> Optional[StatsSnapshot]:
        # choose any available granularity stats to do drift checks; in production you'd keep separate.
        for g in ("CLUSTER", "ITEM", "AGGREGATE"):
            s = self.store.get_stats(fid, window_id, g)
            if s:
                return s
        return None

    def _compute_linkability(self, f: FeatureDef) -> Tuple[float, List[str]]:
        # Simple metadata-based linkability
        id_flag = 1.0 if ("user_id" in f.join_keys or "device_id" in f.join_keys) else 0.0
        # Join graph degree is not modeled in this minimal impl; approximate by join_keys count
        deg = len(f.join_keys)
        ttl = f.retention_days

        n_join = min(1.0, math.log(1 + deg) / math.log(1 + max(1, self.policy.deg_max)))
        n_ttl = min(1.0, ttl / max(1, self.policy.retention_days_max))

        s = clamp01(self.policy.a_id * id_flag + self.policy.a_join * n_join + self.policy.a_ttl * n_ttl)

        rcs: List[str] = []
        if id_flag > 0:
            rcs.append("STABLE_ID_PRESENT")
        if n_join > 0.7:
            rcs.append("HIGH_JOIN_DEGREE")
        if n_ttl > 0.7:
            rcs.append("LONG_RETENTION")
        return s, rcs

    def _compute_uniqueness(
        self, fid: str, w1: Optional[StatsSnapshot], w0: Optional[StatsSnapshot]
    ) -> Tuple[float, List[str]]:
        if not w1:
            return 1.0, ["MISSING_STATS_CONSERVATIVE_UNIQ"]
        if w1.n_obs <= 0:
            return 1.0, ["ZERO_OBS_CONSERVATIVE_UNIQ"]

        # Min-support proxy
        s = clamp01(1.0 - math.log(1 + w1.min_support_est) / math.log(1 + max(1, w1.n_obs)))

        rcs: List[str] = []
        if w1.min_support_est < self.policy.min_support_floor:
            rcs.append("LOW_MIN_SUPPORT")
        if w0 and abs(w1.n_distinct_est - w0.n_distinct_est) > self.policy.distinct_drift_threshold:
            rcs.append("DISTINCT_DRIFT")
        return s, rcs

    def _compute_inferability(self, probe: Optional[ProbeResult]) -> Tuple[float, List[str]]:
        if not probe:
            return self.policy.infer_default, ["MISSING_PROBE_CONSERVATIVE_INFER"]

        best = 0.0
        rcs: List[str] = []
        for attr, auc in probe.metrics.items():
            r = auc_to_risk(auc)
            best = max(best, r)
            if r > self.policy.infer_high:
                rcs.append(f"HIGH_INFER:{attr}")
        return best, rcs

    def _compute_policy_penalty(self, f: FeatureDef) -> Tuple[float, List[str], Dict[str, Any]]:
        # Hard constraints are encoded as return structure
        rcs: List[str] = []
        hard = {"deny_boundaries": set(), "min_granularity": None}

        # Example hard deny: precise_location can't go CENTRAL
        if "precise_location" in f.sensitivity_tags:
            hard["deny_boundaries"].add("CENTRAL")
            rcs.append("POLICY_DENY:CENTRAL_FOR_PRECISE_LOCATION")

        # Example min granularity: demographics at least CLUSTER
        if "demographics" in f.sensitivity_tags:
            hard["min_granularity"] = "CLUSTER" if hard["min_granularity"] is None else hard["min_granularity"]
            rcs.append("POLICY_MIN_GRANULARITY:CLUSTER_FOR_DEMOGRAPHICS")

        # Soft penalty if any sensitivity tag exists
        s = 0.5 if f.sensitivity_tags else 0.0
        if f.sensitivity_tags:
            rcs.append("POLICY_SOFT_PENALTY:SENSITIVE_TAG_PRESENT")

        return s, rcs, hard

    def _derive_admissible_set(
        self, f: FeatureDef, lps_total: float, hard: Dict[str, Any]
    ) -> Tuple[Set[Tuple[str, str]], str]:
        # Base candidates
        candidates: Set[Tuple[str, str]] = set()
        for b in f.boundary_capabilities:
            for g in f.granularity_candidates:
                candidates.add((b, g))

        # Apply hard boundary denies
        deny = hard.get("deny_boundaries", set())
        candidates = {(b, g) for (b, g) in candidates if b not in deny}

        # Determine min granularity (hard then band-based)
        min_g = hard.get("min_granularity")
        if not min_g:
            if lps_total >= self.policy.band_high:
                min_g = "AGGREGATE"
            elif lps_total >= self.policy.band_mid:
                min_g = "CLUSTER"
            else:
                min_g = "ITEM"

        candidates = {(b, g) for (b, g) in candidates if g_at_least(g, min_g)}

        return candidates, min_g

    # -------- Granularity Selection (docs/07) --------
    def run_granularity_selection_batch(self, feature_ids: List[str], window_id: str = "W1") -> None:
        for fid in feature_ids:
            f = self.store.get_feature(fid)
            lps = self.store.read_latest_lps(fid)
            if not lps:
                self.store.audit("ROUTING_SKIPPED", fid, {"reason": "NO_LPS"})
                continue

            scored: List[Dict[str, Any]] = []
            for (b, g) in lps.admissible_set:
                stats = self.store.get_stats(fid, window_id, g)
                if not stats:
                    continue
                if stats.min_support_est < self.policy.min_support_threshold:
                    continue

                eff = self._compute_effective_variance(f, stats, boundary=b)
                scored.append({"boundary": b, "granularity": g, "effvar": eff})

            if not scored:
                # conservative fallback: coarsest granularity within admissible set
                admissible_grans = [g for (_, g) in lps.admissible_set]
                g_star = coarsest(admissible_grans)
                # choose safest boundary among those that support g_star (prefer LOCAL < SHUFFLE < CENTRAL)
                b_candidates = [b for (b, g) in lps.admissible_set if g == g_star]
                b_star = self._prefer_lower_risk_boundary(b_candidates)
                self._persist_routing_decision(fid, b_star, g_star, ["NO_FEASIBLE_STATS_FALLBACK_COARSE"])
                continue

            # Choose minimal effvar; tie-break to finest granularity, then lower-risk boundary
            scored.sort(key=lambda x: (x["effvar"], GRAN_ORDER[x["granularity"]], self._boundary_rank(x["boundary"])))
            best = scored[0]
            self._persist_routing_decision(
                fid,
                best["boundary"],
                best["granularity"],
                ["MIN_EFFVAR_SELECTED", "TIEBREAK_FINEST_THEN_SAFEST"],
            )

    def _compute_effective_variance(self, f: FeatureDef, stats: StatsSnapshot, boundary: str) -> float:
        # Minimal: treat only CENTRAL Gaussian mean queries with sigma policy; others reuse same sigma for demo
        N = max(1, stats.n_obs)
        if f.query_type == "MEAN_BOUNDED_0_1":
            sigma = self.policy.central_sigma  # stub; boundary-specific in real system
            var_dp = (sigma * sigma) * (1.0 / (N * N))
            # add sampling proxy if provided
            return var_dp + max(0.0, stats.approx_variance)
        else:
            # COUNT query: approximate dp noise variance per cell (placeholder)
            sigma = self.policy.central_sigma
            var_dp = sigma * sigma  # placeholder, not correct DP accounting
            return var_dp / N

    def _boundary_rank(self, b: str) -> int:
        # lower is "safer" in this policy (LOCAL safest)
        return {"LOCAL": 0, "SHUFFLE": 1, "CENTRAL": 2}[b]

    def _prefer_lower_risk_boundary(self, boundaries: List[str]) -> str:
        return sorted(boundaries, key=self._boundary_rank)[0]

    def _persist_routing_decision(self, fid: str, boundary: str, granularity: str, reasons: List[str]) -> None:
        f = self.store.get_feature(fid)

        dp_mech = "GAUSSIAN" if boundary == "CENTRAL" else "GAUSSIAN"  # stub
        dp_params = {
            "sigma": self.policy.central_sigma,
            "min_support_threshold": self.policy.min_support_threshold,
        }

        # Aggregation keys depend on granularity (example)
        agg_keys = []
        if granularity == "ITEM":
            agg_keys = ["item_id"]
        elif granularity == "CLUSTER":
            agg_keys = ["cluster_id"]
        else:
            agg_keys = []

        join_policy = {"allow_joins": boundary == "CENTRAL", "join_keys": f.join_keys}
        retention_policy = {"retention_days": f.retention_days}

        contract_version = f"c_{fid}_{now_ts()}"

        rd = RoutingDecision(
            feature_id=fid,
            selected_boundary=boundary,
            selected_granularity=granularity,
            dp_mechanism=dp_mech,
            dp_parameters=dp_params,
            aggregation_keys=agg_keys,
            join_policy=join_policy,
            retention_policy=retention_policy,
            decision_reason_codes=reasons,
            contract_version=contract_version,
            issued_at=now_ts(),
        )
        self.store.append_routing_decision(rd)
        self.store.audit("ROUTING_DECIDED", fid, {"boundary": boundary, "granularity": granularity, "reasons": reasons})

    # -------- Contract Issuance (docs/08) --------
    def run_contract_issuance_batch(self, feature_ids: List[str]) -> None:
        for fid in feature_ids:
            rd = self.store.read_latest_routing_decision(fid)
            if not rd:
                self.store.audit("CONTRACT_SKIPPED", fid, {"reason": "NO_ROUTING_DECISION"})
                continue

            # allow only monotonic downgrades (same boundary; coarser granularity)
            allow = []
            for g in GRanularity_downgrades(rd.selected_granularity):
                allow.append((rd.selected_boundary, g))

            c = RuntimeContract(
                feature_id=fid,
                contract_version=rd.contract_version,
                boundary=rd.selected_boundary,
                granularity=rd.selected_granularity,
                aggregation_keys=rd.aggregation_keys,
                dp_mechanism=rd.dp_mechanism,
                dp_parameters=rd.dp_parameters,
                join_policy=rd.join_policy,
                retention_policy=rd.retention_policy,
                allow_downgrade_to=allow,
                active=True,
            )
            self.store.append_runtime_contract(c)
            self.store.audit("CONTRACT_PUBLISHED", fid, {"contract_version": c.contract_version})


def GRanularity_downgrades(g: str) -> List[str]:
    # Returns strictly coarser granularities in order
    if g == "ITEM":
        return ["CLUSTER", "AGGREGATE"]
    if g == "CLUSTER":
        return ["AGGREGATE"]
    return []


# -----------------------------
# Runtime Plane (docs/08)
# -----------------------------
class Runtime:
    def __init__(self, store: Store):
        self.store = store

    def ingest_signal(
        self,
        feature_id: str,
        window_id: str,
        cell_key: str,
        clicks: int,
        impressions: int,
    ) -> None:
        contract = self.store.read_active_contract(feature_id)
        if not contract:
            self.store.audit("REJECT", feature_id, {"reason": "NO_ACTIVE_CONTRACT"})
            return

        # Runtime does NOT decide; it enforces contract fields
        boundary = contract.boundary
        granularity = contract.granularity

        # Minimal schema checks (placeholder)
        if clicks < 0 or impressions < 0 or clicks > impressions:
            self.store.audit("REJECT", feature_id, {"reason": "INVALID_EVENT"})
            return

        self.store.stage_event(boundary, feature_id, granularity, window_id, cell_key, clicks, impressions)
        self.store.audit("INGEST", feature_id, {"boundary": boundary, "granularity": granularity, "window_id": window_id})

    def materialize(self, boundary: str, window_id: str) -> None:
        # Materialize for all active contracts in this boundary
        for fid in self.store.list_features():
            contract = self.store.read_active_contract(fid)
            if not contract or contract.boundary != boundary:
                continue

            rows = self.store.read_staged(boundary, fid, contract.granularity, window_id)
            if not rows:
                continue

            # Aggregate by cell_key (already staged by cell_key)
            by_cell: Dict[str, Dict[str, int]] = {}
            for r in rows:
                cell = r["cell_key"]
                by_cell.setdefault(cell, {"clicks": 0, "impressions": 0})
                by_cell[cell]["clicks"] += int(r["clicks"])
                by_cell[cell]["impressions"] += int(r["impressions"])

            # Min-support check (fail closed or downgrade if allowed)
            min_support = min(v["impressions"] for v in by_cell.values())
            if min_support < int(contract.dp_parameters.get("min_support_threshold", 0)):
                downgraded = self._attempt_downgrade(contract)
                if not downgraded:
                    self.store.audit("BLOCK", fid, {"reason": "MIN_SUPPORT_FAIL", "min_support": min_support})
                    continue
                contract = downgraded
                # re-read staged rows in downgraded granularity (not modeled); in real system, staging differs.
                # Here we just proceed but note in audit.
                self.store.audit("DOWNGRADE_NOTICE", fid, {"note": "demo does not re-stage by new granularity"})

            # Apply DP and write materialized
            for cell, agg in by_cell.items():
                clicks = agg["clicks"]
                imps = max(1, agg["impressions"])
                ctr = clicks / imps

                value = self._apply_dp_mean_0_1(ctr, imps, contract)
                self.store.write_materialized(boundary, fid, contract.granularity, window_id, cell, value, contract.contract_version)

            self.store.audit(
                "MATERIALIZE",
                fid,
                {"boundary": boundary, "granularity": contract.granularity, "window_id": window_id, "contract_version": contract.contract_version},
            )

    def _apply_dp_mean_0_1(self, mean: float, N: int, contract: RuntimeContract) -> float:
        # Gaussian DP noise on mean with sensitivity 1/N (bounded in [0,1])
        sigma = float(contract.dp_parameters.get("sigma", 0.0))
        std = sigma * (1.0 / max(1, N))
        noisy = mean + gaussian_noise(std)
        return float(max(0.0, min(1.0, noisy)))

    def _attempt_downgrade(self, contract: RuntimeContract) -> Optional[RuntimeContract]:
        # Runtime can only downgrade to pre-authorized coarser granularity within same boundary (demo).
        if not contract.allow_downgrade_to:
            return None
        # pick the first allowed downgrade (coarsest is safest)
        target = sorted(contract.allow_downgrade_to, key=lambda x: GRAN_ORDER[x[1]], reverse=True)[0]
        (b2, g2) = target
        new_contract = dataclasses.replace(contract, granularity=g2)
        self.store.audit(
            "DOWNGRADE",
            contract.feature_id,
            {"from": [contract.boundary, contract.granularity], "to": [b2, g2], "contract_version": contract.contract_version},
        )
        return new_contract


# -----------------------------
# Re-evaluation (docs/10) - minimal
# -----------------------------
class Lifecycle:
    def __init__(self, store: Store, policy: PolicyConfig):
        self.store = store
        self.policy = policy

    def drift_monitor(self, feature_id: str) -> None:
        # Minimal: compare last two LPS scores; if drift > tau → audit flag
        cur = self.store.conn.cursor()
        rows = cur.execute(
            """
            SELECT payload_json FROM lps_scorecards
            WHERE feature_id=?
            ORDER BY computed_at DESC LIMIT 2
            """,
            (feature_id,),
        ).fetchall()
        if len(rows) < 2:
            return
        s0 = json.loads(rows[0]["payload_json"])
        s1 = json.loads(rows[1]["payload_json"])
        drift = abs(float(s0["lps_total"]) - float(s1["lps_total"]))
        if drift > self.policy.tau_lps:
            self.store.audit("LPS_DRIFT", feature_id, {"drift": drift, "tau": self.policy.tau_lps})


# -----------------------------
# Demo Driver
# -----------------------------
def main() -> None:
    store = Store()

    policy = PolicyConfig(
        policy_version="policy_v1",
        w_link=0.25,
        w_uniq=0.25,
        w_infer=0.25,
        w_policy=0.25,
        a_id=0.5,
        a_join=0.3,
        a_ttl=0.2,
        deg_max=10,
        retention_days_max=365,
        band_mid=0.45,
        band_high=0.75,
        min_support_floor=10,
        distinct_drift_threshold=1000,
        infer_default=0.2,
        infer_high=0.7,
        tau_lps=0.1,
        central_sigma=4.0,  # used in example
        min_support_threshold=25,
    )

    controller = Controller(store, policy)
    runtime = Runtime(store)
    lifecycle = Lifecycle(store, policy)

    # 1) Catalog update
    click_rate = FeatureDef(
        feature_id="click_rate",
        feature_version="v1",
        owner="ads-team",
        query_type="MEAN_BOUNDED_0_1",
        join_keys=["campaign_id"],  # no stable user_id in this demo
        retention_days=30,
        sensitivity_tags=set(),  # treat as non-sensitive derived aggregate in this demo
        boundary_capabilities={"LOCAL", "SHUFFLE", "CENTRAL"},
        granularity_candidates={"ITEM", "CLUSTER", "AGGREGATE"},
    )
    controller.on_catalog_update([click_rate])

    # 2) Seed stats snapshots (W1 and W0) for each granularity
    # These should come from your catalog stats pipeline in production
    stats = [
        # W1
        StatsSnapshot("click_rate", "W1", "ITEM", n_obs=50, n_distinct_est=1_000_000, min_support_est=30, tail_mass_est=0.2, approx_variance=0.01 * 0.99 / 50),
        StatsSnapshot("click_rate", "W1", "CLUSTER", n_obs=10_000, n_distinct_est=10_000, min_support_est=8_000, tail_mass_est=0.1, approx_variance=0.01 * 0.99 / 10_000),
        StatsSnapshot("click_rate", "W1", "AGGREGATE", n_obs=10_000_000, n_distinct_est=1, min_support_est=10_000_000, tail_mass_est=0.0, approx_variance=0.01 * 0.99 / 10_000_000),
        # W0 (older window)
        StatsSnapshot("click_rate", "W0", "ITEM", n_obs=45, n_distinct_est=950_000, min_support_est=25, tail_mass_est=0.25, approx_variance=0.01 * 0.99 / 45),
        StatsSnapshot("click_rate", "W0", "CLUSTER", n_obs=9_500, n_distinct_est=9_800, min_support_est=7_500, tail_mass_est=0.12, approx_variance=0.01 * 0.99 / 9_500),
        StatsSnapshot("click_rate", "W0", "AGGREGATE", n_obs=9_500_000, n_distinct_est=1, min_support_est=9_500_000, tail_mass_est=0.0, approx_variance=0.01 * 0.99 / 9_500_000),
    ]
    for s in stats:
        store.upsert_stats(s)

    # 3) Optional inferability probe
    store.upsert_probe(ProbeResult("click_rate", "probe_1", metrics={"gender": 0.52, "age_bucket": 0.55}))

    # 4) LPS scoring + granularity selection + contract issuance
    controller.run_lps_scoring_batch(["click_rate"])
    controller.run_granularity_selection_batch(["click_rate"])
    controller.run_contract_issuance_batch(["click_rate"])

    # Show decision
    lps = store.read_latest_lps("click_rate")
    rd = store.read_latest_routing_decision("click_rate")
    ct = store.read_active_contract("click_rate")
    print("\n=== LPS ===")
    print(json.dumps(dataclasses.asdict(lps), indent=2))
    print("\n=== Routing Decision ===")
    print(json.dumps(dataclasses.asdict(rd), indent=2))
    print("\n=== Active Contract ===")
    print(json.dumps(dataclasses.asdict(ct), indent=2))

    # 5) Runtime ingest (simulate a few cells)
    # Note: cell_key should match selected granularity in production (item_id / cluster_id / etc.)
    for i in range(100):
        # simulate a cell with impressions ~ contract granularity expectation
        clicks = 1 if random.random() < 0.01 else 0
        runtime.ingest_signal("click_rate", window_id="W1", cell_key=f"cell_{i%10}", clicks=clicks, impressions=1)

    # 6) Materialize in the contract boundary
    runtime.materialize(boundary=ct.boundary, window_id="W1")

    # 7) Drift monitor (demo)
    lifecycle.drift_monitor("click_rate")

    # Print a few materialized rows
    cur = store.conn.cursor()
    rows = cur.execute(
        """
        SELECT boundary, feature_id, granularity, window_id, cell_key, value, contract_version
        FROM materialized_features
        WHERE feature_id='click_rate'
        LIMIT 10
        """
    ).fetchall()

    print("\n=== Materialized (sample) ===")
    for r in rows:
        print(dict(r))

    # Print last few audit events
    audit = cur.execute(
        """
        SELECT ts, event_type, feature_id, details_json
        FROM audit_log
        ORDER BY ts DESC LIMIT 8
        """
    ).fetchall()

    print("\n=== Audit (tail) ===")
    for r in audit:
        print({"ts": r["ts"], "event_type": r["event_type"], "feature_id": r["feature_id"], "details": json.loads(r["details_json"])})


if __name__ == "__main__":
    # Make demo deterministic-ish
    random.seed(7)
    main()
