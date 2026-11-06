#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `TableFrame.grok`: THE CORE SPLIT of a log line into columns.

    frame.grok(expr, pattern, schema)

    `expr`     WHICH column to parse — its name, or any `Expr` that resolves to
               one string column (see `parse_renamed.py`).
    `pattern`  a GROK pattern: `%{PATTERN:capture}` placeholders around literal
               text. Standard logstash-style names are built in — `INT`,
               `NUMBER`, `WORD`, `NOTSPACE`, `DATA`, `GREEDYDATA`, `LOGLEVEL`,
               `TIMESTAMP_ISO8601`, `IPV4`, `EMAILADDRESS`, ...
    `schema`   `{capture_name: ColumnDefinition(column_name, dtype)}`, one entry
               per capture you want to KEEP. Dict ORDER is output column order.

grok APPENDS the new columns and keeps the source column, so it is
ROW-PRESERVING — which is what a `@transformer`'s output has to be for a
subscriber to sink it.

TWO PATTERN RULES WORTH THE SPACE

  1. ANCHOR IT. A pattern is a SEARCH, not a full match, so unanchored
     `%{INT:status}` happily matches digits inside a timestamp. `^...$` around
     the whole line is the safe default, and it is what makes a non-matching line
     genuinely non-matching.

  2. `%{WORD}` vs `%{DATA}` vs `%{GREEDYDATA}`. `WORD` stops at the first
     non-word character, so it cannot capture `order-service` or a value with a
     space. `DATA` is NON-GREEDY: it stops at whatever literal comes next in the
     pattern — the right choice for a field between two delimiters. `GREEDYDATA`
     takes everything to the end — the right choice for "and the rest, verbatim".

Here `%{NOTSPACE:service}` is what handles `order-service`, and
`%{GREEDYDATA:details}` keeps the `key=value` tail for the other patterns in this
suite to mine.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe import datatypes as td
from tabsdatak.tableframe.grok import ColumnDefinition as CD


@transformer(input_tables=["logs/app_log@NEW"], output_tables=["log_fields"])
def parse_fields(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    return log.grok(
        "message",
        r"^%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level} %{NOTSPACE:service} "
        r"%{GREEDYDATA:details}$",
        {
            "ts": CD("ts", td.String),
            "level": CD("level", td.String),
            "service": CD("service", td.String),
            "details": CD("details", td.String),
        },
    )
