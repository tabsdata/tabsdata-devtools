#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the IsIn classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of ``value`` with ``IsIn`` against the membership set
    ``values=[10, 20]`` — verdict TRUE when the value is in the set, FALSE when it
    is not, and (with a set that does NOT contain ``None``) the reserved NULL
    sentinel for a null. ``values`` is a keyword-only field: a Python list is
    coerced to a ``frozenset`` by pydantic (``ValuesSpec``).
  * ``Enrich()`` (no to_table) appends the verdict column ``value_is_in`` to
    ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

NULL HANDLING: a null row maps to the NULL sentinel (counted in ``dq.none``, NOT
``dq.false``) unless ``None`` is added to ``values``, in which case a null would
be treated as a member (verdict TRUE). This test keeps ``None`` OUT of the set to
exercise the default null-is-not-a-member behavior.

The 6-row Int64 input has a KNOWN composition — 3 in-set, 2 out-of-set, 1 null —
so the enrich column and the summary tallies are exact and independent of the
engine (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, IsIn, Summary
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

_T, _F, _NULL = Sentinel.TRUE, Sentinel.FALSE, Sentinel.NULL

# Raw input of known composition: in-set (10/20) / out-of-set (30/40) / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": [10, 20, 30, 40, None, 20],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row —
# TRUE for a member of {10, 20}, FALSE otherwise, NULL sentinel for a null.
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_is_in"),
        [_T, _T, _F, _F, _NULL, _T],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 3 in-set (true), 2 out-of-set (false), 0 nan (integer column has no NaN),
# 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_is_in")],
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
        classifiers=[IsIn(["value"], values=[10, 20])],
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
def iin_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def iin_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def iin_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
