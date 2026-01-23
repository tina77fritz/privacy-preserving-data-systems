# Shuffle DP Notes 

This note explains the **full Shuffle Differential Privacy (Shuffle DP) runtime**,combining **client-side** message generation, **shuffler-side** mixing, and **server-side** validation/aggregation/estimation into a single, coherent narrative.

> **Goal:** Convert raw user signals into a **DP-protected released table** by (1) enforcing caps and canonicalization at the client, (2) using a **shuffler** to break sender–message linkage (privacy amplification), and (3) aggregating + estimating on the server (optionally with a small central-noise release step).

---

## Inputs from Control Plane

Shuffle DP requires a **versioned contract bundle** published by the Controller plane:

### 1) RFC (Required Fields Contract)
Defines what fields are allowed/required at each interface:
- **Ingest schema (client → shuffler)**: required/optional fields in the shufflable message
- Forbidden fields (e.g., stable identifiers; raw high-cardinality fields if not allowed)
- **Server-side schema** expectations for messages arriving from the shuffler

### 2) TransformPlan
Defines canonicalization rules (bucketization/mapping):
- `event_time -> window_id`
- `geo -> geo_bucket`
- `age -> age_bucket`
- `item_id -> cluster_id` (if required)

### 3) DPConfig(SHUFFLE)
Defines the shuffle protocol and estimators:
- `protocol_type`: e.g., `SHUFFLE_COUNT`, `SHUFFLE_HIST`, `SHUFFLE_SKETCH`
- whether **optional light local randomization** is enabled:
  - `local_randomization_enabled: true/false`
  - `epsilon_local` and mechanism parameters if enabled
- contribution caps and sampling rules
- server-side estimator spec
- optional central-release noise parameters (if configured)

---

# Part A — Client-side (Raw Signal → Shufflable Message)

## Step A — Raw Signal
**Definition:** A raw user-originated observation on the device before privacy protections.

Examples:
- `clicked = 1` (binary)
- `category = "sports"` (categorical)
- `conversion = 1` (count contribution)

Output: in-memory raw value(s).

---

## Step B — Schema Check (Client Gate)
**Definition:** Verify the client can construct a message that conforms to the RFC for Shuffle DP.

Checks:
- required fields present/derivable (e.g., `window_id`, required dims)
- missing dims follow contract fallback behavior (e.g., `UNKNOWN`) if allowed
- types and encodings are valid

Fail action: **Skip** (no message emitted).

Output: `MessageCandidate`.

---

## Step C — Policy Check (Client Gate)
**Definition:** Verify the feature is allowed to run in the current policy context.

Checks:
- feature enabled for `policy_profile` / region / purpose
- contract version active (not deprecated)
- optional: user consent gate if part of your system

Fail action: **Skip**.

Output: `PolicyEligibleCandidate`.

---

## Step D — Sampling Check (Client Gate)
**Definition:** Enforce sampling probability and frequency caps at the source.

Checks:
- sampling decision (`p_sample`)
- max messages per `(feature_id, window_id)` per device
- max contributions per `(feature_id, window_id, cell_key)` per device

Fail action: **Skip**.

Output: `SelectedCandidate`.

---

## Step E — Process: Bucketization + Encoding (Client Process)

### E1) Bucketization (TransformPlan)
Convert raw attributes into policy-safe buckets/domains:
- `event_time -> window_id`
- `geo -> geo_bucket`
- `age -> age_bucket`
- `item_id -> cluster_id` (if required)

Output: canonical `cell_key` + canonical value domain.

### E2) Encoding (Protocol-specific)
Convert canonical contributions into an encoded representation expected by Shuffle DP protocol.

Examples:
- count contribution: `+1` (bounded integer)
- categorical: category id in `[0..K-1]` (or encoded vector, protocol dependent)
- sketch update: `(row, col, val)` tuple(s)

Output: `EncodedPayload`.

---

## Step F — Optional: Encode + Add Randomize (ε_local) Noise (Client)
**Definition:** If enabled by DPConfig(SHUFFLE), apply **light local randomization** before shuffling.

Why it may be enabled:
- reduces harm if shuffler compromised
- strengthens guarantees in some threat models
- can reduce per-message sensitivity

Why it may be disabled:
- rely primarily on shuffle unlinkability + caps for utility
- avoid extra noise when not needed

Output: `ShufflablePayload` (raw-but-bounded or lightly randomized).

---

## Step G — Shufflable Message (Client Output)
**Definition:** A message ready for shuffling.

Key properties:
- contains **no stable identifier** (no `user_id`, no `device_id`)
- contains only contract-approved, bucketized dims
- contains an encoded payload (possibly lightly randomized)

---

## Shufflable Message Schema (Wire Format: JSON)

```json
{
  "contract_id": "string",
  "contract_version": "string",
  "feature_id": "string",
  "window_id": "string",
  "cell_key": {
    "geo_bucket": "string",
    "cluster_id": "string",
    "age_bucket": "string"
  },
  "protocol_type": "SHUFFLE_COUNT | SHUFFLE_HIST | SHUFFLE_SKETCH",
  "local_randomization_enabled": "boolean",
  "epsilon_local": "number",
  "payload": {
    "format": "bounded_increment | category | vector | sketch",
    "data": "protocol-specific"
  },
  "metadata": {
    "client_ts_ms": "integer",
    "sample_rate": "number"
  }
}
```
## Notes

