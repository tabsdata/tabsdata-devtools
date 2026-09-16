#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsNotNullNorNan classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsNotNullNorNan`` — verdict: is the
    value neither NULL nor NaN?
  * ``Enrich()`` (no to_table) appends the verdict column
    ``value_is_not_null_nor_nan`` to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

QUIRK — unlike IsNotNull / IsNotNan, this classifier emits NO reserved sentinels.
The engine folds both the null and the nan case into the ``is_null | is_nan``
predicate and negates it, so both are labelled plain FALSE (never the NULL(255)/
NAN(254) sentinels). Hence ``dq.nan`` and ``dq.none`` are BOTH 0 — the null and nan
rows are counted under ``dq.false``, not under the sentinel tallies.

The 6-row input has a KNOWN composition — 4 regular floats, 1 null, 1 nan — so the
enrich column and the summary tallies are exact and independent of the engine (the
oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNotNullNorNan, Summary
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
# TRUE for the regular values, FALSE for BOTH the null row and the nan row (folded
# into one negated predicate). No reserved sentinels are produced by this classifier.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_not_null_nor_nan"),
        [_T, _T, _T, _F, _F, _T],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 4 regular (true), 2 false (the null and nan rows), 0 nan-sentinel, 0 null-sentinel.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_not_null_nor_nan")],
        "dq.type": ["boolean"],
        "dq.true": [4],
        "dq.false": [2],
        "dq.nan": [0],
        "dq.none": [0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsNotNullNorNan(["value"])],
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
def isnotnullnornan_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def isnotnullnornan_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def isnotnullnornan_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
