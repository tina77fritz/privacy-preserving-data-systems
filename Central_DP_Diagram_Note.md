# Central DP Runtime: End-to-End Notes (Client + Server)

This note explains the full **Central Differential Privacy (Central DP)** runtime, end-to-end. It combines:
- **Client** as the *event source* (not executing DP),
- **Server ingest + staging** within the trusted boundary,
- **Materialization + release** where **central DP noise** is applied.

**Goal:** Compute aggregate statistics from raw events **inside a server trust boundary**, enforce **contribution bounding**, and add **DP noise only at release** to produce a safe **Released Table**.

---

## Scope and Trust Boundaries

- **Client:** generates events (signals). It does not randomize data for Central DP.
- **Server boundary (trusted):** raw events may exist here briefly, but must be minimized/bounded quickly.
- **Staging:** should contain **pre-aggregated partials**, not raw per-event rows, and must be ephemeral.
- **Released Table:** contains DP-protected aggregates safe for downstream consumers.

---

## Inputs and Contracts (Shared Context)

Central DP requires a versioned contract bundle published by the controller plane.

### 1) RFC (Required Fields Contract)

Defines what fields are allowed/required at each interface:

- **Ingest schema (logging → central DP pipeline):** required/optional fields for raw events
- **Staging schema (pipeline → staging table):** what can be written to staging (should exclude identifiers)
- forbidden fields (e.g., stable identifiers not allowed to persist beyond bounding)

### 2) TransformPlan

Defines canonicalization rules (bucketization/mapping):

- `event_time -> window_id`
- `geo -> geo_bucket`
- `age -> age_bucket`
- `item_id -> cluster_id` (if required)

### 3) BoundingPlan

Defines contribution bounding rules to ensure DP sensitivity assumptions hold:

- per-user-per-cell-per-window caps (e.g., max 1 conversion per day per cell)
- numeric clipping bounds (e.g., revenue clipped to `[0, 500]`)
- deduping rules (optional)

### 4) GranularityPlan (k-threshold + downgrade)

Defines small-cell handling before release:

- `k_min` minimum distinct contributors per cell
- downgrade ladder: `ITEM -> CLUSTER -> AGGREGATE`
- suppression rules (if downgrade not allowed)

### 5) DPConfig(CENTRAL)

Defines central DP release parameters:

- `(epsilon, delta)` or `sigma`
- mechanism type: `Gaussian | Laplace | Discrete`
- metric type: `COUNT | SUM | MEAN | HIST`
- optional: privacy accounting hooks/ledger id

---

# Part A — Client-side (Event Source Only)

## Step A — Raw Signal (Client)

**Definition:** A user-originated observation on device (e.g., impression/click/conversion).

**Important:** In Central DP, the client does **not** add DP noise. Events are sent to the server logging system.

**Output:** Event is emitted to server logging pipeline.

---

# Part B — Server-side Ingest + Canonicalization (Inside Trusted Boundary)

The server-side pipeline consumes raw events and quickly converts them into bounded, canonical contributions.

## Step B1 — Contract Validation (Server Gate 1/3)

**Purpose:** Ensure the pipeline is using an active and correct contract for this feature.

**Checks:**
- `contract_id/version` exists and is **ACTIVE**
- contract boundary is `CENTRAL`
- windowing rules (allowed lateness) are valid

**Fail action:**
- reject partition/stream; log `REJECT_CONTRACT`

**Output on pass:**
- events tagged with correct contract bundle pointer

---

## Step B2 — Schema Validation (Server Gate 2/3)

**Purpose:** Ensure raw event rows match RFC ingest schema.

**Checks:**
- required ingest fields present
- forbidden ingest fields absent (or flagged for immediate drop)
- types valid (timestamp, numeric)

**Fail action:**
- drop offending rows/partitions; log `REJECT_SCHEMA`

**Output on pass:**
- schema-compliant event stream

---

## Step B3 — Dimension + Domain Validation (Server Gate 3/3)

**Purpose:** Prevent cardinality explosions and ensure dims can be bucketized safely.

**Checks:**
- enums in allowed sets (e.g., event_type)
- ids match expected patterns (e.g., item_id formatting)
- values needed for bucketization are present (or map to `UNKNOWN` if contract allows)

**Fail action:**
- drop or map to `UNKNOWN` per contract; log `REJECT_DIM` / `REJECT_DOMAIN`

**Output on pass:**
- validated dims ready for TransformPlan

---

## Step B4 — Bucketization (TransformPlan on Server)

**Purpose:** Convert raw attributes into canonical, policy-safe representations.

**Transform examples:**
- `event_time -> window_id` (day/hour granularity)
- `geo -> geo_bucket` (country/state/DMA)
- `age -> age_bucket` (coarse age ranges)
- `item_id -> cluster_id` (if required by contract)

**Output:**
- canonicalized event rows: `(window_id, cell_key, metric_value, contributor_key_ephemeral)`

**Note:** If you need an identity for bounding (e.g., per-user caps), compute it ephemerally here (e.g., hashed user token) and do not persist it beyond Step B5.

---

