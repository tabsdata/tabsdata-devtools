#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a ScaleCategorizer over an ExponentialScale, with Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * categorizes each row of ``value`` with a ``ScaleCategorizer`` bound to an
    ``ExponentialScale(min_val=1, max_val=100, base=10, bins=2)``;
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category``;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row with per-bin tallies ``dq.p001``/``dq.p002`` plus the sentinel counts.

BIN-EDGE CONVENTION (from engine.categorizer, ExponentialScale branch): the bins
divide the range EVENLY IN THE LOG domain, then map the cut edges back by
exponentiation. With ``min_val > 0`` no shift is applied; over ``[1, 100]`` base
10 the log span is ``[log10 1, log10 100] = [0, 2]``, split at 1, so the cuts are
``[10**1, 10**2] = [10, 100]``. A bin is closed on its right edge (first cut with
``value <= cut``); the last cut is pinned to ``max_val``. ``value < min_val``
underflows, ``value > max_val`` overflows; null/nan are caught first.

The 9-row input: 1 underflow, 3 in bin 1 (1, 5, 10), 2 in bin 2 (50, 100), 1
overflow, 1 null, 1 nan — so the bin column and tallies are exact.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    ExponentialScale,
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

_U, _O, _NAN, _NULL = (
    Sentinel.UNDERFLOW,
    Sentinel.OVERFLOW,
    Sentinel.NAN,
    Sentinel.NULL,
)

# Raw input of known composition. Cuts are [10.0, 100.0].
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8],
        "value": [
            0.5,    # < 1              -> underflow
            1.0,    # min, <= 10       -> bin 1
            5.0,    # <= 10            -> bin 1
            10.0,   # <= 10            -> bin 1
            50.0,   # > 10, <= 100     -> bin 2
            100.0,  # max, <= 100      -> bin 2
            150.0,  # > 100            -> overflow
            None,   # null
            float("nan"),  # nan
        ],
    }
)

_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_category",
        [_U, 1, 1, 1, 2, 2, _O, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_category"],
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
                scale=ExponentialScale(
                    min_val=1.0, max_val=100.0, base=10.0, bins=2
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
def exp_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def exp_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def exp_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
