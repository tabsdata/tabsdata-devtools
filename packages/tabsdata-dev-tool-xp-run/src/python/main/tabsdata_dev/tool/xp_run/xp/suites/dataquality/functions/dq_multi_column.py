#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: ONE classifier over MULTIPLE columns -> one verdict per column.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action runs a SINGLE classifier over TWO columns:
  * ``IsPositive(["a", "b"])`` — one classifier, ``column_names`` a list of >1 —
    so the engine emits ONE verdict column PER input column, named ``<col>_<verb>``:
    ``a_is_positive`` (a > 0) and ``b_is_positive`` (b > 0);
  * ``Enrich()`` (no to_table) appends BOTH verdict columns to ``checked`` in
    place, user columns first (input order ``a``, ``b``) then the verdict columns
    in sorted name order (``a_is_positive`` then ``b_is_positive``);
  * ``Summary()`` emits ``checked_dq_summary`` with ONE ROW PER produced verdict
    column (again sorted), so two boolean summary rows with per-column tallies.

The 5-row input has a KNOWN, DIFFERENT composition per column so the two verdict
columns and the two summary rows are distinct and exact (the oracle; see
functions/_harness.py):
  * ``a`` = [5, -2, 0, 1, null]      -> 2 positive / 2 non-positive / 1 null;
  * ``b`` = [3, nan, -1, 7, 2]       -> 3 positive / 1 non-positive / 1 nan.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsPositive, Summary
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        Sentinel,
        subset_equal,
        unordered_equal,
    )
except ImportError:
    from _harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        Sentinel,
        subset_equal,
        unordered_equal,
    )

_T, _F, _NAN, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NAN, Sentinel.NULL

# Two numeric columns of known, DIFFERENT composition. ``a`` carries a null;
# ``b`` carries a nan — so the two verdict columns and the two summary rows are
# distinct (they differ in the null vs nan sentinel and in the true/false split).
_INPUT = pl.DataFrame(
    {
        "a": [5.0, -2.0, 0.0, 1.0, None],
        "b": [3.0, float("nan"), -1.0, 7.0, 2.0],
    }
)

# ``checked`` after Enrich(): user columns (input order) then BOTH verdict columns
# in sorted name order. One UInt8 verdict per row per column.
#   a_is_positive: [5>0, -2>0, 0>0, 1>0, null] = [T, F, F, T, NULL]
#   b_is_positive: [3>0, nan,  -1>0, 7>0, 2>0] = [T, NAN, F, T, T]
_ENRICHED = _INPUT.with_columns(
    pl.Series("a_is_positive", [_T, _F, _F, _T, _NULL], dtype=pl.UInt8),
    pl.Series("b_is_positive", [_T, _NAN, _F, _T, _T], dtype=pl.UInt8),
)

# ``checked_dq_summary``: one row per verdict column, in sorted name order.
#   a_is_positive: 2 true (5, 1), 2 false (-2, 0), 0 nan, 1 none (null)
#   b_is_positive: 3 true (3, 7, 2), 1 false (-1), 1 nan, 0 none
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["a_is_positive", "b_is_positive"],
        "dq.type": ["boolean", "boolean"],
        "dq.true": [2, 3],
        "dq.false": [2, 1],
        "dq.nan": [0, 1],
        "dq.none": [1, 0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["a", "b"])],
        operators=[Enrich(), Summary()],
    ),
    main_tables=["checked"],
    expects=[
        Expect("checked", _ENRICHED, unordered_equal),
        Expect(
            "checked_dq_summary",
            _SUMMARY,
            subset_equal(
                "dq.classifier",
                "dq.type",
                "dq.true",
                "dq.false",
                "dq.nan",
                "dq.none",
            ),
        ),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def mcol_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def mcol_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def mcol_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
