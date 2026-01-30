CREATE TABLE IF NOT EXISTS privacy_budget_ledger (
  feature_id        VARCHAR(255) NOT NULL,
  contract_version  VARCHAR(64)  NOT NULL,
  boundary          VARCHAR(16)  NOT NULL,
  granularity       VARCHAR(16)  NOT NULL,
  privacy_unit      VARCHAR(32)  NOT NULL,
  window_day        DATE         NOT NULL,
  accountant        VARCHAR(16)  NOT NULL DEFAULT 'BASIC',
  epsilon_spend     DOUBLE       NOT NULL,
  delta_spend       DOUBLE       NOT NULL DEFAULT 0.0,
  status            VARCHAR(16)  NOT NULL DEFAULT 'COMMITTED',
  created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(feature_id, contract_version, window_day)
);

-- Helpful index for rolling window queries
CREATE INDEX IF NOT EXISTS idx_privacy_budget_ledger_day
ON privacy_budget_ledger(feature_id, window_day);
