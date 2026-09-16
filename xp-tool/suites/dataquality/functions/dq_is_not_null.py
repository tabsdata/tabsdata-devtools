#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsNotNull classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsNotNull`` — verdict: is the value
    NOT null?
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_not_null`` to
    ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

QUIRK — IsNotNull does NOT reduce a NaN row to a plain TRUE. The engine tests
``is_null`` first (FALSE), then ``is_nan`` (the reserved NAN sentinel 254), and only
then TRUE. So a NaN value is labelled with the NAN sentinel, not TRUE, and it is
tallied under ``dq.nan`` — never under ``dq.true``.

The 6-row input has a KNOWN composition — 4 regular floats, 1 null, 1 nan — so the
enrich column and the summary tallies are exact and independent of the engine (the
oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNotNull, Summary
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

# Raw input of known composition: 4 regular floats, 1 null, 1 nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": [10.0, -5.0, 0.0, None, float("nan"), 2.0],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for the regular values, FALSE for the null row, the reserved NAN sentinel
# for the nan row (a nan is NOT TRUE here — it is the NAN sentinel).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_not_null"),
        [_T, _T, _T, _F, _NAN, _T],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 4 regular (true), 1 null (false), 1 nan, 0 null-sentinel.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_not_null")],
        "dq.type": ["boolean"],
        "dq.true": [4],
        "dq.false": [1],
        "dq.nan": [1],
        "dq.none": [0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsNotNull(["value"])],
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
def isnotnull_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def isnotnull_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def isnotnull_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
