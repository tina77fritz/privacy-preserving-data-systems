# Evaluation Checklist (PPDS)

This checklist defines required validation steps for confirming privacy enforcement correctness.

## A. Scoring Validation
- [ ] Confirm LPS is computed for all evaluated features.
- [ ] Confirm scoring components are present and within expected range.
- [ ] Confirm risk thresholds match policy configuration.

## B. Enforcement Decision Validation
- [ ] Confirm allow/reject/de-identify decisions match configured rules.
- [ ] Confirm enforcement is fail-closed when required fields are missing.
- [ ] Confirm no raw identifiers are emitted in enforcement outputs.

## C. Audit Record Validation
- [ ] Confirm each decision includes a policy rule identifier.
- [ ] Confirm each decision includes enforcement reason codes.
- [ ] Confirm audit records contain no raw user-level data.

## D. Reproducibility Checks
- [ ] Run the same input twice and confirm identical decision output.
- [ ] Confirm fingerprint/hash matches across repeated runs.

## E. Acceptance Criteria
PASS if all checklist items are satisfied.
FAIL if any enforcement decision lacks audit justification or violates configured thresholds.
