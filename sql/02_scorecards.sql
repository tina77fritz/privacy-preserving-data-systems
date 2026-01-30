CREATE TABLE IF NOT EXISTS lps_scorecards (
  feature_id        VARCHAR(255) NOT NULL,
  contract_version  VARCHAR(64)  NOT NULL,
  granularity       VARCHAR(16)  NOT NULL,
  L                DOUBLE       NOT NULL,
  U                DOUBLE       NOT NULL,
  I                DOUBLE       NOT NULL,
  R                DOUBLE       NOT NULL,
  risk             DOUBLE       NOT NULL,
  contributors_json TEXT        NOT NULL,
  computed_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(feature_id, contract_version, granularity)
);