## Step B5 — Contribution Bounding (BoundingPlan)

**Purpose:** Enforce DP sensitivity assumptions by limiting any single contributor’s impact.

**Typical actions:**
- **Cap** contributions per `(contributor, window_id, cell_key)`  
  e.g., at most 1 conversion per day per cell
- **Clip** numeric values into a bounded range  
  e.g., revenue clipped to `[0, 500]`
- **Dedupe** events if specified  
  e.g., unique by `event_id`

**Fail/edge handling:**
- over-cap contributions are truncated (not dropped entirely unless contract says so)
- invalid numeric values are clipped or dropped per contract

**Output:**
- bounded contributions suitable for safe aggregation
- contributor identity is dropped immediately after capping

---

## Step B6 — Pre-aggregation to Staging (RFC Staging Schema)

**Purpose:** Minimize leakage surface by writing **aggregated partials** to staging instead of raw events.

**Aggregation keys:**
- `(contract_id, contract_version, window_id, cell_key)`

**Typical staging metrics:**
- `count` (e.g., number of events)
- `sum` (e.g., sum of clipped values)
- `contributors_count` (distinct contributor count; required for k-threshold)
- optional: `sum_squares` (variance/CI support)

**Output:**
- `[Staging Table]` (ephemeral, strict ACL, TTL)

---

## Staging Table Schema (SQL-like)

```sql
-- dp_staging_central_<feature_id>_<contract_version>
contract_id        STRING
contract_version   STRING
feature_id         STRING
window_id          STRING

-- bucketed dimensions (cell_key)
geo_bucket         STRING
cluster_id         STRING
age_bucket         STRING

-- partial aggregates
event_count        BIGINT
value_sum          DOUBLE
contributors_count BIGINT

-- optional uncertainty support
value_sumsq        DOUBLE

-- provenance
staging_ts_ms      BIGINT
```

**Notes:**
- Do **not** store stable identifiers in staging.
- Use TTL aligned to materialization cadence (hours/days, not weeks).
- Treat staging as “raw within boundary” from an access-control perspective.

---

# Part C — Materialization + Release (k-threshold → DP Noise → Released Table)

This job reads staging and produces the final DP-protected release.

## Step C1 — Materialization Contract Validation

**Purpose:** Ensure the release job is using an active contract and matching schema version.

**Checks:**
- contract still active
- staging schema version matches RFC

**Fail action:**
- fail job; log `REJECT_CONTRACT`

**Output on pass:**
- validated staging partitions

---

## Step C2 — Staging Schema + Partition Validation

**Purpose:** Ensure staging is well-formed and contains no forbidden columns.

**Checks:**
- required columns present and types correct
- partition keys present (window_id, cell_key)
- forbidden columns absent (identity leak guard)

**Fail action:**
- fail job; log `REJECT_SCHEMA`

**Output on pass:**
- staging rows ready for k-threshold gating

---

## Step C3 — Small-cell Gate: k-threshold + Downgrade (GranularityPlan)

**Purpose:** Prevent small-cell exposure and avoid high-variance releases.

**Rule:**
- if `contributors_count >= k_min`: keep preferred granularity
- else apply downgrade ladder:
  - `ITEM -> CLUSTER -> AGGREGATE`, or
  - suppress if downgrade not permitted

**Output:**
- gated (and possibly downgraded) per-cell aggregates eligible for release

---

## Step C4 — Add Central DP Noise at Release (DPConfig)

**Purpose:** Enforce the formal central DP guarantee.

**Mechanism examples:**
- **COUNT:** add noise to `event_count`
- **SUM:** add noise to `value_sum` (bounded sensitivity)
- **MEAN:** noise sum (and optionally count), then compute mean
- **HIST:** add noise per bin, post-process to non-negative counts

**Post-processing (recommended):**
- enforce non-negative counts
- clamp outputs into valid ranges if required by spec

**Output:**
- DP-protected aggregates with provenance metadata

---

## Step C5 — Released Table (Output)

**Definition:** Final DP-protected table safe for downstream use.

### Released Table Schema (SQL-like)

```sql
-- dp_release_central_<feature_id>_<contract_version>
contract_id        STRING
contract_version   STRING
feature_id         STRING
window_id          STRING

-- bucketed dimensions (cell_key)
geo_bucket         STRING
cluster_id         STRING
age_bucket         STRING

-- DP-protected outputs
dp_event_count     DOUBLE
dp_value_sum       DOUBLE
dp_value_mean      DOUBLE

-- optional uncertainty
variance           DOUBLE
ci_lower           DOUBLE
ci_upper           DOUBLE

-- provenance
mechanism_type     STRING
epsilon            DOUBLE
delta              DOUBLE
release_ts_ms      BIGINT
```

**Notes:**
- Only bucketed dims and DP-protected aggregates are released.
- The exact output columns depend on the metric type(s) declared in the contract.

---

## End-to-End Summary (One Line)

**Client:** emits raw events →  
**Server (trusted):** validate → bucketize → bound contributions → pre-aggregate to staging →  
**Release job:** validate staging → k-threshold + downgrade → add DP noise → write released table
