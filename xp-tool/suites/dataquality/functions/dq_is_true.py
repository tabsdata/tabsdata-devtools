#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsTrue classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of the Boolean column ``value`` with ``IsTrue`` — verdict
    TRUE when the value is ``True``, FALSE for ``False``, and the reserved NULL
    sentinel for a null (a Boolean column has no NaN);
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_true`` to
    ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 6-row input has a KNOWN composition — 3 true, 2 false, 1 null — so the enrich
column and the summary tallies are exact and independent of the engine (the
oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsTrue, Summary
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

_T, _F, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NULL

# Raw input of known composition over a Boolean column: true / false / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": [True, False, True, None, False, True],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for ``True``, FALSE for ``False``, NULL sentinel for a null.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_true"),
        [_T, _F, _T, _NULL, _F, _T],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 3 true, 2 false, 0 nan (Boolean has no NaN), 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_true")],
        "dq.type": ["boolean"],
        "dq.true": [3],
        "dq.false": [2],
        "dq.nan": [0],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsTrue(["value"])],
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
def itr_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def itr_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def itr_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
