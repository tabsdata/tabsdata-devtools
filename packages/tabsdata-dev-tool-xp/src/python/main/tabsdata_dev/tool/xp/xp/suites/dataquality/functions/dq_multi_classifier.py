#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: two classifiers -> two verdict columns + two summary rows.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action runs TWO classifiers over two columns and
then enriches + summarises both:
  * ``IsPositive(["a"])`` -> verdict column ``a_is_positive`` (a > 0);
  * ``IsNull(["b"])``     -> verdict column ``b_is_null`` (b IS NULL);
  * ``Enrich()`` (no to_table) appends BOTH verdict columns to ``checked`` in
    place, in sorted column-name order (``a_is_positive`` then ``b_is_null``);
  * ``Summary()`` emits ``checked_dq_summary`` with ONE ROW PER classifier
    (again sorted), so two boolean summary rows.

The 4-row input has a KNOWN composition per column — ``a``: 2 positive / 2
non-positive; ``b``: 2 null / 2 non-null — so both verdict columns and both
summary rows are exact and independent of the engine (the oracle; see
functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNull, IsPositive, Summary
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

_T, _F = Sentinel.TRUE, Sentinel.FALSE

# Raw input: ``a`` for IsPositive (2 positive / 2 non-positive), ``b`` for IsNull
# (2 null / 2 non-null). ``b`` is an integer column, so it has no nan sentinels.
_INPUT = pl.DataFrame(
    {
        "a": [5.0, -2.0, 0.0, 1.0],
        "b": [1, None, 3, None],
    }
)

# ``checked`` after Enrich(): BOTH verdict columns appended, in sorted order.
#   a_is_positive: TRUE for a>0  -> [5>0, -2>0, 0>0, 1>0]  = [T, F, F, T]
#   b_is_null    : TRUE for null -> [1, None, 3, None]      = [F, T, F, T]
_ENRICHED = _INPUT.with_columns(
    pl.Series("a_is_positive", [_T, _F, _F, _T], dtype=pl.UInt8),
    pl.Series("b_is_null", [_F, _T, _F, _T], dtype=pl.UInt8),
)

# ``checked_dq_summary``: one row per classifier, in sorted column-name order.
#   a_is_positive: 2 true (5, 1), 2 false (-2, 0), 0 nan, 0 none
#   b_is_null    : 2 true (nulls), 2 false (1, 3), 0 nan, 0 none
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["a_is_positive", "b_is_null"],
        "dq.type": ["boolean", "boolean"],
        "dq.true": [2, 2],
        "dq.false": [2, 2],
        "dq.nan": [0, 0],
        "dq.none": [0, 0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["a"]), IsNull(["b"])],
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
def mlt_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def mlt_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def mlt_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
