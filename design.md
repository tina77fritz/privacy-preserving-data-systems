## 1) Local DP Privacy Score (LPS): Implementable Technical Metrics

LPS is a feature-level risk score computed before data is admitted to Central DP. It quantifies how dangerous it is to promote a signal beyond Local DP, considering:

- Semantic sensitivity (e.g.age/gender/location-like)
- Identifiability / uniqueness / sparsity (rare values, long-tail)
- Linkability (can be joined to other tables, stable across time)
- Inferability (can reconstruct sensitive attributes even after LDP)
- Local-DP exposure budget (effective ε used at the device/client)

The score must be:
- Auditable (decomposable into sub-scores)
- Composable across releases
- Cheap to compute at scale

### LPS Decomposition

Define LPS as a weighted sum of normalized sub-scores:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BLPS%7D(f)%20%3D%20%5Csigma%5Cleft(%5Csum_%7Bj%3D1%7D%5E6%20w_j%20%5Ccdot%20s_j(f)%5Cright)" alt="LPS formula">
</p>

where <img src="https://latex.codecogs.com/svg.latex?s_j(f)%20%5Cin%20%5B0%2C1%5D" alt="s_j(f)∈[0,1]"> and <img src="https://latex.codecogs.com/svg.latex?%5Csigma" alt="σ"> is optional (e.g., identity or logistic). The weights are policy-controlled.

---

#### (A) Semantic Sensitivity Score <img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Bsem%7D%7D" alt="s_sem">

A deterministic mapping from feature type/classification:

- **PII-like**: exact location, precise timestamp, device identifiers → 1.0
- **Quasi-identifiers**: coarse location, age bucket, gender → 0.6–0.9
- **Non-user data**: item metadata → 0.0–0.2

**Implementation**: curated taxonomy + allowlist/denylist in DB (no ML required).

---

#### (B) Uniqueness / Rarity Score <img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Buniq%7D%7D" alt="s_uniq">

Signals that take rare values are more re-identifiable even under LDP.
Use a k-anonymity-like proxy computed from (LDP) frequency estimates:

1. Estimate frequency of each category/value under LDP (or use safe historical aggregate)
2. Compute:

   **Tail mass formula**:
   <p align="center">
   <img src="https://latex.codecogs.com/svg.latex?%5Cfrac%7B%5Csum_%7Bv%3A%20%5Chat%7Bp%7D(v)%20%3C%20%5Ctau%7D%20%5Chat%7Bp%7D(v)%7D%7B%5Csum_v%20%5Chat%7Bp%7D(v)%7D" alt="Tail mass formula">
   </p>

   or **Min support**:
   <p align="center">
   <img src="https://latex.codecogs.com/svg.latex?%5Cmin_v%20%5Cleft(%5Chat%7Bp%7D(v)%20%5Ccdot%20N%5Cright)" alt="Min support">
   </p>

3. Normalize to [0,1]

**Interpretation**: long-tail-heavy or ultra-sparse signals → higher risk.

---

#### (C) Linkability Score <img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Blink%7D%7D" alt="s_link">

Even if each release is LDP-protected, linking across tables/time can raise risk.
Compute from:

- Presence of stable join keys (hashed IDs, stable device IDs) → high
- TTL / retention length → higher risk
- Join graph centrality (how many tables can join to this dataset) → higher risk

A simple version:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Blink%7D%7D%20%3D%20%5Ctext%7Bclip%7D%5Cleft(%5Calpha%20%5Ccdot%20%5Cmathbb%7B1%7D%5B%5Ctext%7Bstable%5C_key%7D%5D%20%2B%20%5Cbeta%20%5Ccdot%20%5Clog(1%20%2B%20%5Ctext%7Bjoin%5C_degree%7D)%20%2B%20%5Cgamma%20%5Ccdot%20%5Cfrac%7B%5Ctext%7Bretention%5C_days%7D%7D%7BT%7D%5Cright)" alt="Linkability score">
</p>

---

#### (D) Inferability Score <img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Binf%7D%7D" alt="s_inf">

"How well can an attacker predict a sensitive attribute from this feature even after LDP?"

**Implementation options** (choose one initially):

**D1. Predictive proxy** (fast):
- Train a simple classifier to predict protected attributes (age/gender/location bucket) from the released feature representation (LDP output)
- Use AUC uplift over baseline as inferability
- Normalize to [0,1]

**D2. Mutual-information proxy** (more theoretical):
- Use model-based MI estimate between feature output and sensitive attribute
- Normalize

---

#### (E) Local DP Exposure Score <img src="https://latex.codecogs.com/svg.latex?s_%5Cvarepsilon" alt="s_ε">

If local ε is large or repeated too often (composition), risk increases.

Compute:

1. Effective ε over a window:
   <p align="center">
   <img src="https://latex.codecogs.com/svg.latex?%5Cvarepsilon_%7B%5Ctext%7Beff%7D%7D%20%3D%20%5Csum_t%20%5Cvarepsilon_t" alt="Effective epsilon">
   </p>

2. Normalize:
   <p align="center">
   <img src="https://latex.codecogs.com/svg.latex?s_%5Cvarepsilon%20%3D%20%5Ctext%7Bclip%7D%5Cleft(%5Cfrac%7B%5Cvarepsilon_%7B%5Ctext%7Beff%7D%7D%7D%7B%5Cvarepsilon_%7B%5Cmax%7D%7D%5Cright)" alt="Epsilon score">
   </p>

---

#### (F) Temporal Stability Score <img src="https://latex.codecogs.com/svg.latex?s_%7B%5Ctext%7Bstab%7D%7D" alt="s_stab">

Stable signals across time can be linked and deanonymized more easily.

Compute:
- Autocorrelation / persistence rate across days (on safe aggregates)
- Fraction of users with same value repeated
- Normalize to [0,1]

---

### Breakdown By Routing Tiers 

Define thresholds:

