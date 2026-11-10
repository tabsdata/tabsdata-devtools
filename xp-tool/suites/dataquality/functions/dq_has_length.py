#
# Copyright 2026 Tabsdata Inc.
#
"""DataQuality: the HasLength classifier with the Enrich + Summary operators.

A pass-through transformer carries ``on_tables=[DataQuality(...)]`` over its
output table ``checked``. The action:
  * classifies each row of the STRING column ``value`` with ``HasLength`` — the
    verdict is whether the character length is within ``[min_len, max_len]``.
    ``HasLength`` takes a length RANGE, not a single length; the engine tests
    ``len_chars().is_between(min_len, max_len, closed="both")`` (both bounds
    inclusive). Here ``min_len=2, max_len=5``;
  * ``Enrich()`` (no to_table) appends the verdict column ``value_has_length``
    to ``checked`` in place;
  * ``Summary()`` emits the derived table ``checked_dq_summary`` (one row: the
    boolean tallies for this classifier).

The 7-row input has a KNOWN composition — an interior-length string, the two
boundary lengths (2 and 5, both TRUE), one too short, one too long, an empty
string (length 0, FALSE), and one null. A null STRING classifies as the NULL
sentinel (255), never NAN — the nan branch is a no-op for non-float dtypes — so
the nan tally is 0 (the oracle; see functions/_harness.py).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.dataquality import DataQuality, Enrich, HasLength, Summary
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

# Raw input of known composition for the length range [2, 5]:
# interior (3) / lower-boundary (2) / upper-boundary (5) / too short (1) /
# too long (6) / empty (0) / null.
_INPUT = pl.DataFrame(
    {
        "id": [0, 1, 2, 3, 4, 5, 6],
        "value": ["abc", "ab", "abcde", "a", "abcdef", "", None],
    }
)

# ``checked`` after Enrich: the verdict column appended, one UInt8 per row.
# closed="both" -> lengths 2 and 5 are both TRUE; a null string is the NULL
# sentinel (no NAN for a string dtype).
_ENRICHED = _INPUT.with_columns(
    pl.Series(
        verdict("value_has_length"),
        [_T, _T, _T, _F, _F, _F, _NULL],
        dtype=pl.UInt8,
    )
)

# ``checked_dq_summary``: one row, the boolean tallies for this classifier.
# 3 in-range (true), 3 out-of-range (false), 0 nan, 1 null.
_SUMMARY = pl.DataFrame(
    {
        "dq.classifier": [verdict("value_has_length")],
        "dq.type": ["boolean"],
        "dq.true": [3],
        "dq.false": [3],
        "dq.nan": [0],
        "dq.none": [1],
    }
)

CASE = DQCase(
    inputs={"raw": _INPUT},
    action=DataQuality(
        table="checked",
        classifiers=[HasLength(["value"], min_len=2, max_len=5)],
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
def hl_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(
    input_tables=[f"{SRC}/{n}@NEW" for n in CASE.input_names],
    output_tables=CASE.main_tables,
    on_tables=[CASE.action],
)
def hl_tfr(t_versions: TableFramesSpec) -> TableFrameSpec:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(
    destination=TrashDest(),
    input_tables=[f"{OPS}/{n}" for n in CASE.output_names],
)
def hl_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
