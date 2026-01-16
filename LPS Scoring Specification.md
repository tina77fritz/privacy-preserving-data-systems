# LPS Scoring Specification

**Scope:** Feature-level privacy risk scoring for routing feasibility (Local / Shuffle / Central)

---

## 1. Purpose

The **Local DP Privacy Score (LPS)** is the project’s **privacy core**. It provides a **feature-level, auditable, and conservative** privacy risk score used to:

1. **Gate feasibility:** determine which privacy channels and granularities are admissible for a feature.  
2. **Standardize risk signals:** linkability, uniqueness, inferability, and policy constraints.  
3. **Enable automation:** produce deterministic routing constraints and explainable audit artifacts.

**Non-goal:** LPS does not itself provide formal privacy guarantees. Formal guarantees are provided by downstream DP mechanisms (Local/Shuffle/Central). LPS is a **risk-gating layer** that defines a feasible routing space.

---

## 2. LPS Definition

The **Local DP Privacy Score (LPS)** is a feature-level, configuration-time privacy risk metric that quantifies the **structural privacy exposure** of using a feature under privacy-preserving constraints.
LPS is a weighted combination of four sub-scores in the range `[0, 1]`.

```text
LPS(f) =
  w_link   * S_link(f)
+ w_uniq   * S_uniq(f)
+ w_infer  * S_infer(f)
+ w_policy * S_policy(f)
```
Where:

- `S_link(f)` ∈ [0, 1] is the **linkability score**,
- `S_uniq(f)` ∈ [0, 1] is the **uniqueness (singling-out) score**,
- `S_infer(f)` ∈ [0, 1] is the **inferability score**,
- `S_policy(f)` ∈ [0, 1] is the **policy penalty score**,

and the weights satisfy:

```text
S_* is in [0, 1]
w_link + w_uniq + w_infer + w_policy = 1
w_* ≥ 0
```
### Interpretation

- **Low LPS(f)** indicates that the feature is structurally safe and may be eligible for fine-grained use under appropriate DP mechanisms.
- **High LPS(f)** indicates elevated privacy risk, requiring coarser aggregation, stricter boundaries, or complete exclusion.

LPS is **monotonic with risk**: higher scores always imply weaker admissible usage.

---

### Conservative defaults

- If required inputs are missing, **score upward** (higher risk).
- Emit explicit **reason codes** for missing or degraded inputs.


---
## 3. Key Concepts

### 3.1 Feature

A named, versioned entity in the catalog with a stable `feature_id` and metadata describing:

- Source tables / pipelines  
- Join keys and join graph neighborhood  
- Retention/TTL  
- Intended use cases and sensitivity tags  
- Supported granularities and channels  

### 3.2 Score Granularity

LPS is computed **per feature**, not per user or per query.

### 3.3 Windows and Cadence

LPS uses a **two-window** approach:

- **Primary window (W1):** recent behavior, default **7 days**  
- **Baseline window (W0):** longer reference, default **28 days**  

LPS runs as:

- **Scheduled batch:** daily  
- **On-demand:** when feature contract/policy changes  

---

## 4. Sub-score: Linkability (S_link)

### 4.1 Risk Definition

**Linkability** measures how easily feature values can be connected across:

- Time (long retention)
- Tables (join graph richness)
- Identifiers (explicit or implicit stable keys)

High linkability increases re-identification and attribute inference risk, especially under fine-grained aggregation.

---

### 4.2 Inputs

**Sources and fields:**

- **Catalog / schema metadata (Control Plane)**
  - Join keys
  - Join graph degree / neighborhood
  - Presence of stable identifiers
  - Retention / TTL
  - Time resolution (event-time granularity)

- **Lineage metadata**
  - Upstream sources
  - Whether the feature is derived from user-level signals

---

### 4.3 Computation

Define linkability as a capped sum of normalized factors:

```text
S_link(f) = clamp01(
    a_id   * I_has_stable_id(f)
  + a_join * N_join_degree(f)
  + a_ttl  * N_retention(f)
)
```

Where:

- `I_has_stable_id(f)` ∈ `{0, 1}`
  - `1` if the feature is keyed by or derived from stable identifiers
    (e.g., user_id, device_id, account_id, hashed versions);
    `0` otherwise.

- `N_join_degree(f)` ∈ `[0, 1]`
  - Normalized join complexity derived from the join graph degree.

- `N_retention(f)` ∈ `[0, 1]`
  - Normalized retention / TTL factor.

**Normalization examples:**

```text
N_join_degree(f) = min(1, log(1 + deg(f)) / log(1 + deg_max))
N_retention(f)   = min(1, retention_days(f) / retention_days_max)
```