- **High risk**: LPS ≥ 0.75 → **Aggregate-only** (item/global aggregation, no Central DP raw)
- **Medium risk**: 0.40 ≤ LPS < 0.75 → **Shuffle DP** under ε constraint
- **Low risk**: LPS < 0.40 → eligible for **Central DP** if IBV is sufficient

**Add IBV gating** (your requirement):

- If **Low risk** AND **IBV high** → Central DP item-level permitted
- If **Low risk** but **IBV low** → still aggregate (not worth the risk/budget)

This separates "privacy risk" from "worth it".


## Output

Persist a scorecard per feature:

- **Overall LPS** - Final computed risk score
- **Each sub-score**:
  - <img src="https://latex.codecogs.com/svg.latex?s_{\text{sem}}" alt="s_sem"> - Semantic sensitivity
  - <img src="https://latex.codecogs.com/svg.latex?s_{\text{uniq}}" alt="s_uniq"> - Uniqueness/rarity
  - <img src="https://latex.codecogs.com/svg.latex?s_{\text{link}}" alt="s_link"> - Linkability
  - <img src="https://latex.codecogs.com/svg.latex?s_{\text{inf}}" alt="s_inf"> - Inferability
  - <img src="https://latex.codecogs.com/svg.latex?s_{\varepsilon}" alt="s_ε"> - Local DP exposure
  - <img src="https://latex.codecogs.com/svg.latex?s_{\text{stab}}" alt="s_stab"> - Temporal stability
- **Weights used** - Policy-controlled weighting parameters
- **Computation metadata**:
  - Computation window
  - Data source
  - Model version (if D1 predictive proxy used)

This audit trail is essential for governance and compliance verification.


## 4. Granularity Selection

Once a route is allowed, the system must choose granularity:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?g%20%5Cin%20%5C%7B%5Ctext%7BITEM%7D%2C%20%5Ctext%7BCLUSTER%7D%2C%20%5Ctext%7BAGGREGATE%7D%5C%7D" alt="g ∈ {ITEM, CLUSTER, AGGREGATE}">
</p>

This step is not handled by DP mechanisms and is the key optimization.

### 4.1 Optimization Objective

For a count / frequency feature <img src="https://latex.codecogs.com/svg.latex?f" alt="f">, select:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?g%5E*%20%3D%20%5Carg%5Cmin_g%20%5Cleft%5B%20%5Clambda%20%5Ccdot%20%5Ctext%7BVar%7D_%7B%5Ctext%7BDP%7D%7D(%5Chat%7Bc%7D_g)%20%2B%20%5CDelta%20L_%7B%5Ctext%7Bagg%7D%7D(g)%20%5Cright%5D" alt="g* = argmin_g [λ·Var_DP(ĉ_g) + ΔL_agg(g)]">
</p>

Where:

- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BVar%7D_%7B%5Ctext%7BDP%7D%7D(%5Chat%7Bc%7D_g)" alt="Var_DP(ĉ_g)">: noise-induced variance under the chosen DP route
- <img src="https://latex.codecogs.com/svg.latex?%5CDelta%20L_%7B%5Ctext%7Bagg%7D%7D(g)" alt="ΔL_agg(g)">: information loss from aggregation
- <img src="https://latex.codecogs.com/svg.latex?%5Clambda" alt="λ">: feature sensitivity to noise (configurable or estimated)

### 4.2 Noise Variance (Computable)

For Shuffle DP with randomized response–style frequency estimation:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BVar%7D_%7B%5Ctext%7BDP%7D%7D(%5Chat%7Bc%7D_g)%20%5Capprox%20n_g%20%5Ccdot%20%5Cfrac%7Be%5E%7B%5Cvarepsilon_0(g)%7D%20%2B%201%7D%7B(e%5E%7B%5Cvarepsilon_0(g)%7D%20-%201)%5E2%7D" alt="Var_DP(ĉ_g) ≈ n_g · (e^{ε₀(g)} + 1)/(e^{ε₀(g)} - 1)²">
</p>

Where:

- <img src="https://latex.codecogs.com/svg.latex?n_g" alt="n_g">: effective support size at granularity <img src="https://latex.codecogs.com/svg.latex?g" alt="g">
- <img src="https://latex.codecogs.com/svg.latex?%5Cvarepsilon_0(g)" alt="ε₀(g)">: local parameter derived via shuffle amplification

Approximation:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Cvarepsilon_0(g)%20%5Capprox%20%5Cvarepsilon%20%5Ccdot%20%5Cfrac%7B%5Csqrt%7Bn_g%7D%7D%7B%5Clog(1%2F%5Cdelta)%7D" alt="ε₀(g) ≈ ε · √n_g / log(1/δ)">
</p>

**Monotonic property**:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?n_%7B%5Ctext%7BITEM%7D%7D%20%5Cll%20n_%7B%5Ctext%7BCLUSTER%7D%7D%20%5Cll%20n_%7B%5Ctext%7BAGGREGATE%7D%7D%20%5CRightarrow%20%5Ctext%7BVar%7D_%7B%5Ctext%7BITEM%7D%7D%20%5Cgg%20%5Ctext%7BVar%7D_%7B%5Ctext%7BCLUSTER%7D%7D%20%5Cgg%20%5Ctext%7BVar%7D_%7B%5Ctext%7BAGGREGATE%7D%7D" alt="n_ITEM ≪ n_CLUSTER ≪ n_AGGREGATE ⇒ Var_ITEM ≫ Var_CLUSTER ≫ Var_AGGREGATE">
</p>

### 4.3 Aggregation Loss <img src="https://latex.codecogs.com/svg.latex?%5CDelta%20L_%7B%5Ctext%7Bagg%7D%7D" alt="ΔL_agg">

Two supported estimators:

**A. Oracle Ablation (Offline)**

Train models with no privacy noise under each granularity and measure loss gap.

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5CDelta%20L_%7B%5Ctext%7Bagg%7D%7D(g)%20%3D%20L_%7B%5Ctext%7Boracle%7D%7D(g)%20-%20L_%7B%5Ctext%7Boracle%7D%7D(%5Ctext%7BITEM%7D)" alt="ΔL_agg(g) = L_oracle(g) - L_oracle(ITEM)">
</p>

