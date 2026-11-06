#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `TableFrame.grok`: RENAMING, and passing an `Expr` as `expr`.

TWO NAMES ARE IN PLAY and they are not the same thing:

    the CAPTURE name   what the pattern calls it — `%{NOTSPACE:service}`
    the COLUMN name    what the table gets — `ColumnDefinition("component", ...)`

So the log's vocabulary does not have to become your warehouse's. Rename at the
boundary and downstream code never learns that the source called it `service`.

CAPTURES YOU DO NOT LIST ARE NOT KEPT. The pattern below still matches and
captures `ts` and `level` — they are just absent from `schema`, so no columns are
produced for them. Matching more than you keep is normal and cheap: the pattern's
job is to locate the field, the schema's job is to decide what survives.

`expr` MAY BE AN EXPRESSION, not only a column name — anything that resolves to
one string column. `col("message")` here is the trivial case; the useful ones are
things like a concatenation, or a column selected out of a struct.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe import datatypes as td
from tabsdatak.tableframe.functions import col
from tabsdatak.tableframe.grok import ColumnDefinition as CD


@transformer(input_tables=["logs/app_log@NEW"], output_tables=["log_renamed"])
def parse_renamed(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    return log.grok(
        col("message"),
        r"^%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level} %{NOTSPACE:service} "
        r"%{GREEDYDATA:details}$",
        {"service": CD("component", td.String)},
    )
