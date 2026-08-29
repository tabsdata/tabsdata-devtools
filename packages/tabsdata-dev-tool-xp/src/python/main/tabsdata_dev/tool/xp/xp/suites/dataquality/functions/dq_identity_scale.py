#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a ScaleCategorizer over an IdentityScale, with Enrich + Summary.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * categorizes each row of ``value`` (an INTEGER column) with a
    ``ScaleCategorizer`` bound to an ``IdentityScale(min_val=0, max_val=5,
    use_bin_zero=True)`` — one bin per integer in the range;
  * ``Enrich()`` (no to_table) appends the BIN-INDEX column ``value_category``;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` — one CATEGORY
    row with per-bin tallies ``dq.p000..dq.p005`` plus the sentinel counts.

BIN-EDGE CONVENTION (from engine.categorizer, IdentityScale branch): the number
of bins is ``max_val - min_val`` (a property, not a constructor arg) and the cuts
are the consecutive integers ``[min_val+1, ..., max_val]`` = ``[1, 2, 3, 4, 5]``.
Because ``use_bin_zero=True`` the left endpoint ``min_val`` gets its own bin 0
(``value == min_val`` is checked before the cuts), so the mapping is a true
identity: ``0->0, 1->1, ..., 5->5``. ``value < min_val`` underflows,
``value > max_val`` overflows; null is caught first. This is an integer column,
so no NaN sentinel arises. ``dq.bins`` is reported as ``bins + 1`` (6) when
``use_bin_zero`` is on.

The 9-row input has exactly one value per bin 0..5, one underflow, one overflow,
and one null — so the bin column and tallies are exact.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    IdentityScale,
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

_U, _O, _NULL = Sentinel.UNDERFLOW, Sentinel.OVERFLOW, Sentinel.NULL

# Raw input of known composition — an INTEGER column, one value per bin plus the
# underflow / overflow / null cases (an int column cannot hold NaN).
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6, 7, 8],
        "value": [
            -1,   # < 0            -> underflow
            0,    # == min         -> bin 0
            1,    # <= 1           -> bin 1
            2,    # <= 2           -> bin 2
            3,    # <= 3           -> bin 3
            4,    # <= 4           -> bin 4
            5,    # max, <= 5      -> bin 5
            6,    # > 5            -> overflow
            None,  # null
        ],
    }
)

_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_category",
        [_U, 0, 1, 2, 3, 4, 5, _O, _NULL],
        dtype=pl.UInt8,
    )
)

_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_category"],
        "dq.type": ["categorical"],
        "dq.bins": [6],
        "dq.under": [1],
        "dq.over": [1],
        "dq.nan": [0],
        "dq.none": [1],
        "dq.p000": [1],
        "dq.p001": [1],
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
                scale=IdentityScale(min_val=0, max_val=5, use_bin_zero=True),
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
def ident_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def ident_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def ident_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