**B. Heterogeneity Proxy (Online)**

Use item-level effect dispersion:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5CDelta%20L_%7B%5Ctext%7Bagg%7D%7D(g)%20%5Cpropto%20%5Ctext%7BVar%7D(%5Cbeta_i)" alt="ΔL_agg(g) ∝ Var(β_i)">
</p>

### 4.4 Decision Outcome

The selected granularity is materialized only for the allowed route.

**Examples**:
- `SHUFFLE_DP + CLUSTER`
- `CENTRAL_DP + ITEM`
- `LOCAL_DP + AGGREGATE`

# Runtime Plane: Contract-Driven Execution Under Privacy Constraints

The Runtime Plane is the execution substrate of the privacy-aware data system. Its sole responsibility is to materialize features under the exact representation constraints compiled by the Control Plane. It does not make privacy decisions, reinterpret policy, or adapt representation choices at runtime. Instead, it enforces privacy as a structural invariant of the dataflow.

This separation is intentional. In conventional data systems, privacy enforcement is often implemented as a collection of runtime checks, query rewrites, or access-layer filters. Such mechanisms are inherently fragile: they depend on correct operator ordering, consistent query patterns, and human discipline. In contrast, the Runtime Plane is designed to eliminate unsafe intermediate representations by construction. It only executes pipelines whose representation form has already been proven privacy-feasible.

At the center of the Runtime Plane is a versioned `ContractBundle`, produced by the Control Plane. This contract specifies the schema, trust boundary, granularity, transformation semantics, safeguards, and DP configuration under which a feature is allowed to exist. Runtime does not possess the authority to widen any of these dimensions.

## Representation-First Execution Semantics

The fundamental design principle of the Runtime Plane is that privacy risk is dominated by representation choices, not by downstream query operators. Accordingly, runtime execution is structured around representation-level constraints rather than operator-level enforcement.

Every runtime path—`LOCAL`, `SHUFFLE`, and `CENTRAL`—shares a common semantic foundation:

*   A deterministic `TransformPlan` defines how raw signals are mapped into a policy-safe semantic form.
*   Contribution bounding ensures that no single entity can dominate any aggregate.
*   Aggregation is performed strictly at the granularity approved by the Control Plane.
*   Safeguards (e.g., k-thresholds, downgrade rules) are enforced as invariants over the materialized representation.
*   Noise injection occurs only at representation-approved boundaries.

This architecture ensures that privacy guarantees are enforced structurally, rather than opportunistically.

## Boundary-Specific Semantics

The Runtime Plane supports three execution boundaries—`LOCAL`, `SHUFFLE`, and `CENTRAL`—each corresponding to a different trust radius and attribution model. These are not deployment choices; they are representation constraints compiled into the contract.

### Local Path

In the `LOCAL` path, all privacy-sensitive transformations occur on the client. Raw signals are transformed, bucketized, contribution-bounded, encoded, and randomized before transmission. The server only observes randomized reports.

This path enforces unlinkability and attribution protection by ensuring that the server never sees raw or semi-raw feature values. The estimator at the server reconstructs aggregates in expectation, but no individual report is semantically meaningful.

The `LOCAL` path is structurally incapable of producing linkable raw features, regardless of downstream access controls.

### Shuffle Path

In the `SHUFFLE` path, attribution is broken through message mixing. Clients emit lightly transformed or randomized messages that are passed through a shuffler which permutes and batches reports before forwarding them to the server.

This breaks sender–message linkage without requiring full local randomization. The server aggregates shuffled messages and applies an estimator to reconstruct statistics. Optional central noise may be layered on top.

The `SHUFFLE` path occupies an intermediate trust envelope: higher fidelity than pure local DP, but with structural unlinkability guarantees stronger than central DP alone.

### Central Path

In the `CENTRAL` path, raw signals are processed within a server-side trust boundary under strict isolation. `TransformPlan` and contribution bounding are applied server-side, followed by pre-aggregation into ephemeral staging tables.

These staging tables are **not** treated as analytics assets. They are subject to TTL, isolation, access restrictions, and segmentation policies compiled into the `ContractBundle`. Small-cell exposure is structurally prevented via k-threshold filters and downgrade rules before any release.

Noise is injected only at release time. No unsafe intermediate representation is ever materialized into a long-lived, queryable form.

## Contract-Driven Determinism

A defining property of the Runtime Plane is that it is contract-driven and deterministic.

Given a `ContractBundle` **C** and an input event stream **E**, the released table **T** is a pure function:

**T = Runtime(C, E)**

All runtime behavior—schema shape, grouping keys, aggregation resolution, transformation semantics, safeguard enforcement, and noise configuration—is fixed by the contract.

This eliminates the possibility of privacy drift caused by query evolution, operator reordering, or downstream misuse. If a representation is not encoded in the contract, it cannot be materialized at runtime.

## Structural Safeguards and Downgrade Semantics

The Runtime Plane enforces structural safeguards that are invariant under data distribution shift.

The most important of these is the *downgrade mechanism*: if any aggregate cell violates the minimum support threshold `k_min`, the runtime does not suppress or mask the cell. Instead, it re-aggregates the entire feature at the next coarser granularity approved by the Control Plane.

This ensures that:
1.  small-cell exposure cannot occur even under skew or drift,
2.  privacy violations are resolved by representation change, not output filtering,
3.  the system degrades gracefully toward safer semantic forms.

This mechanism guarantees that the released representation always lies within the feasible privacy envelope defined by the Control Plane.

## Why the Runtime Plane Is Necessary

The Runtime Plane exists because privacy failures in production systems almost never arise from incorrect noise formulas. They arise from:

*   unsafe intermediate tables being accidentally materialized,
*   joins that reintroduce identifiers,
*   analysts querying raw or semi-raw staging data,
*   small cells leaking sensitive information under skew,
*   downstream queries widening the trust envelope implicitly.