---

### 4.4 Window and Sampling

- `S_link` uses **metadata only**; no raw data scan.
- Recomputed whenever:
  - Schema or join relationships change
  - Retention / TTL changes
  - Feature lineage changes

---

### 4.5 Complexity and Scalability

- Per-feature computation: `O(1)` for identifier flags and TTL
- Join-degree lookup:
  - `O(1)` if join graph statistics are precomputed
  - `O(E)` to traverse neighborhood if computed on the fly (not recommended)
- Recommended approach:
  - Maintain join-degree and neighborhood metrics incrementally in the catalog


## 5. Sub-score: Uniqueness (S_uniq)

### 5.1 Risk Definition

**Uniqueness** measures singling-out risk via rare values or small cells. Even without explicit identifiers, rare values can enable identification when combined with auxiliary information.

### 5.2 Inputs

From **stats snapshots** (Data Plane): frequency sketches or approximate histograms.

Recommended fields in `feature_stats_ts`:

- `n_obs` (total observations per window)
- `n_distinct_est` (e.g., HLL)
- `min_support_est` (estimated smallest bucket count)
- `tail_mass_est` (fraction in bottom-q buckets)

Compute per supported granularity if available (item / cluster / aggregate).

### 5.3 Computation Options

**Option A (default): distinct-to-total proxy**

```text
r = n_distinct_est / max(1, n_obs)
S_uniq = clamp01( (r - r0) / (r1 - r0) )
```

Where `r0 < r1` are policy thresholds.

**Option B (recommended for count / frequency features): min-support proxy**

```text
S_uniq = clamp01( 1 - log(1 + min_support_est) / log(1 + n_obs) )
```

Interpretation: if `min_support_est` is small relative to `n_obs`, uniqueness is high.

**Option C: tail mass proxy**

```text
S_uniq = clamp01( tail_mass_est / tail_mass_max )
```

### 5.4 Window and Sampling Strategy

- Compute over W1 (7d) and compare with W0 (28d) for stability.
- If sketches are built from streams:
  - Use reservoir sampling per key; or
  - Compute sketches incrementally.

### 5.5 Complexity and Scalability

- With sketches (HLL, count-min, top-k):
  - Per feature per window: `O(1)` to read summary stats
- Without sketches (raw scans):
  - `O(N)` over events (not acceptable at scale)
- Requirement: `feature_stats_ts` stores summary stats so LPS scoring is metadata-driven.

---

## 6. Sub-score: Inferability (S_infer)

### 6.1 Risk Definition

**Inferability** measures whether a feature allows predicting protected or sensitive attributes (e.g., age, gender, precise location, health) beyond what is acceptable.

This captures model-based privacy leakage even when identifiers are removed.

### 6.2 Inputs

- Protected attribute definitions (`protected_attribute_registry`)
- Offline “probe dataset” (strictly controlled)
- Feature vectors derived under the same representation as runtime (bucketized / noised if applicable)
- Only derived metrics are persisted (AUC, accuracy). Never store raw labels or per-user predictions.

### 6.3 Probe Protocol

For each feature `f` and protected attribute `p`:

1. Build probe training data using a controlled sampling strategy.
2. Train a lightweight probe model `g_{f,p}` (e.g., logistic regression, shallow tree).
3. Evaluate predictive performance `M(f,p)` (e.g., AUC for binary).
4. Map `M(f,p)` to risk score `R(f,p)` in `[0, 1]`.
5. Aggregate across protected attributes.

Mapping example (binary AUC):

```text
R(f,p) =
  0                          if AUC <= 0.5
  min(1, 2 * (AUC - 0.5))    otherwise
```

Aggregation:

```text
S_infer(f) = max_p R(f,p)
```

### 6.4 Sampling Strategy

Inferability probes are expensive; do not run for every feature daily.

Recommended:

- **Tiered scheduling**
  - Tier 0: features tagged as sensitive -> weekly
  - Tier 1: features with rising `S_link` or `S_uniq` -> bi-weekly
  - Tier 2: others -> monthly or on-demand
- **Balanced sampling**
  - Sample up to `K` examples per class to avoid imbalance artifacts
- **Reproducibility**
  - Fixed random seeds per `feature_id + lps_version + window_id`

### 6.5 Complexity and Scalability

Let:

- `P` = number of protected attributes
- `d` = feature dimension (often small for single-feature probes)
- `m` = sample size

For logistic regression:

- Training: `O(P * m * d)`
- Scoring: `O(P * m * d)`

Scaling controls:

- Cap `m` (e.g., 50k)
- Run only on candidate-sensitive features
- Cache probe results and invalidate only on contract changes or drift


