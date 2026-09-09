#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsBetween classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsBetween`` — verdict is whether the
    value lies inside the closed range ``[0, 10]`` (``closed_on="both"``, so both
    endpoints are inclusive);
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_between``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 7-row input has a KNOWN composition — an interior value, the two boundary
values (both TRUE under ``closed_on="both"``), a value below and one above the
range, one null, one nan — so the enrich column and the summary tallies are
exact and independent of the engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsBetween, Summary
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

# Raw input of known composition for the closed range [0, 10]:
# interior / lower-boundary / upper-boundary / below / above / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [5.0, 0.0, 10.0, -1.0, 15.0, None, float("nan")],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row.
# closed_on="both" -> the boundary values 0.0 and 10.0 are both TRUE.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_is_between",
        [_T, _T, _T, _F, _F, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 3 in-range (true), 2 out-of-range (false), 1 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_is_between"],
        "dq.type": ["boolean"],
        "dq.true": [3],
        "dq.false": [2],
        "dq.nan": [1],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsBetween(["value"], min_val=0.0, max_val=10.0, closed_on="both")],
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
def ib_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def ib_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def ib_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
