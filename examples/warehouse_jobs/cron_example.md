# PPDS Integration Demo — Scheduled Warehouse Job

This demo shows an integration path that produces:
1) an auditable planning artifact (`plan.json`)
2) a warehouse-friendly SQL output (`query.sql`)

## Inputs
- Policy: `examples/configs/policy_min.json`
- Feature spec: `examples/configs/features_min.json`

## Run locally
```bash
ppds validate \
  --policy examples/configs/policy_min.json \
  --features examples/configs/features_min.json

ppds plan \
  --policy examples/configs/policy_min.json \
  --features examples/configs/features_min.json \
  --out /tmp/plan.json

ppds emit-sql \
  --plan /tmp/plan.json \
  --dialect spark \
  --out /tmp/query.sql
