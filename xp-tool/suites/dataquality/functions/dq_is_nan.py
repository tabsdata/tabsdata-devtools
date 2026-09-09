#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsNan classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsNan`` — verdict: is the value NaN?
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_nan`` to
    ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

QUIRK — IsNan does NOT reduce a NULL row to a plain FALSE. The engine tests
``is_null`` first (the reserved NULL sentinel 255), then ``is_nan`` (TRUE), and only
then FALSE. So a null value is labelled with the NULL sentinel, not FALSE, and it is
tallied under ``dq.none`` — never under ``dq.false``.

The 6-row input has a KNOWN composition — 4 regular floats, 1 null, 1 nan — so the
enrich column and the summary tallies are exact and independent of the engine (the
oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNan, Summary
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

# Raw input of known composition: 4 regular floats, 1 null, 1 nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": [10.0, -5.0, 0.0, None, float("nan"), 2.0],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for the nan row, FALSE for the regular values, the reserved NULL sentinel
# for the null row (a null is NOT FALSE here — it is the NULL sentinel).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_is_nan",
        [_F, _F, _F, _NULL, _T, _F],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 1 nan (true), 4 regular (false), 0 nan-sentinel, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_is_nan"],
        "dq.type": ["boolean"],
        "dq.true": [1],
        "dq.false": [4],
        "dq.nan": [0],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsNan(["value"])],
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
def isnan_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def isnan_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def isnan_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
