#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the Matches classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of the STRING column ``value`` with ``Matches`` — the
    verdict is whether the value matches the regex ``pattern``. The engine uses
    ``str.contains(pattern)``, i.e. a regex SEARCH (a substring match anywhere in
    the value), not a full-string anchored match. Here ``pattern=r"\\d"``, so the
    verdict is "the string contains at least one digit";
  * ``Enrich()`` (no to_table) appends the verdict column ``value_matches``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 6-row input has a KNOWN composition — 3 strings containing a digit (TRUE),
2 without (FALSE), 1 null. A null STRING classifies as the NULL sentinel (255),
never NAN, so the nan tally is 0 (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, Matches, Summary
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

# Regex the classifier searches for: "contains at least one digit".
_PATTERN = r"\d"

# Raw input of known composition: contains-digit (x3) / no-digit (x2) / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": ["abc123", "hello", "42", "a1b", "xyz", None],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row.
# str.contains is a regex SEARCH -> TRUE when a digit appears anywhere; a null
# string is the NULL sentinel (no NAN for a string dtype).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_matches"),
        [_T, _F, _T, _T, _F, _NULL],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 3 matching (true), 2 non-matching (false), 0 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_matches")],
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
        classifiers=[Matches(["value"], pattern=_PATTERN)],
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
def mt_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def mt_tfr(t: TableFrameSpec) -> TableFrameSpec:
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def mt_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