The Runtime Plane eliminates these failure modes by construction. It treats staging as *raw within boundary*, treats materialized outputs as the only safe artifacts, and enforces representation constraints as non-negotiable invariants.

## Role in the Overall Architecture

*   **The Control Plane** determines *what representations are allowed to exist*.
*   **The Runtime Plane** ensures that *no other representations can exist*.

Together, they transform privacy from an access-layer concern into a representation-layer invariant. This is the core architectural shift of the system.

# Control Plane: Formal Definitions for C2 / C3 / C4

This section formalizes the core computational objects used by the Control Plane:
the policy-safe schema transformation (C2), the representation risk model (LPS, input to C3),
the boundary decision rule (C3), and the granularity refinement rule (C4).

All quantities defined below are deterministic, versioned, and auditable.

---

## C2 — Policy-Safe Schema Transformation

Each feature begins as a normalized feature specification:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?F%20%3D%20(S%2C%20K%2C%20D%2C%20T)" alt="F = (S, K, D, T)">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?S%20%3D%20%5C%7Bf_1%2C%20f_2%2C%20%5Cdots%2C%20f_n%5C%7D" alt="S = {f₁, f₂, ..., fₙ}"> is the raw field set  
- <img src="https://latex.codecogs.com/svg.latex?K%20%5Csubseteq%20S" alt="K ⊆ S"> is the set of join-enabling keys  
- <img src="https://latex.codecogs.com/svg.latex?D%20%5Csubseteq%20S" alt="D ⊆ S"> is the set of dimension fields  
- <img src="https://latex.codecogs.com/svg.latex?T" alt="T"> is the target statistic (e.g., count, sum, mean, rate)

Let the organizational privacy policy be:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?P%20%3D%20%5C%7Bp_1%2C%20p_2%2C%20%5Cdots%2C%20p_m%5C%7D" alt="P = {p₁, p₂, ..., pₘ}">
</p>

We define a deterministic schema transformation:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5CPhi_P(F)%20%3D%20(S%27%2C%20K%27%2C%20D%27%2C%20T%27)" alt="Φₚ(F) = (S', K', D', T')">
</p>

subject to the following rules.

---

### 1. Identifier Elimination

Let <img src="https://latex.codecogs.com/svg.latex?I_P" alt="I_P"> be the set of forbidden identifiers defined by policy <img src="https://latex.codecogs.com/svg.latex?P" alt="P">
(e.g., user_id, device_id, session_id).

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?S%27%20%3D%20S%20%5Csetminus%20I_P" alt="S' = S \ I_P">
</p>

---

### 2. Dimension Coarsening

Each retained dimension <img src="https://latex.codecogs.com/svg.latex?d%20%5Cin%20D%20%5Csetminus%20I_P" alt="d ∈ D \ I_P"> is transformed by a policy-approved
bucketization or generalization function <img src="https://latex.codecogs.com/svg.latex?g_d" alt="g_d">.

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?D%27%20%3D%20%5Cbigcup_%7Bd%20%5Cin%20D%20%5Csetminus%20I_P%7D%20g_d(d)" alt="D' = ⋃_{d ∈ D \ I_P} g_d(d)">
</p>

Each <img src="https://latex.codecogs.com/svg.latex?g_d%20%3A%20%5Ctext%7BDom%7D(d)%20%5Cto%20%5Ctext%7BDom%7D(d%27)" alt="g_d: Dom(d) → Dom(d')"> maps raw values into approved buckets.

---

### 3. Join-Surface Reduction

Join keys are restricted to fields that remain after policy filtering.

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?K%27%20%3D%20K%20%5Ccap%20S%27" alt="K' = K ∩ S'">
</p>

---

### 4. Transform Plan Compilation

The TransformPlan is compiled as:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?T%27%20%3D%20(T%2C%20%5C%7Bg_d%5C%7D%2C%20%5C%7B%5Ctext%7Bclip%7D_f%5C%7D)" alt="T' = (T, {g_d}, {clip_f})">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?g_d" alt="g_d"> are the bucketization / generalization functions  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Bclip%7D_f" alt="clip_f"> are contribution-bounding functions associated with each numeric field

The output of C2 is the policy-safe schema:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?S_P%20%3D%20(S%27%2C%20K%27%2C%20D%27%2C%20T%27)" alt="S_P = (S', K', D', T')">
</p>

This schema is the canonical privacy-normalized semantic form of the feature.
All downstream representation decisions operate exclusively on <img src="https://latex.codecogs.com/svg.latex?S_P" alt="S_P">.

---

## C3 — Representation Risk Model (LPS)

Representation-level privacy risk is captured by persistent Local Privacy Scorecards (LPS)
attached to policy-safe schemas.

For a policy-safe schema <img src="https://latex.codecogs.com/svg.latex?S_P" alt="S_P"> and a candidate granularity <img src="https://latex.codecogs.com/svg.latex?g" alt="g">,
the scorecard is defined as:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BLPS%7D(S_P%2C%20g)%20%3D%20(L(S_P)%2C%20U(S_P%2C%20g)%2C%20I(S_P)%2C%20R(S_P))" alt="LPS(S_P, g) = (L(S_P), U(S_P, g), I(S_P), R(S_P))">
</p>

---

