# Data Lineage and Trust Boundary Specification 

**Scope:** Formal specification of data lineage, trust boundaries, and
privacy invariants across Local, Shuffle, and Central environments.

---

## 1. Purpose

This part specifies **where data originates, how it flows, and which
trust boundary it is allowed to cross** under the privacy-aware routing
framework.

The goals are to:

- make privacy guarantees auditable end-to-end,
- prevent implicit or accidental trust-boundary escalation,
- clearly separate *data usage structure* from *privacy mechanisms*,
- provide invariants that can be enforced by infrastructure.

This document answers a single question:

> **Which data, at what granularity, may exist in which trust domain?**

---

## 2. Trust Boundaries

The system defines **three explicit trust boundaries**.

### 2.1 Local Boundary

**Definition**

- User device or edge-controlled execution environment.
- No server-side trust assumed.

**Properties**

- Raw or high-resolution user signals may exist.
- Local DP mechanisms may be applied.
- No cross-user joins.
- No persistent storage beyond local constraints.

**Allowed operations**

- Clipping, bucketization
- Local randomization (Local DP)
- Temporary aggregation

---

### 2.2 Shuffle Boundary

**Definition**

- Untrusted-but-anonymized aggregation layer.
- Signals are mixed across users before analysis.

**Properties**

- User identifiers removed or replaced.
- Signals are unlinkable across time windows.
- Shuffle DP guarantees apply.

**Allowed operations**

- Stateless aggregation
- Count / sum / histogram
- Short-window materialization

**Disallowed**

- Persistent per-user state
- Longitudinal joins

---

### 2.3 Central Boundary

**Definition**

- Trusted analytics and storage environment.
- Strong access controls and auditability.

**Properties**

- Only privacy-approved data may enter.
- Central DP mechanisms apply.
- Joins and long-term storage allowed only under policy.

**Allowed operations**

- Aggregation at approved granularity
- Versioned materialization
- Downstream analytics and modeling

---

## 3. Boundary Invariants

The following invariants **must never be violated**.

### Invariant 1: No Implicit Boundary Escalation

Data may not cross from a lower-trust boundary to a higher-trust boundary
without an explicit routing contract.

```text
Local -> Shuffle -> Central
```

Reverse flow is prohibited.

---

### Invariant 2: Granularity Monotonicity

Granularity may only become **coarser** across boundaries.

```text
ITEM -> CLUSTER -> AGGREGATE
```

Finer-grained data may not be reconstructed downstream.

---

### Invariant 3: Join Safety

No join operation may occur unless:

- explicitly permitted by the routing contract, and
- executed entirely within an approved boundary.

---

### Invariant 4: Retention Alignment

Retention duration must **not increase** when crossing boundaries.

```text
retention(Local) >= retention(Shuffle) >= retention(Central)
```

---

## 4. Feature-Level Data Lineage

Each feature is associated with an explicit lineage path.

### 4.1 Lineage Record Schema

```text
FeatureLineage {
  feature_id
  source_boundary        // Local | Shuffle | Central
  materialization_boundary
  selected_granularity
  allowed_joins
  retention_policy
  contract_version
}
```

This record is immutable per contract version.

---

### 4.2 Example Lineage

```text
Feature: CTR_click_rate

Local:
  - raw impressions and clicks
  - bucketized
  - no persistence

Shuffle:
  - per-session counts
  - window = 1 hour
  - no identifiers

Central:
  - CLUSTER-level CTR
  - DP noise applied
  - retention = 30 days
```

---

## 5. Interaction with LPS and Granularity Selection

### 5.1 LPS as Boundary Feasibility Gate

LPS determines:

- whether a feature may cross into Central,
- the minimum allowed granularity,
- whether Shuffle is required.

Formally:

```text
Ω(f) defines admissible (boundary, granularity) pairs
```

---

### 5.2 Granularity Selection as Boundary-Constrained Optimization

Granularity selection operates **only within the admissible boundary set**.

```text
(boundary, g)* = argmax Utility(f, boundary, g)
subject to (boundary, g) ∈ Ω(f)
```

---

## 6. Enforcement Points

Boundary enforcement occurs at **infrastructure choke points**.

### 6.1 Ingestion Gate

- verifies routing contract
- validates boundary compatibility
- rejects unauthorized writes

### 6.2 Query Planner

- blocks joins violating boundary or granularity constraints
- enforces read-side policy

### 6.3 Materialization Jobs

- apply DP mechanisms
- ensure correct aggregation keys
- emit lineage metadata

---

## 7. Audit and Traceability

Every materialized dataset must be traceable to:

- originating boundary
- routing contract version
- DP mechanism and parameters
- aggregation granularity

### 7.1 Required Audit Artifacts

- routing contracts
- lineage records
- execution logs
- downgrade / rejection logs

---

## 8. Failure Modes and Safeguards

### 8.1 Missing Lineage

- fail closed
- block materialization
- alert controller

### 8.2 Boundary Mismatch

- reject operation
- emit security event

### 8.3 Emergency Downgrade

- allowed only toward coarser granularity
- must remain within same or lower boundary
- logged and reviewed

---

## 9. Summary

This specification formalizes **where data is allowed to exist** and
**how it may flow across trust boundaries**.

By explicitly encoding lineage and boundary invariants, the system ensures:

- privacy guarantees are structural, not heuristic,
- trust assumptions are explicit and auditable,
- routing decisions remain enforceable at scale.

This document closes the loop between **privacy scoring**, **granularity
selection**, and **runtime execution**.


