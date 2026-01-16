# Granularity Selection Specification
**Scope:** Selecting optimal data granularity (Item / Cluster / Aggregate)
           under privacy-induced noise and policy constraints.

---

## 1. Purpose

This part specifies how the system **selects the data granularity** (Item / Cluster / Aggregate) for each feature, **after privacy feasibility
has been established by LPS**.

The goal is to:

- maximize predictive utility under privacy noise,
- respect hard privacy and policy constraints,
- provide deterministic, auditable routing decisions,
- avoid per-signal decision-making at runtime.

 Granularity selection is a **configuration-time optimization problem**, not a runtime privacy check.

---

## 2. Problem Statement

Given a feature `f`:

- privacy feasibility is already determined (via LPS),
- allowed channels and minimum granularity may already be constrained,
- multiple granularities may still be admissible,

we must select a granularity `g ∈ {ITEM, CLUSTER, AGGREGATE}` that:

- provides the **highest expected utility**,
- under the **same privacy mechanism and budget**,
- while avoiding unstable or degenerate statistics.

---

## 3. Inputs

### 3.1 Required Inputs

For each feature `f`:

- LPS scorecard (from `LPS Scoring Specification.md`)
- Admissible routing set Ω(f)
- Historical stats snapshots per granularity:
  - observation count
  - approximate distinct count
  - min-support estimate
- Privacy mechanism parameters:
  - DP channel (Local / Shuffle / Central)
  - effective noise scale (policy-defined)

### 3.2 Optional Inputs

- Downstream model sensitivity to noise (if available)
- Fairness or stability constraints (future extension)

---

## 4. Candidate Granularities

Granularity options are defined structurally:

- **ITEM**
  - Per-item statistics (e.g., ad_slot, SKU, content_id)
  - Highest resolution, lowest sample support

- **CLUSTER**
  - Per-group statistics (e.g., category, region, cohort)
  - Balance between resolution and stability

- **AGGREGATE**
  - Global statistics
  - Lowest resolution, highest stability

Not all granularities are always admissible. The feasible set is restricted by:

- LPS-derived constraints
- Explicit policy rules
- Minimum-support requirements

---

## 5. Utility Model

### 5.1 Core Principle

Under differential privacy, **utility degradation is dominated by noise variance relative to signal strength**.

We evaluate each candidate granularity using **Effective Variance (EffVar)**,or equivalently **Signal-to-Noise Ratio (SNR)**.

---

### 5.2 Effective Variance

For a feature `f` at granularity `g`:

```text
EffVar(f, g) = Var_privacy_noise(g) / N_eff(f, g)
```
Where:

- `Var_privacy_noise(g)`
  - variance induced by the DP mechanism at granularity `g`

- `N_eff(f, g)`
  - effective sample size (e.g., expected count per cell)

**Intuition:**

- smaller cells → smaller `N_eff` → higher effective variance
- coarser aggregation → larger `N_eff` → lower effective variance

---

### 5.3 Signal-to-Noise Ratio (SNR)

Optionally, we compute:

```text
SNR(f, g) = Signal(f, g) / sqrt(Var_privacy_noise(g))
```

Where `Signal(f, g)` may be approximated by:

- empirical variance of the statistic across cells, or
- historical effect size proxy.

---

## 6. Granularity Selection Rule

### 6.1 Optimization Objective

Select granularity `g*` as:

```text
g* = argmax_g Utility(f, g)
```

Subject to:

- `g ∈ Ω(f)` (privacy feasibility)
- `MinSupport(f, g) >= threshold`
- policy-imposed minimum granularity

---

### 6.2 Default Utility Proxy

By default:

```text
Utility(f, g) = - EffVar(f, g)
```

(Equivalent to minimizing effective variance.)

---

## 7. Decision Algorithm (Pseudo-code)

```text
Input:
  feature f
  feasible granularities G = {g1, g2, ...}
  stats snapshots S(f, g)
  DP parameters

For each g in G:
  if MinSupport(f, g) < threshold:
    mark g as infeasible
  else:
    compute Var_privacy_noise(g)
    compute N_eff(f, g)
    compute EffVar(f, g)

Select g* with minimal EffVar
Persist routing decision (f, g*)
```

---

## 8. Outputs

The granularity selection step produces:

- `selected_granularity`
- supporting metrics:
  - `EffVar`
  - `N_eff`
  - min-support checks