### 1. Linkability Component

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?L(S_P)%20%3D%20%5Csum_%7Bk%20%5Cin%20K%27%7D%20%5C%5B%20w_k%20%5Ctimes%20%5Ctext%7Bstab%7D(k)%20%5C%5D" alt="L(S_P) = Σ_{k∈K'} [w_k × stab(k)]">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?K%27" alt="K'"> are retained join keys  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Bstab%7D(k)%20%5Cin%20%5B0%2C%201%5D" alt="stab(k) ∈ [0,1]"> is the temporal stability of key <img src="https://latex.codecogs.com/svg.latex?k" alt="k">  
- <img src="https://latex.codecogs.com/svg.latex?w_k%20%5Cgeq%200" alt="w_k ≥ 0"> is a key-specific weight

---

### 2. Uniqueness / Small-Cell Component

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?U(S_P%2C%20g)%20%3D%20%5Cmathbb%7BE%7D%5Cleft%5B%20%5Cfrac%7B1%7D%7B%5Ctext%7Bsupp%7D(c)%7D%20%5Cright%5D" alt="U(S_P, g) = 𝔼[1/supp(c)]">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?g" alt="g"> is a candidate granularity (ITEM, CLUSTER, AGGREGATE)  
- <img src="https://latex.codecogs.com/svg.latex?c" alt="c"> is a cell induced by grouping under <img src="https://latex.codecogs.com/svg.latex?g" alt="g">  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Bsupp%7D(c)" alt="supp(c)"> is the support (number of distinct entities) in cell <img src="https://latex.codecogs.com/svg.latex?c" alt="c">  
- the expectation is taken over historical or simulated data

---

### 3. Inferability Component

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?I(S_P)%20%3D%20%5Cmax_%7Ba%20%5Cin%20A_%7B%5Ctext%7Bsensitive%7D%7D%7D%20%5Ctext%7BMI%7D(a%3B%20S_P)" alt="I(S_P) = max_{a∈A_sensitive} MI(a; S_P)">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?A_%7B%5Ctext%7Bsensitive%7D%7D" alt="A_sensitive"> is the set of sensitive attributes  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BMI%7D(a%3B%20S_P)" alt="MI(a; S_P)"> is the mutual information between <img src="https://latex.codecogs.com/svg.latex?a" alt="a"> and the retained fields in <img src="https://latex.codecogs.com/svg.latex?S_P" alt="S_P">

---

### 4. Policy Penalty Component

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?R(S_P)%20%3D%20%5Csum_%7Bp%20%5Cin%20P_%7B%5Ctext%7Bapplicable%7D%7D%7D%20%5Clambda_p" alt="R(S_P) = Σ_{p∈P_applicable} λ_p">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?P_%7B%5Ctext%7Bapplicable%7D%7D%20%5Csubseteq%20P" alt="P_applicable ⊆ P"> are policies triggered by <img src="https://latex.codecogs.com/svg.latex?S_P" alt="S_P">  
- <img src="https://latex.codecogs.com/svg.latex?%5Clambda_p%20%5Cgeq%200" alt="λ_p ≥ 0"> is the penalty weight for policy <img src="https://latex.codecogs.com/svg.latex?p" alt="p">

---

### 5. Aggregated Representation Risk

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Cbegin%7Baligned%7D%0A%5Ctext%7BRisk%7D(S_P%2C%20g)%20%26%3D%20%5Calpha_L%20%5Ctimes%20L(S_P)%20%5C%5C%0A%26%5Cquad%20%2B%20%5Calpha_U%20%5Ctimes%20U(S_P%2C%20g)%20%5C%5C%0A%26%5Cquad%20%2B%20%5Calpha_I%20%5Ctimes%20I(S_P)%20%5C%5C%0A%26%5Cquad%20%2B%20%5Calpha_R%20%5Ctimes%20R(S_P)%0A%5Cend%7Baligned%7D" alt="Risk formula">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?%5Calpha_L%2C%20%5Calpha_U%2C%20%5Calpha_I%2C%20%5Calpha_R%20%5Cgeq%200" alt="α_L, α_U, α_I, α_R ≥ 0"> are system weights  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BRisk%7D(S_P%2C%20g)" alt="Risk(S_P, g)"> is a scalar representation-level risk score

LPS is catalog-level, versioned, and independent of runtime execution.

---

## C3 — Boundary Decision Rule

Let the available trust boundaries be:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?B%20%3D%20%5C%7B%5Ctext%7BLOCAL%7D%2C%20%5Ctext%7BSHUFFLE%7D%2C%20%5Ctext%7BCENTRAL%7D%5C%7D" alt="B = {LOCAL, SHUFFLE, CENTRAL}">
</p>

Each boundary <img src="https://latex.codecogs.com/svg.latex?b%20%5Cin%20B" alt="b ∈ B"> is associated with a maximum allowable risk threshold <img src="https://latex.codecogs.com/svg.latex?%5Ctau_b" alt="τ_b">.

Let <img src="https://latex.codecogs.com/svg.latex?g_%7B%5Cmin%7D(b)" alt="g_min(b)"> denote the finest granularity permitted under boundary <img src="https://latex.codecogs.com/svg.latex?b" alt="b">.

We define boundary feasibility as:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BFeasible%7D(b%2C%20S_P)%20%5Cequiv%20%5Ctext%7BRisk%7D(S_P%2C%20g_%7B%5Cmin%7D(b))%20%5Cle%20%5Ctau_b" alt="Feasible(b, S_P) ≡ Risk(S_P, g_min(b)) ≤ τ_b">
</p>

The boundary selection rule is:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?b%5E*%20%3D%20%5Cunderset%7Bb%20%5Cin%20B%7D%7B%5Coperatorname%7Barg%5C%2Cmax%7D%7D%20%5C%2C%20%5Ctext%7Butility%7D(b)%20%5Cquad%20%5Ctext%7Bsubject%20to%7D%20%5Cquad%20%5Ctext%7BFeasible%7D(b%2C%20S_P)" alt="b* = argmax_{b∈B} utility(b) subject to Feasible(b, S_P)">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Butility%7D(b)" alt="utility(b)"> is a monotonic preference score over boundaries  
  (e.g., CENTRAL > SHUFFLE > LOCAL)

The selected <img src="https://latex.codecogs.com/svg.latex?b%5E*" alt="b*"> defines the trust envelope within which all subsequent
granularity refinement must occur.

---

## C4 — Granularity Refinement Rule

Let the candidate granularity set be:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?G%20%3D%20%5C%7B%5Ctext%7BITEM%7D%2C%20%5Ctext%7BCLUSTER%7D%2C%20%5Ctext%7BAGGREGATE%7D%5C%7D" alt="G = {ITEM, CLUSTER, AGGREGATE}">
</p>

Given a fixed boundary <img src="https://latex.codecogs.com/svg.latex?b%5E*" alt="b*">, the representation utility of granularity <img src="https://latex.codecogs.com/svg.latex?g%20%5Cin%20G" alt="g ∈ G"> is:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?U(g)%20%3D%20%5Cfrac%7B%5Ctext%7Bsignal%5C_power%7D(S_P%2C%20g)%7D%7B%5Ctext%7Bnoise%5C_variance%7D(b%5E*%2C%20g)%7D" alt="U(g) = signal_power(S_P,g)/noise_variance(b*,g)">
</p>

where:

- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Bsignal%5C_power%7D(S_P%2C%20g)" alt="signal_power(S_P,g)"> measures heterogeneity retained under granularity <img src="https://latex.codecogs.com/svg.latex?g" alt="g">  
- <img src="https://latex.codecogs.com/svg.latex?%5Ctext%7Bnoise%5C_variance%7D(b%5E*%2C%20g)" alt="noise_variance(b*,g)"> is the effective variance induced by DP noise
  under boundary <img src="https://latex.codecogs.com/svg.latex?b%5E*" alt="b*"> and granularity <img src="https://latex.codecogs.com/svg.latex?g" alt="g">

Granularity feasibility is defined as:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?%5Ctext%7BRisk%7D(S_P%2C%20g)%20%5Cle%20%5Ctau_g" alt="Risk(S_P, g) ≤ τ_g">
</p>

where <img src="https://latex.codecogs.com/svg.latex?%5Ctau_g" alt="τ_g"> is a granularity-specific risk threshold.

The granularity selection rule is:

<p align="center">
<img src="https://latex.codecogs.com/svg.latex?g%5E*%20%3D%20%5Cunderset%7Bg%20%5Cin%20G%7D%7B%5Coperatorname%7Barg%5C%2Cmax%7D%7D%20%5C%2C%20U(g)%20%5Cquad%20%5Ctext%7Bsubject%20to%7D%20%5Cquad%20%5Ctext%7BRisk%7D(S_P%2C%20g)%20%5Cle%20%5Ctau_g" alt="g* = argmax_{g∈G} U(g) subject to Risk(S_P,g) ≤ τ_g">
</p>

The selected <img src="https://latex.codecogs.com/svg.latex?g%5E*" alt="g*"> is the finest resolution admissible within the
trust envelope defined by <img src="https://latex.codecogs.com/svg.latex?b%5E*" alt="b*">.

---

---

## Core Design Principles

### 1) Privacy as a First-Class Optimization Constraint

The Control Plane treats privacy risk as a quantifiable input to system design, not an after-the-fact filter. Rather than assuming that de-identification or DP noise alone is sufficient, it models privacy risk structurally: how linkable a feature is, how unique its realizations are, how inferable sensitive attributes become when it is joined, and how much policy exposure it carries.

This risk is not binary (“allowed” vs. “forbidden”). It is *graded* across candidate granularities and boundaries. A feature may be safe at cluster level but unsafe at item level; safe under Shuffle DP but unsafe under Central DP; acceptable for training but not for delivery. The Control Plane’s role is to surface these distinctions and encode them into binding constraints.

---

### 2) Utility Is Intent-Dependent, Not Intrinsic

A feature’s value is not intrinsic to the raw signal; it depends on the modeling objective and the representation used. Item-level heterogeneity may be crucial for one task and irrelevant for another. Aggregation may dramatically reduce noise variance under DP but may also erase the very structure the model needs.

The Control Plane therefore does not treat “feature usefulness” as a scalar property. Instead, it reasons about *expected marginal utility* at different granularities and under different noise regimes. It formalizes the idea that:

> The best privacy-preserving representation is the one that maximizes downstream utility *subject to privacy and fairness constraints*.

This reframes privacy not as a compliance tax but as a design-space constraint within a structured optimization problem.

---

### 3) Boundary Selection Is a Trust Decision, Not a Mechanism Choice

Local DP, Shuffle DP, and Central DP are not interchangeable implementations of the same idea. They correspond to fundamentally different trust assumptions:

- **Local DP** assumes the server is untrusted and shifts noise to the client.
- **Shuffle DP** assumes an honest-but-curious server but relies on unlinkability amplification.
- **Central DP** assumes a trusted boundary but enforces formal release guarantees.

The Control Plane treats boundary selection as a **trust and threat-model decision**, not as a purely technical one. It explicitly binds each feature to a boundary based on its risk profile, the system’s operational trust assumptions, and the severity of downstream misuse.

This prevents architectural drift where highly sensitive features are silently processed under weaker guarantees simply because the pipeline happens to support them.

---

### 4) Granularity Is the Primary Privacy–Utility Control Knob

The system is designed around the insight that *granularity*, not just noise magnitude, is the dominant driver of both privacy risk and signal quality.

- Item-level representations maximize heterogeneity but amplify uniqueness and linkability.
- Cluster-level representations preserve structure while dramatically reducing risk.
- Aggregate-level representations minimize risk but collapse most modeling signal.

The Control Plane makes granularity a **first-class decision variable**. It does not assume that finer granularity is always better or that aggregation is always safer. Instead, it selects granularity based on:

- expected signal-to-noise ratio under the chosen DP mechanism,
- privacy risk gradients across granularities,
- fairness exposure (e.g., small-cell bias),
- stability under opt-out or missingness.

This enables systematic, principled downgrading (item → cluster → aggregate) instead of ad-hoc suppression.

---

## Conceptual Phases of the Control Plane

The Control Plane is structured into conceptual phases. These are not runtime steps but *logical responsibilities*.

---

### Phase 1 — Feature Intent Formalization

The system begins by formalizing what a feature *is supposed to mean*, not how it is computed.

This phase produces a canonical feature specification: what signal is measured, what modeling purpose it serves, what candidate dimensions might be included, and what outputs are expected. The goal is to remove ambiguity: privacy and fairness reasoning cannot be applied to an underspecified feature.

Design intent:
- Prevent silent scope creep.
- Make implicit modeling assumptions explicit.
- Bind feature semantics to downstream accountability.

---

### Phase 2 — Privacy Risk Modeling

Next, the Control Plane evaluates how risky the feature is *as a representation*, not as a raw event.

It models four structural risk dimensions:

- **Linkability**: how easily the feature can be joined with other datasets.
- **Uniqueness**: how sparse or identifying its realizations are.
- **Inferability**: how much sensitive information becomes predictable from it.
- **Policy Exposure**: how it intersects with regulatory or internal constraints.

These risks are evaluated at multiple candidate granularities and boundaries. The outcome is not a yes/no decision but a **risk surface** over the design space.

Design intent:
- Replace subjective privacy reviews with quantitative structure.
- Enable consistent comparisons across features.
- Provide audit-ready justifications.

---

### Phase 3 — Utility and Heterogeneity Estimation

In parallel, the Control Plane estimates how much modeling value the feature is expected to contribute at each candidate granularity.

This phase does not require a full model retraining loop; it relies on proxies such as:
- historical feature importance,
- expected heterogeneity,
- sparsity and opt-out behavior,
- DP noise amplification effects,
- downstream loss sensitivity.

The key design idea is that **utility is representation-dependent**. A feature that is highly valuable at item level may be almost useless once aggregated.

Design intent:
- Avoid over-protecting features that are already low value.
- Avoid under-protecting features whose signal collapses under noise.
- Make privacy–utility tradeoffs explicit.

---

### Phase 4 — Boundary and Granularity Synthesis

This is the system’s core decision layer.

The Control Plane synthesizes privacy risk, utility intent, and policy constraints into a binding recommendation:

- Which DP boundary must be used?
- At which granularity is this feature allowed to exist?
- Under what fallback or downgrade rules?

This is not an unconstrained optimization. Hard policy constraints (e.g., “never allow item-level under Central DP”) bind first; utility optimization happens within the remaining feasible region.

Design intent:
- Encode trust assumptions explicitly.
- Prevent unsafe representations from ever entering runtime.
- Systematize what is otherwise manual governance.

---

### Phase 5 — Contract Materialization

Finally, the Control Plane compiles all decisions into **machine-enforceable contracts**:

- RFC schemas (what fields are allowed at each interface),
- Transform plans (how to bucketize or map),
- Bounding plans (how to cap sensitivity),
- Granularity plans (k-thresholds and downgrade ladders),
- DP configurations (mechanisms and parameters).

These artifacts are versioned, distributed, and consumed by the runtime plane. Runtime systems do not re-decide privacy; they simply enforce what the Control Plane has declared.

Design intent:
- Eliminate policy drift.
- Make behavior reproducible and auditable.
- Allow privacy changes without rewriting pipelines.

---

## Why This Architecture Matters

The Control Plane turns privacy from an operational afterthought into a **design-time optimization layer**.

It makes three things possible that are not feasible in traditional pipelines:

1. **Adaptive privacy**: different features receive different protections based on structural risk.
2. **Intent-aligned representations**: granularity is chosen for utility, not convenience.
3. **Governance at scale**: policy becomes code, not review tickets.

Most importantly, it enables the system to answer a question that conventional DP pipelines cannot:

> *What is the most informative representation of this feature that is still safe to use under our privacy, fairness, and trust constraints?*

That question is the Control Plane’s entire reason for existing.
---

If you want, next we can write the matching **Runtime Plane** section in the same design-doc style (principles → phases → intent), so the two halves mirror each other conceptually instead of reading like a spec.


- ingests data,
- applies transformations,
- enforces contribution bounds,
- executes Local / Shuffle / Central DP paths,
- produces released tables.

It **never re-decides privacy**.  
It only enforces what the Control Plane has declared.

---




# Design Document: Adaptive Privacy-Aware Data System

## 1. Motivation and Problem Statement

Modern data platforms in fintech, healthcare, and e-commerce rely on user-level behavioral signals to build predictive models. These signals are inherently privacy-sensitive, either directly (e.g., health attributes, financial transactions) or indirectly (e.g., behavioral traces that can be linked or inferred).

The standard approaches used today fall into three categories:

1) **Uniform anonymization**  
   Apply the same de-identification or DP mechanism to all features.

