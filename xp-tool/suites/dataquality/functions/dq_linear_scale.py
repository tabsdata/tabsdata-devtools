#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a ScaleCategorizer over a LinearScale, with Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * categorizes each row of ``value`` with a ``ScaleCategorizer`` bound to a
    ``LinearScale(min_val=0, max_val=10, bins=5)`` — the range ``[0, 10]`` split
    into 5 equal-width bins (cut edges 2, 4, 6, 8, 10);
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category`` to
    ``checked`` in place (a UInt8 holding 1..5 for in-range rows and the reserved
    252 under / 253 over / 254 nan / 255 null sentinels);
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row (``dq.type = "categorical"``) with per-bin tallies ``dq.p001..dq.p005``
    and the ``dq.under``/``dq.over``/``dq.nan``/``dq.none`` counts.

BIN-EDGE CONVENTION (from engine.categorizer): a bin is closed on its right edge,
so bin ``i`` (1-based) captures the first cut with ``value <= cut``. Bin 1 also
takes the left endpoint ``min_val`` (``use_bin_zero`` is off, so ``min_val`` is
NOT split into its own bin 0). ``value < min_val`` underflows (252) and
``value > max_val`` overflows (253); null/nan are caught before either.

The 11-row input has a KNOWN composition — 1 underflow, 2 in bin 1 (0, 1), 1 in
bin 2 (3), 1 in bin 3 (5), 1 in bin 4 (7), 2 in bin 5 (9, 10), 1 overflow, 1
null, 1 nan — so the bin column and summary tallies are exact and independent of
the engine (the oracle; see functions/_harness.py).
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

# Raw input of known composition, one value per bin plus each sentinel case.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "value": [
            -1.0,   # < 0            -> underflow
            0.0,    # min, <= 2      -> bin 1
            1.0,    # <= 2           -> bin 1
            3.0,    # <= 4           -> bin 2
            5.0,    # <= 6           -> bin 3
            7.0,    # <= 8           -> bin 4
            9.0,    # <= 10          -> bin 5
            10.0,   # max, <= 10     -> bin 5
            11.0,   # > 10           -> overflow
            None,   # null
            float("nan"),  # nan
        ],
    }
)

# ``checked`` after Enrich: the bin-index column appended, one UInt8 per row.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_category",
        [_U, 1, 1, 2, 3, 4, 5, 5, _O, _NULL, _NAN],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one CATEGORY row — the per-bin tallies for this scale.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_category"],
        "dq.type": ["categorical"],
        "dq.bins": [5],
        "dq.under": [1],
        "dq.over": [1],
        "dq.nan": [1],
        "dq.none": [1],
        "dq.p001": [2],
        "dq.p002": [1],
        "dq.p003": [1],
        "dq.p004": [1],
        "dq.p005": [2],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[
            ScaleCategorizer(
                ["value"],
                scale=LinearScale(min_val=0.0, max_val=10.0, bins=5),
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
                "dq.p003",
                "dq.p004",
                "dq.p005",
            ),
        ),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def lin_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def lin_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def lin_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
