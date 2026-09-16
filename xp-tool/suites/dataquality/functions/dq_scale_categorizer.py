#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the ScaleCategorizer with use_bin_zero, plus Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. This file exercises the ``ScaleCategorizer`` classifier
itself with ``use_bin_zero=True`` on a ``LinearScale``, complementing the
per-scale files (which mostly leave bin 0 off). The action:
  * categorizes each row of ``value`` with a ``ScaleCategorizer`` bound to a
    ``LinearScale(min_val=0, max_val=10, bins=5, use_bin_zero=True)``;
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category``;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row with per-bin tallies ``dq.p000..dq.p005`` plus the sentinel counts.

BIN-EDGE CONVENTION (from engine.categorizer): the same equal-width linear cuts
``[2, 4, 6, 8, 10]``, but with ``use_bin_zero=True`` the left endpoint
``min_val`` is split into its OWN bin 0 (``value == min_val`` is tested before
the cut chain). So ``0`` lands in bin 0 while ``(0, 2]`` lands in bin 1. A bin is
closed on its right edge (first cut with ``value <= cut``); the last cut is
pinned to ``max_val``. ``value < min_val`` underflows, ``value > max_val``
overflows; null/nan are caught first. ``dq.bins`` is reported as ``bins + 1`` (6)
when ``use_bin_zero`` is on.

The 11-row input: 1 in bin 0 (exactly 0), 2 in bin 1 (1, 2), 1 each in bins 2..5
(3, 5, 7, 10), 1 underflow, 1 overflow, 1 null, 1 nan — so the bin column and
tallies are exact.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    LinearScale,
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

# Raw input of known composition. Cuts are [2, 4, 6, 8, 10]; min_val 0 is its own
# bin 0 because use_bin_zero=True.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "value": [
            0.0,    # == min                 -> bin 0
            1.0,    # (0, 2]                  -> bin 1
            2.0,    # <= 2                    -> bin 1
            3.0,    # <= 4                    -> bin 2
            5.0,    # <= 6                    -> bin 3
            7.0,    # <= 8                    -> bin 4
            10.0,   # max, <= 10             -> bin 5
            -1.0,   # < 0                     -> underflow
            11.0,   # > 10                    -> overflow
            None,   # null
            float("nan"),  # nan
        ],
    }
)

_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_category"),
        [0, 1, 1, 2, 3, 4, 5, _U, _O, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_category")],
        "dq.type": ["categorical"],
        "dq.bins": [6],
        "dq.under": [1],
        "dq.over": [1],
        "dq.nan": [1],
        "dq.none": [1],
        "dq.p000": [1],
        "dq.p001": [2],
        "dq.p002": [1],
        "dq.p003": [1],
        "dq.p004": [1],
        "dq.p005": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[
            ScaleCategorizer(
                ["value"],
                scale=LinearScale(
                    min_val=0.0, max_val=10.0, bins=5, use_bin_zero=True
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
                "dq.p000",
                "dq.p001",
                "dq.p002",
                "dq.p003",
                "dq.p004",
                "dq.p005",
            ),
        ),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def scat_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def scat_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def scat_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