- decision reason codes

Stored in:

- `routing_decision`
- `audit_ledger`

---

## 9. Failure Modes and Safeguards

- Missing stats → conservatively drop to coarser granularity
- Sudden distribution shift → trigger re-evaluation
- Inconsistent stats across windows → mark unstable

---

## 10. Summary

Granularity selection transforms privacy feasibility into **structural data usage decisions**.

By comparing effective variance under privacy noise across granularities, the system selects the **finest stable granularity** that remains privacy-compliant, statistically meaningful, and auditable.

This step is the bridge between **privacy constraints** and **model utility**.


## 11. Appendix - Worked Example 

This example shows how the controller selects the optimal granularity for a
**count/frequency feature** under a fixed privacy target.

### Step 0: Define the Feature and the Data Schema

**Feature:** `CTR` defined as % of click rate after impressions

**Data Schema:** 

| user_id | ad_id | category_id | click_ts | impression_ts | 
|-----------:|-------:|-------------------------------:|------------------:|------------------:|
| 11251     | tead1422 | makeup      | 12342570101 | 12342300129 |

We compare three granularities for this feature:

- `ITEM`: per-ad / per-user. 
- `CLUSTER`: per-category cell (e.g., category_id)
- `AGGREGATE`: global CTR (one cell total)
- 

---

### Step 1: Observed Metric - CTR

Assume a 1-day window **user CTR** is around:

We model click rate as a Bernoulli mean:

- Each impression produces `x ∈ {0, 1}` (click or not)
- The statistic we release is the mean click rate per cell:

```text
p = 0.01
```

So the user CTR variance from sampling is roughly:

```text
Var_sampling ≈ p(1-p)/N
```
---

### Step 2: Fix the Privacy Target and Mechanism

We choose a Central DP release of the **mean** using a Gaussian mechanism.

Privacy target:

```text
(ε, δ) = (1.0, 1e-6)
```

We assume each user can contribute at most **one impression per cell per day**
(or contributions are clipped to enforce this), so the sensitivity is bounded.

For CTR(mean) we release:

```text
μ = (1/N) * sum x
```

If `x ∈ [0, 1]`, then the **L2 sensitivity** of the mean is:

```text
Δ = 1/N
```

Gaussian noise added to the released mean:

```text
μ_hat = μ + Normal(0, σ^2 * Δ^2)
```

So the DP noise variance is:

```text
Var_DP = σ^2 * (1/N^2)
```

---

### Step 3: Calibrate σ (Noise Multiplier)

For the Gaussian mechanism, σ depends on (ε, δ).
Instead of deriving it here, assume policy calibration gives:

```text
σ = 4.0
```

(This is a realistic order-of-magnitude for ε=1, δ=1e-6 with conservative calibration.)

So:

```text
Var_DP = (4.0^2) * (1/N^2) = 16 / N^2
Std_DP = 4 / N
```

---
### Step 4: Compute DP Noise Magnitude at Each Granularity

| Granularity  | N  |  Std  |
|-----------:|-------:|-------:|
| User_id    | 50 | 0.08 |
| Category_id    | 10,000 | 0.0004 |
| Total    | 10,000,000 | 0.0000004 |

**Conclusion:** Given CTR is ~1%, ITEM(user_id) level 8% noise std completely overwhelms the signal. Category level is much smaller than the CTR magnitude (1%). Aggreated level is essentially negligible.

---

### Step 5: Compare “Effective Utility” via Total Variance

In a practical system, the released statistic is noisy due to:

- sampling noise (finite N)
- DP noise

Total variance proxy:

```text
Var_total ≈ Var_sampling + Var_DP
```

Compute each granualrity.
| Granularity  | Variance 
|-----------:|-------:|
| User_id    | 0.0812 | 
| Category_id    | 0.00107 | 
| Total    | 0.0000315 | 

---

### Step 6: Granularity Decision

Pick the finest granularity whose noise is "acceptable". "Acceptable" defined by a threshold on standard deviation:

```text
Std_total(f, g) <= τ
```

Choose τ = 0.005 (0.5% absolute CTR error tolerance):

- ITEM: 0.0812  > 0.005  (reject)
- CLUSTER: 0.00107 <= 0.005 (accept)
- AGGREGATE: 0.0000315 <= 0.005 (accept)

Among acceptable granularities, select the **finest**:

**Selected granularity: `CLUSTER`**

