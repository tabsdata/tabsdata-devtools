#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Summary(table=...) lands the summary in a custom-named table.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then:
  * ``Summary(table="my_summary")`` — the boolean tallies are written to the
    custom-named derived table ``my_summary`` instead of the default
    ``checked_dq_summary``.

No enrich/filter operator acts on ``checked`` here, so the target table is
produced UNCHANGED (the raw input). The run therefore yields two tables:
``checked`` (untouched) and ``my_summary`` (the one summary row).

The 7-row input has a KNOWN composition — 2 positive, 3 non-positive, 1 null, 1
nan — so the summary tallies are exact and independent of the engine (the oracle;
see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, IsPositive, Summary
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import (
        OPS,
        SRC,
        DQCase,
        Expect,
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
        subset_equal,
        unordered_equal,
        verdict,
    )

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# ``my_summary``: one row, the boolean tallies for this classifier.
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

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[Summary(table="my_summary")],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` is untouched — same rows/columns as the raw input.
        Expect("checked", _INPUT, unordered_equal),
        # the summary landed in the custom-named table, not ``checked_dq_summary``.
        Expect(
            "my_summary",
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
def smc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def smc_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def smc_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
