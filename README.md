# Privacy Preserving Data Systems
System-level design frameworks for privacy-preserving data processing that enable lawful data use and analytical utility while minimizing reliance on identifiable personal information.

## Context & Goal
Data-driven services increasingly underpin essential sectors such as healthcare, online commerce, communications, and financial technology. Because these systems rely on large-scale data to deliver functionality and reliability, they routinely collect and use extensive personal information. This creates material privacy risks: breaches and unauthorized disclosure can enable identity theft and fraud, expose sensitive attributes and location patterns, and erode public trust in essential digital services, while also increasing compliance and operational risk as privacy and data security requirements continue to evolve.

While governments have enacted strong privacy regulations to protect the public’s rights, legal and policy controls alone are often reactive and can lag behind the pace and complexity of modern data practices. As a result, effective privacy protection cannot depend solely on post hoc compliance processes. It must be operationalized as an engineering constraint—embedded directly into system design—so that data can be used lawfully and responsibly while minimizing exposure of identifiable information by default.

Privacy-preserving systems provide this technical capability. By shifting from individual-level data dependence to aggregated and privacy-protected signals, enforcing risk-based constraints on how data is processed and shared, and enabling consistent, auditable controls that scale across high-volume pipelines, these systems reduce systemic privacy risk while maintaining the utility and reliability of data-driven services.



## Purpose of This Repository
This repository focuses on that systems perspective—how to implement privacy protection as a built-in, decision-driven capability that supports both trustworthy data use and the continued stability of data-driven infrastructure.Rather than focusing on algorithmic optimization alone, this repository describes system-level decision logic for determining how and at what granularity data may be processed or released in a privacy-aware manner.

## Repository Structure

This repository is organized as a **layered system specification**, where each document
builds on the previous one and introduces a strictly scoped responsibility.

- [00 Overview](docs/00_overview.md)  
  High-level architecture, design principles, and system goals.

- [01 Problem Statement](docs/01_problem_statement.md)  
  Formalizes the problem of privacy-induced data degradation and motivates
  structure-aware data usage.

- [02 Threat Model & Trust Boundaries](docs/02_threat_model_trust_boundaries.md)  
  Defines protected assets, adversary capabilities, trust boundaries (Local / Shuffle / Central),
  and **formally maps threat classes to measurable privacy risk dimensions (LPS sub-scores)**.
  This document grounds all privacy reasoning in an explicit threat model.

- [06 LPS Scoring Specification](docs/06_lps_scoring_spec.md)  
  Defines the Local DP Privacy Score (LPS), including linkability, uniqueness,
  inferability, and policy penalty, as quantitative proxies derived from the threat model.

- [07 Granularity Selection Specification](docs/07_granularity_selection_spec.md)  
  Specifies how data granularity (Item / Cluster / Aggregate) is selected by
  optimizing utility within the privacy-feasible region defined by LPS.

- [08 Routing Execution Specification](docs/08_routing_execution_spec.md)  
  Defines runtime enforcement of routing decisions and guarantees that no
  privacy decisions are made during signal ingestion.

- [09 Data Lineage & Trust Boundary Enforcement](docs/09_data_lineage_and_trust_boundary.md)  
  Formalizes how data flows across trust boundaries and enforces boundary invariants.

- [10 Re-evaluation & Lifecycle Management](docs/10_re_evaluation_and_lifecycle_spec.md)  
  Defines feature lifecycle states, re-evaluation triggers, downgrade rules,
  and governance controls to ensure stability and auditability.

---

### Reading Guide

- **Security / Privacy reviewers** should start with `02 → 06 → 09`.
- **Infra / Data platform engineers** should focus on `07 → 08 → 10`.
- **Research / ML readers** should read `01 → 06 → 07` for the core method.

Together, these documents specify a complete **privacy-aware data usage framework**
that is threat-grounded, structurally enforced, and auditable by design.


## Quickstart

> **Goal:** In ~3 minutes, validate a policy, generate an auditable PPDS plan, and emit SQL-compatible outputs for warehouse integration.

### Prerequisites
- Python **3.10+**
- `pip` (recommended: run inside a virtualenv)

### Install

**Option A — Install a pinned release (recommended for reproducibility)**

```bash
pip install "ppds @ git+https://github.com/tina77fritz/privacy-preserving-data-systems@v0.1.0"
```
**Option B — Install latest from `main` (for development)**

```bash
pip install "ppds @ git+https://github.com/tina77fritz/privacy-preserving-data-systems@main"
```

Verify:
```bash
ppds --version
```

1) Validate configuration (fail-closed)

Validate your policy + feature specifications. Invalid configs must hard-fail with structured reasons (non-zero exit code).

```bash
ppds validate \
  --policy examples/configs/policy_min.yaml \
  --features examples/configs/features_min.yaml \
  --format json
```

**Expected behavior**
- ✅ Exit code `0` if valid
- ❌ Non-zero exit code + JSON error payload if invalid (e.g., weights don’t sum to 1, thresholds out of range, missing required fields)

---

### 2) Generate an auditable plan (`plan.json`)

Generate a deterministic and auditable plan that captures decisions, constraints, and reasons.

```bash
ppds plan \
  --policy examples/configs/policy_min.yaml \
  --features examples/configs/features_min.yaml \
  --out plan.json
```

`plan.json` is designed to be:

- **Auditable:** includes structured reasons (scores, thresholds, rule hits)
- **Deterministic:** includes a fingerprint for reproducible runs
- **Integration-ready:** includes planner/warehouse friendly constraints

**Example (illustrative):**

```json
{
  "schema_version": 1,
  "fingerprint": "sha256:…",
  "decision": {
    "route": "local_only",
    "granularity": "coarse"
  },
  "constraints": [
    {
      "type": "deny_join",
      "key": "user_id"
    }
  ],
  "reasons": {
    "lps": {
      "total": 0.83,
      "components": {
        "linkability": 0.25,
        "uniqueness": 0.30,
        "inferability": 0.28
      },
      "thresholds_hit": ["stable_join_key", "high_sparsity"]
    },
    "policy": {
      "fail_closed": true,
      "rejection_reasons": []
    }
  }
}
```

## 3) Emit SQL-compatible outputs

Translate a plan into SQL snippets for warehouse integration.

```bash
ppds emit-sql \
  --plan plan.json \
  --dialect spark \
  --out query.sql
```

## 4) Explain (optional): human-readable audit report

```bash
ppds explain --plan plan.json --format md > audit_report.md
```

This produces a reviewer-friendly report summarizing:

- Why a feature was routed / rejected
- Which thresholds were hit
- How LPS components contributed to the final decision

## Reproducibility / Citation

To reproduce planning behavior in technical evaluations, always reference:

1. the release tag (e.g., v0.1.0) and
2. the generated plan's fingerprint

**Example:**
```bash
python -c "import ppds; print(ppds.__version__)"
ppds plan --policy policy.yaml --features features.yaml --out plan.json
jq -r .fingerprint plan.json
```
### How to cite this release

If you use PPDS for technical evaluation, prototyping, or integration experiments, please cite the exact release tag to ensure reproducibility:

- **Repository:** `privacy-preserving-data-systems`
- **Release tag:** `v0.1.0`
- **URL:** https://github.com/tina77fritz/privacy-preserving-data-systems/releases/tag/v0.1.0

For best reproducibility, also record the plan fingerprint produced by:

```bash
ppds plan --policy policy.yaml --features features.yaml --out plan.json
jq -r .fingerprint plan.json