2) **Rule-based sensitivity labeling**  
   Categorize features as “sensitive” vs “non-sensitive” and hard-code handling rules.

3) **Post-hoc DP injection**  
   Add noise at release time without redesigning feature representations.

All three approaches are structurally flawed.

They assume that privacy risk is a property of *fields*.  
In reality, privacy risk is a property of *representations*.

The same underlying signal can be:

- catastrophically unsafe at item level,
- moderately risky at cluster level,
- essentially harmless at aggregate level.

Furthermore, privacy protection mechanisms induce **systematic data degradation**:

- DP noise increases variance,
- clipping introduces bias,
- aggregation collapses heterogeneity,
- opt-out induces missingness bias,
- unlinkability destroys cross-feature joins.

These effects are not uniform across features or granularities.  
Therefore, privacy cannot be treated as a post-processing step.

**Core design objective:**

> Select, for each feature, the representation (granularity + DP boundary) that maximizes predictive utility subject to privacy and fairness constraints.

This is a **structural optimization problem**, not a noise-tuning problem.

---

## 2. Formal Problem Definition

Let:

- \( f \) denote a feature.
- \( g \in \{\text{item}, \text{cluster}, \text{aggregate}\} \) denote representation granularity.
- \( b \in \{\text{local}, \text{shuffle}, \text{central}\} \) denote the privacy boundary.
- \( \mathcal{C}_{\text{policy}} \) denote hard policy constraints (regulatory, governance, trust).

