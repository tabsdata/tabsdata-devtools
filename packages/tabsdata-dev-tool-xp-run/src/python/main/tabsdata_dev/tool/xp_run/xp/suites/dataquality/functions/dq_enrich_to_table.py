#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Enrich(to_table=...) writes the verdicts to a NEW derived table.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Enrich(to_table="checked_enriched")`` — because a ``to_table`` is given, the
    verdict column ``value_is_positive`` is written to a NEW derived table
    ``checked_enriched`` (input columns + the verdict), and the target ``checked``
    is left UNCHANGED (no in-place rewrite).

So the run produces two tables: ``checked`` (the raw input, untouched) and
``checked_enriched`` (input + verdict). Contrast ``dq_is_positive`` where
``Enrich()`` with no ``to_table`` rewrites ``checked`` in place.

The 7-row input has a KNOWN composition — 2 positive, 3 non-positive, 1 null, 1
nan — so the enrich column is exact and independent of the engine (the oracle;
see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsPositive
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

_T, _F, _NAN, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NAN, Sentinel.NULL

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# ``checked_enriched``: the input with the verdict column appended, one UInt8 per
# row — TRUE for >0, FALSE for <=0, and the reserved NULL / NAN sentinels.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_is_positive",
        [_T, _F, _F, _NULL, _T, _F, _NAN],
        dtype=pl.UInt8,
    )
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[Enrich(to_table="checked_enriched")],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` is untouched — same rows/columns as the raw input.
        Expect("checked", _INPUT, unordered_equal),
        # ``checked_enriched`` is the input plus the verdict column.
        Expect("checked_enriched", _ENRICHED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def ent_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def ent_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def ent_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
