# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning (SemVer).
Release notes prioritize: auditability, deterministic behavior, and integration readiness.

## [Unreleased]
### Added
### Changed
### Fixed
### Security

## [0.1.0] - 2026-02-01
### Added
- Stable `PPDSPlan` output contract (schema v1) including:
  - routing & granularity decisions
  - planner-level constraints
  - structured rejection / decision reasons for audit review
  - deterministic fingerprint for reproducible runs
- CLI commands:
  - `ppds validate` for fail-closed config validation
  - `ppds plan` to generate `plan.json`
  - `ppds emit-sql` to emit SQL-compatible outputs for warehouse integration
- SQL emitter with initial dialect support (e.g., Spark) and parameterized query generation.
- Minimal end-to-end example configs under `examples/` for quickstart usage.
- **Quickstart**: documented an end-to-end evaluation flow (validate → plan → emit SQL) with reproducibility guidance (pinned version + plan fingerprint).
- **Audit-friendly outputs**: documented expectations for structured decision reasons and deterministic fingerprints in `plan.json` (contract-level guidance for integrations).
- **Warehouse integration entrypoint**: documented SQL emission usage and dialect placeholder (intended for scheduled warehouse jobs / offline evaluation).


### Changed
- Repository documentation reorganized under `docs/spec/` and `docs/api/` to separate specifications from usage docs.

### Fixed
- Configuration guardrails to prevent nonsensical scoring due to invalid policy weights or thresholds.

### Security
- Enforced fail-closed behavior: inputs violating policy thresholds are deterministically rejected with audit-visible reasons.

[0.1.0]: https://github.com/tina77fritz/privacy-preserving-data-systems/releases/tag/v0.1.0



## [0.1.1] - 2026-02-7
### Added
- integration demo (configs + scheduled job example)
- end-to-end test validating validate → plan → emit-sql

### Changed
- CI now runs on pull requests (PR checks)


[0.1.1]: [https://github.com/tina77fritz/privacy-preserving-data-systems/releases/tag/v0.1.1](https://github.com/tina77fritz/privacy-preserving-data-systems/releases/tag/v.0.1.1)