We define three functions:

- \( U(f, g, b) \): expected predictive utility.
- \( R(f, g, b) \): privacy risk.
- \( F(f, g, b) \): fairness risk.

The system solves:

\[
\max_{g, b} \quad U(f, g, b)
\]

subject to:

\[
R(f, g, b) \le \tau_{\text{privacy}}
\]

\[
F(f, g, b) \le \tau_{\text{fairness}}
\]

\[
(g, b) \in \mathcal{C}_{\text{policy}}
\]

This makes explicit that:

- privacy is a *constraint*, not an afterthought,
- granularity and boundary are *decision variables*,
- and utility is representation-dependent.

---

## 3. Why Privacy Is Structurally Important (Not Just Legally)

Privacy matters here for three independent technical reasons.

### 3.1 Linkability is a structural leakage channel

Even without identifiers, high-cardinality, stable, sparse features can be joined with external datasets.

Formally, joinability increases with:

- cardinality of the key space \( K_g \),
- temporal stability \( S(f) \),
- uniqueness \( U(f) \).

No amount of DP noise added *after* linkage can undo a successful join.

Therefore, **representation choice dominates noise magnitude**.

---

### 3.2 Uniqueness is a representation property

Let:

- \( n_c \) = contributor count in cell \( c \).

Then k-anonymity violations occur when:

