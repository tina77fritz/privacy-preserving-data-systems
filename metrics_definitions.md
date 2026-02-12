# Metrics Definitions (PPDS Evaluation)

This document defines measurable metrics used to evaluate privacy risk, enforcement effectiveness, and system consistency.

## M1: Local Privacy Score (LPS)
**Definition:** Composite risk score computed before admission into downstream pipelines.  
**Range:** [0, 1] (higher indicates higher privacy risk).  
**Interpretation:** Values above threshold require de-identification or rejection.

## M2: Risk Threshold Hit Rate
**Definition:** Fraction of evaluated inputs that exceed configured risk thresholds.  
**Purpose:** Measures how often controls are triggered under real workloads.

## M3: Enforcement Consistency Rate
**Definition:** Percentage of repeated evaluations that produce identical enforcement outcomes.  
**Purpose:** Detects nondeterministic or drift-prone enforcement behavior.

## M4: Audit Completeness
**Definition:** Percentage of enforcement decisions that include required audit fields:
- policy rule id
- applied threshold
- decision outcome
- enforcement reason codes

## M5: Granularity Reduction Ratio
**Definition:** Ratio of applied granularity reduction relative to original signal granularity.  
**Purpose:** Quantifies privacy-utility tradeoff decisions.

## M6: Decision Replay Match Rate
**Definition:** Percentage of replay runs where the system produces identical outputs for identical inputs.  
**Purpose:** Validates reproducibility and independent verification.
