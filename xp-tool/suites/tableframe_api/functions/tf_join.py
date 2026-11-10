#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.join — inner / left / right / full / outer / semi / anti / cross
strategies, the ``left_on`` / ``right_on`` key form, and ``suffix`` for an
overlapping column (two input tables)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_LEFT = pl.DataFrame({"id": [3, 1, 2, 9], "name": ["c", "a", "b", "z"]})
_RIGHT = pl.DataFrame({"id": [1, 2, 3], "country": ["US", "ES", "JP"]})
CASE = TFCase(
    inputs={"join_left_in": _LEFT, "join_right_in": _RIGHT},
    checks=[
        Check("join_inner", lambda f, l, r: l.join(r, on="id", how="inner"), unordered_equal),
        Check("join_left", lambda f, l, r: l.join(r, on="id", how="left"), unordered_equal),
        Check("join_right", lambda f, l, r: l.join(r, on="id", how="right"), unordered_equal),
        Check("join_full", lambda f, l, r: l.join(r, on="id", how="full"), unordered_equal),
        Check("join_semi", lambda f, l, r: l.join(r, on="id", how="semi"), unordered_equal),
        Check("join_anti", lambda f, l, r: l.join(r, on="id", how="anti"), unordered_equal),
        Check("join_cross", lambda f, l, r: l.join(r, how="cross"), unordered_equal),
        Check(
            "join_on_keys",
            lambda f, l, r: l.join(r.rename({"id": "rid"}), left_on="id", right_on="rid"),
            unordered_equal,
        ),
        Check(
            "join_suffix",
            lambda f, l, r: l.join(r.rename({"country": "name"}), on="id", suffix="_r"),
            unordered_equal,
        ),
    ],
)


@publisher(
    source=DataGenSrc(data=CASE.data), output_tables=["join_left_in", "join_right_in"]
)
def join_pub(
    left: TableFrameSpec, right: TableFrameSpec
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (left, right)


@transformer(
    input_tables=[f"{SRC}/join_left_in@NEW", f"{SRC}/join_right_in@HEAD"],
    output_tables=CASE.output_names,
)
def join_tfr(
    left_versions: TableFramesSpec, right: TableFrameSpec
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    left = concat(left_versions or [])
    return CASE.transform(left, right)


@subscriber(
    destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names]
)
def join_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
    c8: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7, c8])
    return TableFrame.empty()
