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