## 7. Sub-score: Policy Penalty (S_policy)

### 7.1 Risk Definition

**Policy penalty** enforces hard constraints that override optimization, regardless of estimated utility.

Examples:

- Direct identifiers
- Precise geolocation
- Child-related attributes
- Prohibited joins / purpose limitations

### 7.2 Inputs

- Policy DSL rules
- Feature sensitivity tags
- Lineage tags (e.g., "derived from user demographics")
- Jurisdiction flags (if applicable)

### 7.3 Computation

Policy penalty is rule-based:

```text
S_policy(f) =
  1.0      if hard_restricted(f)
  p_mid    if policy_sensitive(f) and not hard_restricted
  0.0      otherwise
```

Where `p_mid` (e.g., 0.5) is configurable.

Policy may also emit explicit constraints:

- `deny_channel = CENTRAL`
- `min_granularity = CLUSTER`
- `deny_join = true`

### 7.4 Complexity

- `O(#rules_matched)`; typically `O(1)` with indexed tags.

---

## 8. SQL / batch job Example

### 8.1 Scorecard Schema (stored and versioned)

The LPS job outputs a scorecard per feature per scoring run.

Example scorecard payload:

```json
{
  "run_id": "uuid",
  "feature_id": "f_xxx",
  "feature_version": "catalog_v123",
  "window_w1": { "start": "2026-01-08", "end": "2026-01-15" },
  "window_w0": { "start": "2025-12-18", "end": "2026-01-15" },

  "lps_total": 0.62,
  "s_link": 0.70,
  "s_uniq": 0.45,
  "s_infer": 0.60,
  "s_policy": 0.50,

  "weights": {
    "w_link": 0.35,
    "w_uniq": 0.25,
    "w_infer": 0.25,
    "w_policy": 0.15
  },

  "inputs": {
    "catalog_snapshot_id": "cat_snap_...",
    "policy_version": "policy_v7",
    "stats_snapshot_ids": ["stats_..._w1", "stats_..._w0"],
    "probe_run_id": "probe_... (optional)"
  },

  "reason_codes": [
    "POLICY_SENSITIVE_TAG:demographics",
    "LOW_MIN_SUPPORT:item_cells",
    "HIGH_JOIN_DEGREE"
  ],

  "lps_version": "lps_v1",
  "computed_at": "2026-01-15T00:00:00Z"
}
```

**Storage:**

- `lps_scorecard` (append-only)
- Optional: `lps_scorecard_latest` (materialized view)

### 8.2 Versioning Rules

- `lps_version` identifies scoring semantics (formulas, thresholds, mappings).
- A new `lps_version` is required if any of the following change:
  - Sub-score formulas
  - Normalization functions
  - Mapping functions (e.g., AUC -> risk)
  - Aggregation logic (e.g., max vs weighted max)
- Weights or thresholds may change under policy without bumping `lps_version`
  if the functional form is unchanged; always log `policy_version`.

## 9. QA

### 9.1 Drift Detection

**Goal:** detect when a feature’s privacy risk signals shift materially.

Compute drift signals:

```text
delta_link  = S_link_w1 - S_link_w0
delta_uniq  = S_uniq_w1 - S_uniq_w0
delta_infer = S_infer_latest - S_infer_prev
```

Trigger alerts if:

- `abs(delta_*) > tau_*` (policy thresholds), or
- LPS crosses a risk band boundary (e.g., `0.40`, `0.75`)

Also monitor:

- Join graph changes (degree spikes)
- Retention changes
- Min-support collapse at fine granularity
- Sudden distinct-count increases

Actions on drift:

- Mark feature as `needs_review`
- Force re-routing evaluation (`docs/07`)
- Optionally restrict channels until revalidated

---

### 9.2 Preventing Gaming (Bypass Resistance)

**Vector A: Feature splitting**  
(sensitive feature split into multiple features)

- Lineage-aware scoring: derived features inherit risk floor from parents
- Group-level penalties for feature families
- Cap total risk budget per domain/pipeline

**Vector B: Key renaming / schema obfuscation**

- Canonical key registry (semantic tags)
- Lineage-based stable-key propagation detection
- Require explicit join-key declaration; missing → conservative flag

**Vector C: Rare-value masking**  
(inflate bins / merge categories)

- Require `min_support_est` (or equivalent sketches)
- Compare W1 vs W0 stability; sudden shifts trigger review
- Enforce minimum binning standards per data type

**Vector D: Probe evasion**  
(frequent definition changes)

- Pin evaluation schedule per feature family/domain
- Require probe on first publish for sensitive domains
- Reuse probe results across minor versions where semantics unchanged

