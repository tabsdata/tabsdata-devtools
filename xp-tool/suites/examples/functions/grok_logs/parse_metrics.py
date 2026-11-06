#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `TableFrame.grok`: THE SCHEMA IS THE CAST.

Every capture arrives as TEXT. The `dtype` in its `ColumnDefinition` is the
conversion grok applies on the way out — which is where `status` stops being the
string `"200"` and becomes an `Int64` you can compare, sum and filter without a
further step.

That is the difference between a log table you can query and one you have to
clean first, and it costs one word per column.

The pattern here also shows `%{DATA}` earning its keep: it is NON-GREEDY, so it
stops at the literal ` status=` rather than swallowing it. `%{GREEDYDATA}` in the
same position would consume the rest of the line and the pattern would never
match.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe import datatypes as td
from tabsdatak.tableframe.grok import ColumnDefinition as CD


@transformer(input_tables=["logs/app_log@NEW"], output_tables=["log_metrics"])
def parse_metrics(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    return log.grok(
        "message",
        r"^%{DATA} status=%{INT:status} duration_ms=%{INT:duration}$",
        {
            "status": CD("http_status", td.Int64),
            "duration": CD("duration_ms", td.Int64),
        },
    )
