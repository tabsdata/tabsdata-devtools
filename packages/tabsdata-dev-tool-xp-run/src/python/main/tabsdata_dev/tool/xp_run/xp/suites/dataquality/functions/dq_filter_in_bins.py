#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Filter(InBins(...), ...) keeps in-bin rows, redirects the rest.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action categorizes each row of ``value`` with a
``ScaleCategorizer`` (a ``LinearScale`` with ``use_bin_zero=True``) into the
UInt8 bin-index verdict column ``value_category`` (the engine's suffix for
``ScaleCategorizer`` is ``_category``), and then applies a single ``Filter``
whose criteria is a category criteria ``InBins``.

INBINS SEMANTICS (from PolarsCriteriaProvider.in_bins): the criteria matches when
``value_category`` is in the criteria's ``bins`` set. ``bins`` is a NON-EMPTY set
of bin indices (ints 0..100) and/or the sentinel strings ``"none"`` / ``"nan"`` /
``"underflow"`` / ``"overflow"``, which the engine maps to the reserved byte
sentinels (255 / 254 / 252 / 253). Here ``bins={0, 1, 2, "underflow"}`` mixes
three plain bin indices with the underflow sentinel to exercise both shapes.

FILTER DIRECTION (from engine.filter): criteria-TRUE rows STAY in ``checked``
(rewritten in place); criteria-FALSE rows are redirected to ``to_table``
(``out_of_bins``). ``include_quality_columns`` defaults to ``"none"``, so neither
output carries the ``value_category`` column — both keep only the user columns.

BIN-EDGE CONVENTION (see dq_scale_categorizer): cuts are ``[2, 4, 6, 8, 10]``;
with ``use_bin_zero=True`` ``value == min_val`` is its own bin 0, ``(0, 2]`` is
bin 1, and so on; ``value < min`` underflows, ``value > max`` overflows, null/nan
are caught first.

The 11-row input has a KNOWN composition — bins 0..5, plus underflow / overflow /
null / nan — so the split is exact and independent of the engine (the oracle; see
functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    Filter,
    InBins,
    LinearScale,
    ScaleCategorizer,
)
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
    )
except ImportError:
    from _harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
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

# criteria bins = {0, 1, 2, underflow-sentinel}. Rows whose bin is IN that set
# stay in ``checked``: bins 0 (id 0), 1 (ids 1, 2), 2 (id 3), underflow (id 7).
_CHECKED = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 7],
        "value": [0.0, 1.0, 2.0, 3.0, -1.0],
    }
)

# The remaining rows (bins 3/4/5, overflow, null, nan) are redirected.
_OUT_OF_BINS = pl.DataFrame(
    {
        "id": [4, 5, 6, 8, 9, 10],
        "value": [5.0, 7.0, 10.0, 11.0, None, float("nan")],
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
        operators=[
            Filter(
                InBins(column_name="value_category", bins={0, 1, 2, "underflow"}),
                to_table="out_of_bins",
            )
        ],
    ),
    main_tables=["checked"],
    expects=[
        Expect("checked", _CHECKED, unordered_equal),
        Expect("out_of_bins", _OUT_OF_BINS, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def fib_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def fib_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def fib_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
