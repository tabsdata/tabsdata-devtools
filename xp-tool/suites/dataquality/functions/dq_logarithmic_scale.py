#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a ScaleCategorizer over a LogarithmicScale, with Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * categorizes each row of ``value`` with a ``ScaleCategorizer`` bound to a
    ``LogarithmicScale(min_val=0, max_val=2, base=10, bins=2)``;
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category``;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row with per-bin tallies ``dq.p001``/``dq.p002`` plus the sentinel counts.

BIN-EDGE CONVENTION (from engine.categorizer, LogarithmicScale branch): the bins
divide the range EVENLY IN THE ANTILOG domain, then map the cut edges back with
the logarithm. With base 10 over ``[0, 2]`` and 2 bins the antilog span is
``[10**0, 10**2] = [1, 100]``, split at the midpoint 50.5, so the cuts are
``[log10(50.5), 2] = [~1.7033, 2]``. A bin is closed on its right edge (first cut
with ``value <= cut``); the last cut is pinned to ``max_val``. ``value < min_val``
underflows, ``value > max_val`` overflows; null/nan are caught first.

The 9-row input is chosen well clear of the ~1.7033 boundary: 1 underflow, 3 in
bin 1 (0, 1, 1.5), 2 in bin 2 (1.8, 2), 1 overflow, 1 null, 1 nan.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    LogarithmicScale,
    ScaleCategorizer,
    Summary,
)
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

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

# Raw input of known composition. Cuts are [~1.7033, 2.0]; values stay clear of
# the ~1.7033 boundary so every bin assignment is unambiguous.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8],
        "value": [
            -0.5,   # < 0                 -> underflow
            0.0,    # min, <= 1.7033      -> bin 1
            1.0,    # <= 1.7033           -> bin 1
            1.5,    # <= 1.7033           -> bin 1
            1.8,    # > 1.7033, <= 2      -> bin 2
            2.0,    # max, <= 2           -> bin 2
            2.5,    # > 2                 -> overflow
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
                scale=LogarithmicScale(
                    min_val=0.0, max_val=2.0, base=10.0, bins=2
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
def log_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def log_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def log_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
