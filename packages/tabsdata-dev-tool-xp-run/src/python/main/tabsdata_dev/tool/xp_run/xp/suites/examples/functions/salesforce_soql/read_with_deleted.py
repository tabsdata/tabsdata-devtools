#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce SOQL source: DELETED ROWS, `api_version` and `src_cfg`.

`include_deleted=True` switches the call from `query` to `queryAll`, so
soft-deleted rows (the recycle bin) come back too, flagged by `IsDeleted`.

THAT IS THE ONLY WAY A MIRROR LEARNS ABOUT DELETIONS. An ordinary read simply
STOPS RETURNING the row, which is indistinguishable from "it was not modified" to
any incremental reader — so a downstream table built from `LastModifiedDate`
pages will keep a deleted record forever unless you ask for the tombstones.

`api_version` pins the REST API version. Set it when a field or a behaviour you
depend on is version-sensitive; omit it to take the connector's default.

`src_cfg` takes `salesforce.logging_level`, which turns up the client's own
logging in the worker log — handy when a SOQL query is rejected and you want to
see exactly what was sent. IT IS A NUMERIC PYTHON LOGGING LEVEL (the `logging`
constants; default `logging.ERROR`). The string `"INFO"` is NOT accepted: it
reaches the plugin and fails there at run time, not at registration.
"""
from __future__ import annotations

import logging

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceSrc


@publisher(
    source=SalesforceSrc(
        queries=["SELECT Id, Name, IsDeleted, LastModifiedDate FROM Account"],
        include_deleted=True,
        api_version="60.0",
        src_cfg={"salesforce.logging_level": logging.INFO},
    ),
    output_tables=["accounts_with_deleted"],
)
def read_with_deleted(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
