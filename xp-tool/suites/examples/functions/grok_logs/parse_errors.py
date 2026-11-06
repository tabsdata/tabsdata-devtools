#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `TableFrame.grok`: A NARROW PATTERN, and the null-on-no-match rule.

A ROW THAT DOES NOT MATCH IS NOT AN ERROR. It comes back with NULL in every
capture column. That is the contract, and it is what makes grok usable on a real
log where the pattern only covers the lines you care about — this one matches
ERROR lines and nothing else, so every other row is nulls.

IT IS ALSO THE TRAP: a WRONG pattern looks exactly like a narrow one. An
all-null column is the same shape whether you meant to ignore those lines or
mistyped the delimiter. So CHECK FOR NULLS; do not assume a parse worked because
the transaction was green.

Turning "did not match" into "not interesting" is then deliberate — filter on
`col("err_service").is_not_null()` downstream — rather than something the parse
did silently on your behalf.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe import datatypes as td
from tabsdatak.tableframe.grok import ColumnDefinition as CD


@transformer(input_tables=["logs/app_log@NEW"], output_tables=["log_errors"])
def parse_errors(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    return log.grok(
        "message",
        r"^%{TIMESTAMP_ISO8601} ERROR %{NOTSPACE:err_service} %{GREEDYDATA:err_details}$",
        {
            "err_service": CD("err_service", td.String),
            "err_details": CD("err_details", td.String),
        },
    )
