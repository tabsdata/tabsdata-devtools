#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Filter(AllOk(), to_table=...) splits rows into kept vs rejected.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Filter(AllOk(), to_table="rejected")`` — the criteria selects the rows that
    PASS (``AllOk`` = every classifier is TRUE for the row). Those passing rows
    stay in ``checked`` (rewritten to only the kept rows); the rows that do NOT
    pass (false / null / nan verdicts) are redirected to the derived table
    ``rejected``. ``include_quality_columns`` defaults to ``"none"``, so neither
    output carries the verdict column — both keep only the original user columns.

With ``AllOk`` and defaults (``none_is_ok=False``, ``nan_is_ok=False``) only a
TRUE verdict counts as passing, so null and nan rows are rejected too.

The 7-row input has a KNOWN composition — 2 positive (kept), 5 not-positive
(3 non-positive + 1 null + 1 nan, rejected) — so the split is exact and
independent of the engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import AllOk, DataQuality, Filter, IsPositive
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

# Rows that PASS AllOk (value_is_positive is TRUE) stay in ``checked``.
_KEPT = pl.DataFrame(
    {
        "id": [0, 4],
        "value": [10.0, 3.0],
    }
)

# Rows that do NOT pass (<=0, null, nan) are redirected to ``rejected``.
_REJECTED = pl.DataFrame(
    {
        "id": [1, 2, 3, 5, 6],
        "value": [-5.0, 0.0, None, -1.0, float("nan")],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[Filter(AllOk(), to_table="rejected")],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` now holds only the passing rows (no verdict column).
        Expect("checked", _KEPT, unordered_equal),
        # the rejected rows landed in the derived table (no verdict column).
        Expect("rejected", _REJECTED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def flt_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def flt_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def flt_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
