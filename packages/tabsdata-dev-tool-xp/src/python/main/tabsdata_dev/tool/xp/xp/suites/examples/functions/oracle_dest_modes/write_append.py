#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Oracle destination: `if_table_exists="append"`.

INSERT the rows. The table keeps growing across runs, and if it does not exist it
is CREATED on the first write.

APPEND IS NOT AN UPSERT. There is no key matching, no merge, and no delete of
rows this run did not produce — re-running this publishes the same three rows
again. An event log wants `append`; a table that mirrors a source of truth wants
`replace`; a real upsert is built downstream, not here.

THE SHAPE OF A SQL DESTINATION
    `tables` declares one WRITE SLOT per entry, fed by `input_tables` in the SAME
    ORDER, and the function returns one frame per slot. Names may be bare or
    qualified; a bare name resolves against the connection's default schema.

ORACLE SPECIFICS
    Oracle folds unquoted identifiers to UPPERCASE, so `customers_append` below
    creates a table called `CUSTOMERS_APPEND`. Double-quote the name in
    `tables` to keep it lowercase. Oracle NUMBER is a single numeric type, so
    an integer column may come back as a float on a later read.

RE-RUN THE PROJECT and compare with `write_replace`: this target grows by three
rows each time, that one stays at three.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.oracle import OracleDest


@subscriber(
    destination=OracleDest(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
