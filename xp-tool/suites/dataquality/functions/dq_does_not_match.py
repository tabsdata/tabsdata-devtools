#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the DoesNotMatch classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of the STRING column ``value`` with ``DoesNotMatch`` —
    the complement of ``Matches``: the engine computes ``~str.contains(pattern)``,
    a regex SEARCH negated, so the verdict is "the string does NOT contain a
    substring matching the pattern". Here ``pattern=r"\\d"``, so the verdict is
    "the string contains NO digit";
  * ``Enrich()`` (no to_table) appends the verdict column ``value_does_not_match``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 6-row input mirrors dq_matches — 3 strings contain a digit (here FALSE), 2
do not (TRUE), 1 null — so the tallies are the exact complement of dq_matches on
the non-null rows. A null STRING classifies as the NULL sentinel (255), never
NAN, so the nan tally is 0 (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, DoesNotMatch, Enrich, Summary
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

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

# Regex the classifier searches for: verdict TRUE when NO digit is present.
_PATTERN = r"\d"

# Raw input of known composition: contains-digit (x3) / no-digit (x2) / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5],
        "value": ["abc123", "hello", "42", "a1b", "xyz", None],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row.
# ~str.contains -> TRUE only when no digit appears anywhere; a null string is the
# NULL sentinel (no NAN for a string dtype).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_does_not_match"),
        [_F, _T, _F, _F, _T, _NULL],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 2 digit-free (true), 3 with a digit (false), 0 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_does_not_match")],
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
        classifiers=[DoesNotMatch(["value"], pattern=_PATTERN)],
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
def dnm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def dnm_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def dnm_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
