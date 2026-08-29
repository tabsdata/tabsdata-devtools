#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 destination: ONE FILE PER TRANSACTION.

THE PROBLEM: a destination path is a fixed string, so a subscriber that writes
`customers.parquet` writes `customers.parquet` every run, each run replacing the
last. Fine for a "current state" export; useless for a landing zone, an audit
trail, or anything a downstream reader picks up incrementally.

THE THREE TOKENS, substituted at WRITE time anywhere in a destination path

    ${TRX_ID}        the TRANSACTION id — the finest grain. One value per
                     committed transaction, so one file per write.
    ${EXEC_PLAN_ID}  the EXECUTION PLAN id — the whole plan a trigger started.
                     Several functions in one plan share it, so it GROUPS the
                     outputs of a single run.
    ${EXEC_PLAN_TS}  the plan's TIMESTAMP — sorts and reads chronologically,
                     which the opaque ids do not.

    They are the only tokens allowed; anything else in `${...}` is rejected when
    the descriptor is built, not at run time. And they are DESTINATION-only: a
    source path with a token in it is invalid, because a source globs rather than
    templates.

    There are no directories: a path with a `/` in it is one flat key that
    happens to contain a slash, so nothing is created and nothing is left
    behind empty. Paths are always relative to `base_path` — never an `s3://`
    URI.

`${TRX_ID}` in the FILENAME is the safe default for a landing zone: every write
is its own artefact, side by side in one directory — which is exactly the shape a
wildcard + `initial_last_modified` source consumes. These directories GROW;
nothing prunes them, and that is the trade for keeping history.

RUN THE PROJECT TWICE and watch files accumulate rather than be replaced.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.s3 import S3Dest


@subscriber(
    destination=S3Dest(paths=["exports/customers_${TRX_ID}.parquet"]),
    input_tables=["gen/customers"],
)
def write_per_transaction(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