- `epsilon_local` may be omitted if local randomization is disabled.
- Do **not** include stable identifiers; the shuffler’s job is unlinkability, not identity.
# Part B — Shuffler-side (Ingress Validation → Shuffle/Mix → Forward)

The shuffler is an intermediate service designed to **break sender–message linkage** by batching and permuting messages and stripping linkable transport metadata.


## Step H — Shuffler Validation (3 checks)

**Definition:** Ensure incoming shufflable messages are contract-compliant and safe to mix.

### H1) Contract Validation (fail-fast)

**Checks:**
- `contract_id/version` exists and is active for Shuffle DP
- `window_id` format valid; lateness within threshold

**Reject action:**
- Drop message; log `REJECT_CONTRACT`

### H2) Schema + Dimension Validation (RFC-driven)

**Checks:**
- required fields present; forbidden fields absent
- types valid
- dims valid per catalogs (bucket sets / patterns)
- message size limits

**Reject action:**
- Drop message; log `REJECT_SCHEMA` / `REJECT_DIM`

### H3) Payload Validation (protocol-driven)

**Checks depend on `protocol_type`:**
- bounded increment: integer within `[0..cap]` (or `{-1,0,1}` if applicable)
- categorical/vector: expected length/range
- sketch: indices within `[0..W-1]`, `[0..D-1]`, updates within max

**Reject action:**
- Drop message; log `REJECT_PAYLOAD_*`

**Output:**
- `AcceptedMessages` stream

---

## Step I — Shuffle/Mix

**Definition:** Batch, permute, and de-link messages from senders.

**Actions:**
- collect messages into batches (target batch size / time window)
- apply random permutation (shuffle)
- strip/normalize transport metadata that enables linkage (as feasible)

**Output:**
- `ShuffledBatch` forwarded to server

# Part C — Server-side (Validate → Aggregation → Estimation → Optional Central Noise → Release)

## Step S1 — Server Message Validation (3 checks)

**Definition:** Defense-in-depth validation of messages arriving from the shuffler.

### S1.1) Contract Validation

**Checks:**
- contract exists and is active
- contract version is allowed for this rollout set
- `window_id` format valid; lateness within threshold

**Reject action:**
- Drop message; log `REJECT_CONTRACT`

### S1.2) Schema + Dimension Validation

**Checks:**
- required fields present; forbidden fields absent (per RFC)
- types valid
- dims valid per catalogs (bucket sets / patterns)

**Reject action:**
- Drop message; log `REJECT_SCHEMA` / `REJECT_DIM`

### S1.3) Payload Validation

**Checks:**
- validate payload shape/range using `DPConfig(SHUFFLE).protocol_type`
- apply the same validation rules as the shuffler (do not trust upstream completely)

**Reject action:**
- Drop message; log `REJECT_PAYLOAD_*`

**Output:**
- `ValidatedShuffledMessages` stream (the only input to aggregation)

---

## Step S2 — Aggregation

**Definition:** Aggregate validated shuffled messages per analysis cell.

**Group by:**
- `(contract_id, contract_version, window_id, cell_key)`

**Compute:**
- `n = count(messages)`
- `Y = sum(payload)` (or vector/sketch sums depending on protocol)

**Output:**
- `AggregatedStats`

---

## Step S3 — Estimation / Decoding (If Needed)

**Definition:** Convert aggregated randomized stats into estimates of the true underlying metric.

**If `local_randomization_enabled = true`:**
- apply an unbias / decoding estimator consistent with `epsilon_local` and `protocol_type`

**If `local_randomization_enabled = false`:**
- estimator may be identity (protocol-dependent)
- privacy relies primarily on shuffle unlinkability + caps

**Output:**
- `EstimatedStats` per cell
- optionally: `variance`, `ci_lower`, `ci_upper`

---

## Step S4 — Optional Central Noise (Release Hardening)

**Definition:** If configured, add a small amount of central DP noise at release time.

**Why:**
- handle small cells more safely
- strengthen guarantees under conservative threat models
- simplify downstream release constraints

**Output:**
- `DPHardenedStats`

---

## Step S5 — Released Table (Output)

### Released Table Schema (SQL-like)

```sql
-- dp_release_shuffle_<feature_id>_<contract_version>
contract_id       STRING
contract_version  STRING
feature_id        STRING
window_id         STRING

-- bucketed dimensions (cell_key)
geo_bucket        STRING
cluster_id        STRING
age_bucket        STRING

-- estimated metric
estimate_value    DOUBLE

-- optional uncertainty
variance          DOUBLE
ci_lower          DOUBLE
ci_upper          DOUBLE

-- provenance
protocol_type     STRING
local_randomization_enabled BOOLEAN
epsilon_local     DOUBLE
sample_rate       DOUBLE
release_ts_ms     BIGINT
```
## Notes

- dims are bucketed per contract
- output is safe for downstream consumption under your governance model
