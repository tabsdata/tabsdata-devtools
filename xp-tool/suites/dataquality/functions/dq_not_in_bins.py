#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Select(NotInBins(...), ...) copies out-of-bin rows out.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action categorizes each row of ``value`` with a
``ScaleCategorizer`` (a ``LinearScale`` with ``use_bin_zero=True``) into the
UInt8 bin-index verdict column ``value_category``, and then applies a single
``Select`` whose criteria is a category criteria ``NotInBins``.

NOTINBINS SEMANTICS (from PolarsCriteriaProvider.not_in_bins): the criteria
matches when ``value_category`` is NOT in the criteria's ``bins`` set (it is the
negation of ``InBins``). ``bins`` is a NON-EMPTY set of bin indices (ints 0..100)
and/or the sentinel strings ``"none"`` / ``"nan"`` / ``"underflow"`` /
``"overflow"``; here ``bins={0, 1, 2, "underflow"}`` mixes plain indices with the
underflow sentinel.

SELECT SEMANTICS (from engine.select): ``Select`` never modifies the target — it
COPIES the criteria-TRUE rows to ``to_table`` (``selected``) and leaves
``checked`` UNCHANGED (same rows/columns as the raw input, no verdict column).
``include_quality_columns`` defaults to ``"none"``, so ``selected`` carries only
the original user columns. The selected set here is exactly the complement of the
in-bins set (bins 3/4/5, overflow, null, nan).

The 11-row input has a KNOWN composition — bins 0..5, plus underflow / overflow /
null / nan — so both frames are exact and independent of the engine (the oracle;
see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    DataQuality,
    LinearScale,
    NotInBins,
    ScaleCategorizer,
    Select,
)
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
        verdict,
    )
except ImportError:
    from _harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        unordered_equal,
        verdict,
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

# criteria bins = {0, 1, 2, underflow-sentinel}. NotInBins selects rows whose bin
# is NOT in that set: bins 3 (id 4), 4 (id 5), 5 (id 6), overflow (id 8),
# null (id 9), nan (id 10).
_SELECTED = pl.DataFrame(
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
            Select(
                NotInBins(
                    column_name=verdict("value_category"),
                    bins={0, 1, 2, "underflow"},
                ),
                to_table="selected",
            )
        ],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` is untouched — same rows/columns as the raw input.
        Expect("checked", _INPUT, unordered_equal),
        # the out-of-bins rows were copied to the derived table (no verdict column).
        Expect("selected", _SELECTED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def nib_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def nib_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def nib_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
