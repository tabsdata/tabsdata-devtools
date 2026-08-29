#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Select(AllOk(), to_table=...) copies matching rows out.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Select(AllOk(), to_table="selected")`` — the criteria selects the rows that
    PASS (``AllOk`` = every classifier is TRUE for the row). Those rows are COPIED
    to the derived table ``selected``; ``checked`` is left UNCHANGED (Select never
    modifies the target). ``include_quality_columns`` defaults to ``"none"``, so
    ``selected`` carries only the original user columns (no verdict column).

The 7-row input has a KNOWN composition — 2 positive (selected), plus the full
7 rows preserved in ``checked`` — so both frames are exact and independent of the
engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import AllOk, DataQuality, IsPositive, Select
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
    )
except ImportError:
    from _harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
    )

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# Rows that PASS AllOk (value_is_positive is TRUE) are copied to ``selected``.
_SELECTED = pl.DataFrame(
    {
        "id": [0, 4],
        "value": [10.0, 3.0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[Select(AllOk(), to_table="selected")],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` is untouched — same rows/columns as the raw input.
        Expect("checked", _INPUT, unordered_equal),
        # the passing rows were copied to the derived table (no verdict column).
        Expect("selected", _SELECTED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def sel_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def sel_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def sel_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
