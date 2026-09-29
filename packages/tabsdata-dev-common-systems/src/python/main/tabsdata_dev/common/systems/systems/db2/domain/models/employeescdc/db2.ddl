-- =============================================================
-- IBM Db2 DDL — employeescdc (one table per way a row is identified)
-- =============================================================

-- A primary key the changes change (every UPDATE moves account_id).
CREATE TABLE accounts (
    account_id      INTEGER         NOT NULL PRIMARY KEY,
    owner           VARCHAR(40)     NOT NULL,
    balance         DECIMAL(12,2)   NOT NULL,
    opened_on       DATE            NOT NULL
);

-- A composite primary key.
CREATE TABLE ledger (
    account_code    VARCHAR(12)     NOT NULL,
    entry_no        INTEGER         NOT NULL,
    amount          DECIMAL(12,2)   NOT NULL,
    memo            VARCHAR(40)     NOT NULL,
    booked_on       DATE            NOT NULL,
    PRIMARY KEY (account_code, entry_no)
);

-- No primary key: a unique index names a row.
CREATE TABLE devices (
    serial          VARCHAR(20)     NOT NULL,
    model           VARCHAR(20)     NOT NULL,
    status          VARCHAR(10)     NOT NULL,
    firmware        INTEGER         NOT NULL
);
CREATE UNIQUE INDEX ux_devices_serial ON devices (serial);

-- No primary key and no index: reading_id is unique only by construction.
CREATE TABLE readings (
    reading_id      INTEGER         NOT NULL,
    device_serial   VARCHAR(20)     NOT NULL,
    reading         DECIMAL(10,3)   NOT NULL,
    taken_on        DATE            NOT NULL
);

-- xp_sentinel: written only by `tdd domain sentinel-data`, never by create/modify-data.
CREATE TABLE xp_sentinel (
    sentinel_key     VARCHAR(255)    NOT NULL PRIMARY KEY,
    sentinel_ts      TIMESTAMP       NOT NULL
);
