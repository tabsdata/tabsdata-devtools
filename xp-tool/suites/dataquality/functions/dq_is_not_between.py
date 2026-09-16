#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsNotBetween classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsNotBetween`` — the complement of
    ``IsBetween``: TRUE when the value lies OUTSIDE the range. Here the range is
    ``(0, 10)`` with ``closed_on="none"`` (an OPEN interval), so a value equal to
    a boundary is NOT inside the range and therefore counts as "not between"
    (TRUE);
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_not_between``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 7-row input has a KNOWN composition — one interior value (inside the open
range -> FALSE), the two boundary values (excluded by the open interval -> TRUE),
one below and one above the range (TRUE), one null, one nan. ``closed_on="none"``
makes the boundaries flip to TRUE, exercising the open-interval semantics.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNotBetween, Summary
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

# Raw input of known composition for the OPEN range (0, 10):
# interior / lower-boundary / upper-boundary / below / above / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [5.0, 0.0, 10.0, -1.0, 15.0, None, float("nan")],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row.
# closed_on="none" -> the range is open, so 5.0 is inside (not-between FALSE) and
# the boundaries 0.0 / 10.0 are outside (not-between TRUE), as are -1.0 and 15.0.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_not_between"),
        [_F, _T, _T, _T, _T, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 4 out-of-range (true), 1 in-range (false), 1 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_not_between")],
        "dq.type": ["boolean"],
        "dq.true": [4],
        "dq.false": [1],
        "dq.nan": [1],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[
            IsNotBetween(["value"], min_val=0.0, max_val=10.0, closed_on="none")
        ],
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
def inb_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def inb_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def inb_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
