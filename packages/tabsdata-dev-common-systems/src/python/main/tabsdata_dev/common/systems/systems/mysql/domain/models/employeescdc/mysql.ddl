-- =============================================================
-- MySQL DDL — employeescdc (one table per way a row is identified)
-- =============================================================

-- A primary key the changes change (every UPDATE moves account_id).
CREATE TABLE accounts (
    account_id      INT             NOT NULL,
    owner           VARCHAR(40)     NOT NULL,
    balance         DECIMAL(12,2)   NOT NULL,
    opened_on       DATE            NOT NULL,
    PRIMARY KEY (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A composite primary key.
CREATE TABLE ledger (
    account_code    VARCHAR(12)     NOT NULL,
    entry_no        INT             NOT NULL,
    amount          DECIMAL(12,2)   NOT NULL,
    memo            VARCHAR(40)     NOT NULL,
    booked_on       DATE            NOT NULL,
    PRIMARY KEY (account_code, entry_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- No primary key: a unique index names a row.
CREATE TABLE devices (
    serial          VARCHAR(20)     NOT NULL,
    model           VARCHAR(20)     NOT NULL,
    status          VARCHAR(10)     NOT NULL,
    firmware        INT             NOT NULL,
    UNIQUE KEY ux_devices_serial (serial)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- No primary key and no index: reading_id is unique only by construction.
CREATE TABLE readings (
    reading_id      INT             NOT NULL,
    device_serial   VARCHAR(20)     NOT NULL,
    reading         DECIMAL(10,3)   NOT NULL,
    taken_on        DATE            NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A plain primary key, on a table no CDC suite's stream tracks: changed by every
-- data verb, carried by no stream.
CREATE TABLE audit (
    audit_id        INT             NOT NULL,
    actor           VARCHAR(40)     NOT NULL,
    action          VARCHAR(20)     NOT NULL,
    noted_on        DATE            NOT NULL,
    PRIMARY KEY (audit_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- xp_sentinel: written only by `tdd domain sentinel-data`, never by create/modify-data.
CREATE TABLE xp_sentinel (
    sentinel_key     VARCHAR(255)    NOT NULL,
    sentinel_ts      DATETIME        NOT NULL,
    PRIMARY KEY (sentinel_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
