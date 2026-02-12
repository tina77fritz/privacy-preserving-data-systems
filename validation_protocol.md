# Validation Protocol (PPDS)

This protocol enables independent reviewers to verify PPDS enforcement behavior.

## Step 1: Prepare Inputs
- Provide a sample feature set file (features.json)
- Provide a policy configuration file (policy.yaml)

## Step 2: Execute Planning
Run:
ppds plan --policy policy.yaml --features features.json --out plan.json

## Step 3: Verify Outputs
Confirm plan.json includes:
- enforcement outcome
- triggered policy rule ids
- thresholds applied
- reason codes
- fingerprint/hash

## Step 4: Replay Verification
Run the same command again with identical inputs.
Confirm:
- plan.json enforcement outcome is identical
- fingerprint/hash matches

## Step 5: Acceptance Criteria
PASS if:
- enforcement decisions match configured thresholds
- audit fields are complete
- replay results are identical

FAIL if:
- enforcement output is nondeterministic
- required audit fields are missing
- raw identifiers appear in audit outputs
