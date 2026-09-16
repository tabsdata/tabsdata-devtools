#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a ScaleCategorizer over a MonomialScale, with Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * categorizes each row of ``value`` with a ``ScaleCategorizer`` bound to a
    ``MonomialScale(min_val=0, max_val=100, power=2, bins=2)`` — a power-law
    (here quadratic) scale;
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category``;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row with per-bin tallies ``dq.p001``/``dq.p002`` plus the sentinel counts.

BIN-EDGE CONVENTION (from engine.categorizer, MonomialScale branch): the bins
divide the range EVENLY IN THE ``value ** (1/power)`` domain, then map the cuts
back by raising to ``power`` (a non-negative ``min_val`` means no shift). Over
``[0, 100]`` with power 2 the root span is ``[0**0.5, 100**0.5] = [0, 10]``,
split at 5, so the cuts are ``[5**2, 10**2] = [25, 100]``. A bin is closed on its
right edge (first cut with ``value <= cut``); the last cut is pinned to
``max_val``. ``value < min_val`` underflows, ``value > max_val`` overflows;
null/nan are caught first.

The 9-row input: 1 underflow, 3 in bin 1 (0, 10, 25), 2 in bin 2 (30, 100), 1
overflow, 1 null, 1 nan — so the bin column and tallies are exact.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    MonomialScale,
    ScaleCategorizer,
    Summary,
)
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

_U, _O, _NAN, _NULL = (
    Sentinel.UNDERFLOW,
    Sentinel.OVERFLOW,
    Sentinel.NAN,
    Sentinel.NULL,
)

# Raw input of known composition. Cuts are [25.0, 100.0].
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8],
        "value": [
            -1.0,   # < 0              -> underflow
            0.0,    # min, <= 25       -> bin 1
            10.0,   # <= 25            -> bin 1
            25.0,   # <= 25            -> bin 1
            30.0,   # > 25, <= 100     -> bin 2
            100.0,  # max, <= 100      -> bin 2
            101.0,  # > 100            -> overflow
            None,   # null
            float("nan"),  # nan
        ],
    }
)

_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_category"),
        [_U, 1, 1, 1, 2, 2, _O, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_category")],
        "dq.type": ["categorical"],
        "dq.bins": [2],
        "dq.under": [1],
        "dq.over": [1],
        "dq.nan": [1],
        "dq.none": [1],
        "dq.p001": [3],
        "dq.p002": [2],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[
            ScaleCategorizer(
                ["value"],
                scale=MonomialScale(
                    min_val=0.0, max_val=100.0, power=2.0, bins=2
                ),
            )
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
                "dq.bins",
                "dq.under",
                "dq.over",
                "dq.nan",
                "dq.none",
                "dq.p001",
                "dq.p002",
            ),
        ),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def mono_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def mono_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def mono_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
