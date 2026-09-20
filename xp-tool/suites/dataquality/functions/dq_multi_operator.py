#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: ONE action carrying a CHAIN of operators -> four tables at once.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The single action classifies ``value`` with
``IsPositive`` once and then runs THREE operators together, each contributing a
table to the same run:
  * ``Enrich(to_table="checked_enriched")`` — writes the input plus the verdict
    column ``value_is_positive`` to a NEW derived table ``checked_enriched``
    (all 7 rows preserved);
  * ``Summary()`` — emits ``checked_dq_summary`` (the boolean tallies row);
  * ``Filter(AnyFailed(), to_table="rejected")`` — REMOVES the failing rows
    (``value_is_positive`` is not TRUE) from the target ``checked``, rewritten in
    place to only the passing rows, and redirects them to the derived table
    ``rejected``. ``include_quality_columns``
    defaults to ``"none"`` so ``checked`` and ``rejected`` carry only the user
    columns.

HOW Enrich AND Filter COMPOSE ON THE TARGET
    Both an in-place ``Enrich()`` (no ``to_table``) and ``Filter()`` are
    "target-overriding" operators. The engine forbids TWO overriding operators on
    the same table in one action (raises DQPE_15 "overridden multiple times"), so
    ``operators=[Enrich(), Summary(), Filter(..., to_table="rejected")]`` is
    REJECTED. To chain both, ``Enrich`` is routed to its own ``to_table``
    (non-overriding), leaving ``Filter`` as the sole rewriter of ``checked``. The
    verdict column therefore survives in ``checked_enriched``, while ``checked``
    itself holds the filtered (passing) rows.

The 7-row input has a KNOWN composition — 2 positive (kept), 3 non-positive + 1
null + 1 nan (rejected) — so every one of the four tables is exact and
independent of the engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import (
    AnyFailed,
    DataQuality,
    Enrich,
    Filter,
    IsPositive,
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

_T, _F, _NAN, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NAN, Sentinel.NULL

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# ``checked``: Filter rewrites it to ONLY the passing rows (value_is_positive is
# TRUE); ``include_quality_columns="none"`` -> user columns only.
_CHECKED = pl.DataFrame(
    {
        "id": [0, 4],
        "value": [10.0, 3.0],
    }
)

# ``checked_enriched``: the full input plus the verdict column (Enrich to_table).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_positive"),
        [_T, _F, _F, _NULL, _T, _F, _NAN],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one boolean row for the single classifier.
# 2 positive (true), 3 non-positive (false), 1 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_positive")],
        "dq.type": ["boolean"],
        "dq.true": [2],
        "dq.false": [3],
        "dq.nan": [1],
        "dq.none": [1],
    }
)

# ``rejected``: the failing rows redirected by Filter (user columns only).
_REJECTED = pl.DataFrame(
    {
        "id": [1, 2, 3, 5, 6],
        "value": [-5.0, 0.0, None, -1.0, float("nan")],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[
            Enrich(to_table="checked_enriched"),
            Summary(),
            Filter(AnyFailed(), to_table="rejected"),
        ],
    ),
    main_tables=["checked"],
    expects=[
        Expect("checked", _CHECKED, unordered_equal),
        Expect("checked_enriched", _ENRICHED, unordered_equal),
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
        Expect("rejected", _REJECTED, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def mop_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def mop_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def mop_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
