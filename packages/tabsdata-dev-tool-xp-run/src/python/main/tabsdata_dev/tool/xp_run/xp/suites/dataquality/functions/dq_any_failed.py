#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: Filter(AnyFailed(), ...) splits failed-vs-clean rows.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action classifies each row of ``value`` with
``IsPositive`` and then applies a single ``Filter`` whose criteria is
``AnyFailed`` — the complement of ``AllOk``.

FILTER DIRECTION (from engine.filter): the criteria expression is evaluated per
row; the rows for which it is TRUE STAY in the target table (``checked``,
rewritten in place), and the rows for which it is FALSE are redirected to
``to_table``. So with ``AnyFailed`` the target ``checked`` keeps the rows that
FAILED at least one classifier, and the rows that passed every classifier are
sent out — hence the redirect table is named ``clean`` (naming it "failed" would
be backwards: that table receives the rows with NO failure).

ANYFAILED SEMANTICS (from PolarsCriteriaProvider.any_failed): a row matches when
any classifier verdict is in a sentinel set built as ``[FALSE]`` plus ``NULL``
unless ``none_is_ok`` and plus ``NAN`` unless ``nan_is_ok``. Here we set
``none_is_ok=True`` and leave ``nan_is_ok=False``, so the set is ``{FALSE, NAN}``:
a FALSE verdict is a failure (stays in ``checked``), a NAN verdict is a failure
(``nan_is_ok`` off, stays in ``checked``), a NULL verdict is treated as OK
(``none_is_ok`` on, so NOT a failure -> redirected to ``clean``), and a TRUE
verdict passes (redirected to ``clean``). This exercises both flags: the null row
and the nan row take OPPOSITE branches purely because of them.

``include_quality_columns`` defaults to ``"none"``, so neither output carries the
verdict column — both keep only the original user columns.

The 7-row input has a KNOWN composition — 2 positive (TRUE), 3 non-positive
(FALSE), 1 null (NULL), 1 nan (NAN) — so the split is exact and independent of the
engine (the oracle; see functions/_harness.py).
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

# Raw input of known composition: positive / negative / zero / null / nan.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": [10.0, -5.0, 0.0, None, 3.0, -1.0, float("nan")],
    }
)

# Rows that MATCH AnyFailed (verdict in {FALSE, NAN}) stay in ``checked``:
#   -5.0 / 0.0 / -1.0 -> FALSE ; nan -> NAN (nan_is_ok=False keeps it a failure).
_CHECKED = pl.DataFrame(
    {
        "id": [1, 2, 5, 6],
        "value": [-5.0, 0.0, -1.0, float("nan")],
    }
)

# Rows that do NOT match AnyFailed are redirected to ``clean``:
#   10.0 / 3.0 -> TRUE (passed) ; null -> treated OK (none_is_ok=True).
_CLEAN = pl.DataFrame(
    {
        "id": [0, 3, 4],
        "value": [10.0, None, 3.0],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsPositive(["value"])],
        operators=[
            Filter(
                AnyFailed(none_is_ok=True, nan_is_ok=False),
                to_table="clean",
            )
        ],
    ),
    main_tables=["checked"],
    expects=[
        # ``checked`` keeps the rows that failed at least one classifier.
        Expect("checked", _CHECKED, unordered_equal),
        # the rows with no failure landed in the redirect table.
        Expect("clean", _CLEAN, unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=CASE.input_names)
def anf_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def anf_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def anf_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
