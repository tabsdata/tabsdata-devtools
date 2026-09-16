#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsPositive classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsPositive`` — verdict > 0;
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_positive``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 7-row input has a KNOWN composition — 2 positive, 3 non-positive (a negative,
a zero, a negative), 1 null, 1 nan — so the enrich column and the summary tallies
are exact and independent of the engine (the oracle; see functions/_harness.py).
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
        verdict,
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
        verdict,
    )

_T, _F, _NAN, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NAN, Sentinel.NULL

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for >0, FALSE for <=0, and the reserved NULL / NAN sentinels.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_positive"),
        [_T, _F, _F, _NULL, _T, _F, _NAN],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 2 positive (true), 3 non-positive (false), 1 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_positive")],
        "dq.type": ["boolean"],
        "dq.true": [2],
        "dq.false": [3],
        "dq.nan": [1],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
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
def ip_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def ip_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def ip_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