**Vector E: Contract drift without re-score**

- Enforce contract version checks at runtime ingestion
- Schema mismatch → reject writes
- Trigger controller re-score on catalog change events


## 10. Operational Considerations

### 10.1 Scheduling

Recommended jobs:

- `lps_scoring_daily` (all features; metadata + uniqueness + policy)
- `infer_probe_weekly` (sensitive candidates only)
- `drift_monitor_daily` (sub-score deltas + boundary crossing)

### 10.2 Failure Modes

- Missing stats -> set `S_uniq = 1` and emit reason code
- Missing catalog metadata -> set `S_link = 1` and emit reason code
- Probe failures -> set `S_infer` to conservative default (policy) and emit reason code

### 10.3 Audit Requirements

Every scorecard must be reproducible given:

- Catalog snapshot id
- Policy version
- Stats snapshot ids
- Probe run id (if any)
- LPS version

## 8. Worked Numerical Example (Numerical)

We illustrate granularity selection with a concrete numerical example.

### Feature

- Feature: `CTR_click_rate`
- Statistic: click-through rate (mean of Bernoulli)
- Privacy channel: Central DP
- DP mechanism: Gaussian
- Privacy budget: (ε = 1.0, δ = 1e-6)

### Candidate Granularities

| Granularity | Avg. cells | Avg. impressions per cell |
|------------|------------|---------------------------|
| ITEM       | 1,000,000  | 50                        |
| CLUSTER    | 10,000     | 10,000                    |
| AGGREGATE  | 1          | 10,000,000                |

### Privacy Noise

For Gaussian DP on mean estimation:

```text
Var_privacy_noise = σ² / N_eff
```

Assume calibrated σ² = 1.0 under (ε, δ).

### Effective Variance Computation

```text
EffVar(f, g) = Var_privacy_noise / N_eff
```

| Granularity | N_eff | EffVar |
|------------|-------|--------|
| ITEM       | 50    | 0.0200 |
| CLUSTER    | 10,000| 0.0001 |
| AGGREGATE  |10,000,000| 0.0000001 |

### Decision

- ITEM: high noise dominates signal → unstable
- CLUSTER: strong signal-to-noise tradeoff → optimal
- AGGREGATE: minimal noise but no heterogeneity

**Selected granularity:** `CLUSTER`

## 9. Granularity Selection Job Interface (KWDB)

### Input Tables

#### LPS Scorecard

```sql
CREATE TABLE lps_scorecard_latest (
  feature_id STRING,
  lps_total DOUBLE,
  min_granularity STRING,
  admissible_granularities ARRAY<STRING>,
  policy_version STRING,
  lps_version STRING
);
```

#### Feature Statistics (per granularity)

```sql
CREATE TABLE feature_stats_ts (
  feature_id STRING,
  granularity STRING,
  window_id STRING,
  n_obs BIGINT,
  min_support_est BIGINT,
  approx_variance DOUBLE
);
```

### Selection Query (Simplified)

```sql
SELECT
  f.feature_id,
  g.granularity,
  (dp.noise_variance / g.n_obs) AS eff_var
FROM lps_scorecard_latest f
JOIN feature_stats_ts g
  ON f.feature_id = g.feature_id
JOIN dp_policy dp
  ON f.policy_version = dp.policy_version
WHERE
  g.granularity IN UNNEST(f.admissible_granularities)
  AND g.min_support_est >= dp.min_support_threshold
QUALIFY
  eff_var = MIN(eff_var) OVER (PARTITION BY f.feature_id);
```

### Output

```sql
CREATE TABLE routing_decision (
  feature_id STRING,
  selected_granularity STRING,
  eff_var DOUBLE,
  decision_ts TIMESTAMP
);
```

## 10. Interaction with LPS (Admissible Set Ω(f))

Granularity selection is **conditional on privacy feasibility**.

For each feature `f`, LPS defines an admissible granularity set:

```text
Ω(f) ⊆ {ITEM, CLUSTER, AGGREGATE}
```

Where:

- Ω(f) is derived from:
  - LPS score
  - policy penalties
  - minimum allowed granularity

### Examples

| LPS Outcome | Ω(f) |
|------------|------|
| Low risk   | {ITEM, CLUSTER, AGGREGATE} |
| Medium risk| {CLUSTER, AGGREGATE} |
| High risk  | {AGGREGATE} |

Granularity selection **never evaluates options outside Ω(f)**.

Formally:

```text
g* = argmax_{g ∈ Ω(f)} Utility(f, g)
```

This guarantees:

- privacy constraints are never violated,
- optimization is restricted to safe structures,
- routing decisions are explainable and auditable.




