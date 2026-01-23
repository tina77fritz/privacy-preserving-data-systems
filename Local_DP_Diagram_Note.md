# LOCAL DP Note

This section is an instraction note to define each step in the Local DP client-side path shown in the diagram. The goal is to make the runtime behavior deterministic and easy to implement and review.

---

## Inputs from Control Plane

Local DP requires a **versioned contract bundle** published by the Controller plane:

### 1) RFC (Required Fields Contract)
Defines what fields are allowed/required at each interface:
- **Ingest schema (client → server)**: required/optional fields in the randomized report
- Forbidden fields (e.g., no stable identifiers)

### 2) Bucketization Plan
Defines canonicalization rules (bucketization/mapping),such as: 
- `event_time -> window_id`
- `geo -> geo_bucket`
- `age -> age_bucket`
- `item_id -> cluster_id` (if required)

### 3) DPConfig(LOCAL)
Defines the privacy mechanism and estimator:
- `mechanism_type`: `RR_BINARY | UE_K | HR_K | SKETCH_WxD`
- privacy params: `epsilon` (and mechanism parameters: `K`, `W`, `D`, `p/q`, etc.)
- sampling/caps: report rate, frequency limits, per-window caps
- estimator spec (how server decodes/unbiases)

---

# Part A — Client-side (Raw Signal → Randomized Report)

## Step A — Raw Signal(Feature Inputs)
**Definition:** Raw inputs on the device before privacy protection.

Examples:
- `clicked = 1` (binary)
- `category = "sports"` (categorical)
- `time_to_convert = 37` (numeric)

Output: an in-memory raw value.

---

## Step B — Schema Check (Client Gate)
**Definition:** Verify the client can construct a report that conforms to the RFC.

Checks:
- required fields are present/derivable (e.g., `window_id`, required dims)
- types are correct (timestamp parseable, numeric values valid)
- missing dims follow contract fallback behavior (e.g., `UNKNOWN`) if allowed

Fail action: **Error** (no report emitted).

Output: `ReportCandidate` (still may include raw values).

---

## Step C — Policy Check (Client Gate)
**Definition:** Verify the feature is allowed to run in the current policy context.

Checks:
- feature enabled for `policy_profile` / region / purpose
- contract version active (not deprecated)
- optional: user consent gate if part of your system

Fail action: **Error**.

Output: `PolicyEligibleCandidate`.

---

## Step D — Sampling Check (Client Gate)
**Definition:** Enforce reporting probability and frequency caps at the source.

Checks:
- sampling decision (`p_sample`)
- max reports per `(feature_id, window_id)` per device
- max reports per `(feature_id, window_id, cell_key)` per device

Fail action: **Error**.

Output: `SelectedCandidate` eligible to emit a single report instance.

---

## Step E — Process: Bucketization + Encoding (Client Process)
This step standardizes the data and prepares it for randomization.

### E1) Bucketization (TransformPlan)
Convert raw attributes into policy-safe buckets/domains:
- `event_time -> window_id`
- `geo -> geo_bucket`
- `age -> age_bucket`
- `item_id -> cluster_id` (if required)

Output: canonical `cell_key` + canonical value domain.

### E2) Encoding (Mechanism-specific)
Convert canonical value into an encoded representation:
- RR: `x ∈ {0,1}`
- UE/HR: vector/code for domain size `K`
- SKETCH: `(row, col, value)` updates

Output: `EncodedPayload`.

---

## Step F — Randomized Report (Client Output)
**Definition:** A report containing only allowed fields and a randomized payload.

Creation:
- `RandomizedPayload = randomize(EncodedPayload, epsilon)`

Output: `RandomizedReport` sent to the server.

---

## Randomized Report Schema (Wire Format: JSON)

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
  "mechanism_type": "RR_BINARY | UE_K | HR_K | SKETCH_WxD",
  "payload": {
    "format": "bit | vector | sketch",
    "data": "mechanism-specific"
  },
  "metadata": {
    "client_ts_ms": "integer",
    "sample_rate": "number"
  }
}
