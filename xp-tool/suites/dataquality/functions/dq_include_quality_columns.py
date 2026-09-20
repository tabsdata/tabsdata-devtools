#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Filter(..., include_quality_columns="all") explains rejected rows.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies ``value`` with ``IsPositive`` and
then:
  * ``Filter(AnyFailed(), to_table="rejected", include_quality_columns="all")`` —
    splits rows as ``dq_filter`` does (passing rows stay in ``checked``, failing
    rows go to ``rejected``), but ``include_quality_columns="all"`` CARRIES the
    classifier VERDICT columns into ``rejected``. So ``rejected`` is the user
    columns (``id``, ``value``) followed by the verdict column ``value_is_positive``
    (UInt8), in that order, while the target ``checked`` stays user columns only:
    ``include_quality_columns`` shapes ``to_table`` alone (the engine rejects any
    value but ``"none"`` when ``to_table`` is not given).

CONTRAST with ``dq_filter`` (default ``"none"``) whose ``rejected`` is
``id``/``value`` only.

WHICH COLUMNS "all" vs "criteria" ADD
    ``"all"`` appends every produced verdict column (here just ``value_is_positive``).
    ``"criteria"`` appends only the verdict columns the criteria consults — for an
    untagged ``AnyFailed`` that is ALL of them, so with a single untagged classifier
    ``"all"`` and ``"criteria"`` are identical; they diverge only when tags scope
    the criteria to a subset of classifiers. This test uses ``"all"``.

The 7-row input has a KNOWN composition — 2 positive (kept), 5 not-positive
(rejected) — so both output frames, ``rejected``'s verdict column included, are
exact and independent of the engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import AnyFailed, DataQuality, Filter, IsPositive
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

_T, _F, _NAN, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NAN, Sentinel.NULL

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# ``checked`` — passing rows (value > 0), user columns only: the verdict column
# travels with the rejected rows, never into the target.
_KEPT = pl.DataFrame(
    {
        "id": [0, 4],
        "value": [10.0, 3.0],
    }
)

# ``rejected`` — the not-passing rows, verdict column carried through: false for
# <=0, and the reserved NULL / NAN sentinels for the null / nan rows.
_REJECTED = pl.DataFrame(
    {
        "id": [1, 2, 3, 5, 6],
        "value": [-5.0, 0.0, None, -1.0, float("nan")],
    }
).with_columns(
    pl.Series(verdict("value_is_positive"), [_F, _F, _NULL, _F, _NAN], dtype=pl.UInt8)
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[
            Filter(
                AnyFailed(),
                to_table="rejected",
                include_quality_columns="all",
            )
        ],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` = passing rows, user columns only (same as dq_filter).
        Expect("checked", _KEPT, unordered_equal),
        # ``rejected`` = failing rows, WITH the verdict column.
        Expect("rejected", _REJECTED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def iqc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def iqc_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def iqc_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
