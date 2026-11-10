#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Filter(AnyFailed(), to_table=...) splits rows into kept vs rejected.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Filter(AnyFailed(), to_table="rejected")`` — the criteria selects the rows
    that FAIL (``AnyFailed`` = at least one classifier verdict is not TRUE for
    the row). Filter REMOVES the selected rows from ``checked`` (rewritten to only
    the rows the criteria did not select) and, since ``to_table`` is given,
    redirects them to the derived table ``rejected`` instead of discarding them.
    ``include_quality_columns`` defaults to ``"none"``, so neither output carries
    the verdict column — both keep only the original user columns.

With ``AnyFailed`` and defaults (``none_is_ok=False``, ``nan_is_ok=False``) a null
or nan verdict counts as a failure, so null and nan rows are rejected too.

The 7-row input has a KNOWN composition — 2 positive (kept), 5 not-positive
(3 non-positive + 1 null + 1 nan, rejected) — so the split is exact and
independent of the engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import AnyFailed, DataQuality, Filter, IsPositive
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

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

# Rows AnyFailed does not select (value_is_positive is TRUE) stay in ``checked``.
_KEPT = pl.DataFrame(
    {
        "id": [0, 4],
        "value": [10.0, 3.0],
    }
)

# Rows AnyFailed selects (<=0, null, nan) are removed and redirected to ``rejected``.
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
        operators=[Filter(AnyFailed(), to_table="rejected")],
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
def flt_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def flt_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
