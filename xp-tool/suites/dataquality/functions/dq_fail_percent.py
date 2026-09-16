#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a NON-triggering Fail(PercentThreshold) with Enrich().

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_positive`` to
    ``checked`` in place;
  * ``Fail(AllOk(), threshold=PercentThreshold(percent=25.0))`` — Fail raises (and
    aborts the transaction) only when the quality gate is NOT satisfied.

PERCENTTHRESHOLD SEMANTICS (from PolarsCriteriaProvider._threshold): the gate
computes ``percent = matching_rows / total_rows * 100`` (a 0..100 scale — the
count is literally multiplied by 100 then divided by the row count) and, for an
``AllOk`` criteria, is satisfied when ``percent >= threshold.percent``. Here the
matching (all-classifiers-TRUE) rows are 2 of 4, i.e. 50.0%, and the threshold is
25.0%; 50 >= 25, so the gate holds, Fail does NOT raise, and the transaction
completes — ``checked`` is still produced. (``percent`` is on 0..100, NOT a 0..1
fraction; picking 0.25 here would have compared 50 >= 0.25 and still passed, so
25.0 is used to make the 0..100 scale explicit.)

This exercises the Fail + PercentThreshold wiring/serde and the engine's
non-triggering percent path without failing the run. Fail itself yields no table,
so the only produced table is the enriched ``checked``.

The 4-row input has a KNOWN composition — 2 positive, 2 non-positive — so the
enrich column is exact and the 50% pass rate comfortably clears the 25% gate (the
oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    AllOk,
    DataQuality,
    Enrich,
    Fail,
    IsPositive,
    PercentThreshold,
)
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        Sentinel,
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
        unordered_equal,
        verdict,
    )

_T, _F = Sentinel.TRUE, Sentinel.FALSE

# Raw input of known composition: 2 positive, 2 non-positive (all-ok count == 2,
# i.e. 50% of 4 rows pass AllOk).
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3],
        "value": [10.0, 3.0, -5.0, 0.0],
    }
)

# ``checked`` after Enrich(): the verdict column appended, one UInt8 per row —
# TRUE for >0, FALSE for <=0.
_ENRICHED = _INPUT.with_columns(
    pl.Series(verdict("value_is_positive"), [_T, _T, _F, _F], dtype=pl.UInt8)
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[
            Enrich(),
            # gate: require >= 25% passing rows; we have 50%, so this does NOT fire.
            Fail(AllOk(), threshold=PercentThreshold(percent=25.0)),
        ],
    ),
    main_tables=["checked"],
    expects=[
        Expect("checked", _ENRICHED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def fpc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def fpc_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def fpc_sub(c0: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0])
    return TableFrame.empty()
