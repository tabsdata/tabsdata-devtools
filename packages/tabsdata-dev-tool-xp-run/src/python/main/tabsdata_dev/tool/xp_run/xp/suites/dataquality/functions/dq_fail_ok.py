#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: a NON-triggering Fail alongside Enrich() (transaction survives).

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_positive`` to
    ``checked`` in place;
  * ``Fail(AllOk(), threshold=RowCountThreshold(row_count=1))`` — Fail raises (and
    aborts the transaction) only when the quality gate is NOT satisfied. With
    ``AllOk`` + ``RowCountThreshold`` the gate is satisfied when the count of
    passing (all-classifiers-TRUE) rows is >= ``row_count``. This input has 2
    passing rows and ``row_count=1`` (2 >= 1), so the gate holds, Fail does NOT
    raise, and the transaction completes — ``checked`` is still produced.

This exercises the Fail wiring/serde and the engine's non-triggering path without
failing the run. Fail itself yields no table, so the only produced table is the
enriched ``checked``.

The 4-row input has a KNOWN composition — 2 positive, 2 non-positive — so the
enrich column is exact and the Fail gate is comfortably satisfied (the oracle;
see functions/_harness.py).
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
    RowCountThreshold,
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
    )
except ImportError:
    from _harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
        Sentinel,
        unordered_equal,
    )

_T, _F = Sentinel.TRUE, Sentinel.FALSE

# Raw input of known composition: 2 positive, 2 non-positive (all-ok count == 2).
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3],
        "value": [10.0, 3.0, -5.0, 0.0],
    }
)

# ``checked`` after Enrich(): the verdict column appended, one UInt8 per row —
# TRUE for >0, FALSE for <=0.
_ENRICHED = _INPUT.with_columns(
    pl.Series("value_is_positive", [_T, _T, _F, _F], dtype=pl.UInt8)
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[
            Enrich(),
            # gate: require >= 1 passing row; we have 2, so this does NOT fire.
            Fail(AllOk(), threshold=RowCountThreshold(row_count=1)),
        ],
    ),
    main_tables=["checked"],
    expects=[
        Expect("checked", _ENRICHED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def flo_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def flo_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def flo_sub(c0: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0])
    return TableFrame.empty()
