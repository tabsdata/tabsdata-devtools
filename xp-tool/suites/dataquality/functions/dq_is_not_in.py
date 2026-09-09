#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsNotIn classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action is the complement of IsIn:
  * classifies each row of ``value`` with ``IsNotIn`` against the membership set
    ``values=[10, 20]`` — verdict TRUE when the value is NOT in the set, FALSE
    when it is, and (with a set that does NOT contain ``None``) the reserved NULL
    sentinel for a null. ``values`` is a keyword-only field: a Python list is
    coerced to a ``frozenset`` by pydantic (``ValuesSpec``).
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_not_in`` to
    ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

NULL HANDLING: a null row maps to the NULL sentinel (counted in ``dq.none``, NOT
``dq.true``) unless ``None`` is added to ``values``, in which case a null would be
treated as a member and IsNotIn would return FALSE. This test keeps ``None`` OUT
of the set to exercise the default null-is-not-a-member behavior.

The 6-row Int64 input has a KNOWN composition — 3 in-set, 2 out-of-set, 1 null —
so the enrich column and the summary tallies are exact and independent of the
engine (the oracle; see functions/_harness.py). Relative to IsIn the true/false
verdicts are swapped: the 2 out-of-set rows are TRUE and the 3 in-set rows FALSE.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsNotIn, Summary
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
    )

_T, _F, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NULL

# Raw input of known composition: in-set (10/20) / out-of-set (30/40) / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": [10, 20, 30, 40, None, 20],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for a non-member of {10, 20}, FALSE for a member, NULL sentinel for a null.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        "value_is_not_in",
        [_F, _F, _T, _T, _NULL, _F],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 2 out-of-set (true), 3 in-set (false), 0 nan (integer column has no NaN),
# 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": ["value_is_not_in"],
        "dq.type": ["boolean"],
        "dq.true": [2],
        "dq.false": [3],
        "dq.nan": [0],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[IsNotIn(["value"], values=[10, 20])],
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
def ini_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def ini_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def ini_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