\[
\mathbb{P}(n_c < k) \text{ is non-negligible}.
\]

Item-level representations massively amplify this probability.  
Cluster-level representations reduce it.  
Aggregate-level representations collapse it.

This cannot be fixed by adding noise alone.

---

### 3.3 Inferability grows with representational richness

Let \( A \) be a sensitive attribute.

If a model \( h(f) \) can predict \( A \) from feature \( f \) with high AUC:

\[
I(f) = \text{AUC}(h(f), A)
\]

then releasing \( f \) increases privacy risk even if it is anonymized.

Again: noise magnitude does not remove structural predictability.

---

## 4. Privacy Risk Model: Local Privacy Score (LPS)

Privacy risk is modeled as a vector:

\[
\text{LPS}(f, g, b) =
\left[
L(f, g, b),\;
U(f, g, b),\;
I(f, g, b),\;
P(f, g, b)
\right]
\]

### 4.1 Linkability Risk \( L \)

Let:

- \( K_g \) = cardinality at granularity \( g \)
- \( J(f) \) = empirical join success rate
- \( S(f) \) = temporal stability
- \( A(b) \) = anonymization strength (Local > Shuffle > Central)

\[
L(f, g, b)
=
\alpha_1 \log K_g
+
\alpha_2 J(f)
+
\alpha_3 S(f)
-
\alpha_4 A(b)
\]

---

### 4.2 Uniqueness Risk \( U \)

Let:

- \( n_c \) = contributors per cell
- \( H_g \) = entropy at granularity \( g \)

\[
U(f, g, b)
=
\mathbb{E}_c [\mathbb{1}(n_c < k)]
+
\beta_1 / H_g
\]

---

### 4.3 Inferability Risk \( I \)

Let:

- \( A \) be a sensitive attribute
- \( h(f) \) be a probing model

\[
I(f, g, b) = \text{AUC}(h(f), A)
\]

---

### 4.4 Policy Exposure \( P \)

\[
P(f, g, b)
=
\sum_{r \in \mathcal{R}}
\lambda_r \cdot \mathbb{1}[(f, g, b) \text{ violates rule } r]
\]

---

## 5. Utility Model Under Privacy-Induced Degradation

Utility is modeled as:

\[
U(f, g, b)
=
\frac{H(f, g)}{\sigma^2(f, g, b) + \text{Bias}(f, g, b) + \epsilon}
\]

where:

- \( H(f, g) \): heterogeneity retained at granularity \( g \)
- \( \sigma^2(f, g, b) \): effective DP noise variance
- \( \text{Bias}(f, g, b) \): clipping + missingness bias

### 5.1 DP Noise Variance

For count queries:

- Central DP:
  \[
  \sigma^2 \approx \frac{2 \log(1.25/\delta)}{\varepsilon^2}
  \]

- Local DP:
  \[
  \sigma^2 \propto \frac{1}{n (e^\varepsilon - 1)^2}
  \]

- Shuffle DP:
  \[
  \sigma^2 \approx \frac{1}{n} \cdot \text{polylog}(n)
  \]

---

### 5.2 Aggregation Effect on Heterogeneity

Let:

- \( H(f, \text{item}) = 1 \)
- \( H(f, \text{cluster}) = \rho < 1 \)
- \( H(f, \text{aggregate}) = 0 \)

This formalizes that aggregation collapses modeling signal.

---

## 6. Boundary and Granularity Optimization

Define feasible set:

\[
\mathcal{F}(f)
=
\{ (g, b) \mid \text{LPS}(f, g, b) \le \boldsymbol{\tau} \}
\]

Optimal representation:
$$ [(g^*, b^*)=\arg\max_{(g, b) \in \mathcal{F}(f)} U(f, g, b)] $$
$$ \[(g^*, b^*)=\arg\max_{(g, b) \in \mathcal{F}(f)} U(f, g, b)\] $$

---

## 7. Granularity Downgrade Ladder

If \( (g, b) \notin \mathcal{F}(f) \):

\[
\text{item} \rightarrow \text{cluster} \rightarrow \text{aggregate}
\]

Stop at first feasible \( g \).

---

## 8. Runtime Enforcement

The Control Plane emits:

- RFC schemas
- TransformPlan
- BoundingPlan
- GranularityPlan
- DPConfig

The runtime plane enforces these deterministically.

---

## 9. Innovations

1) Privacy as structural optimization  
2) Granularity as a first-class variable  
3) Boundary selection as a trust decision  
4) Representation-aware privacy modeling  
5) Automated downgrade instead of suppression

---

## 10. Summary

This system replaces uniform anonymization with adaptive representation selection under formal privacy constraints. It treats privacy as a design-time optimization variable, not a post-hoc filter.

---



