#
# Copyright 2026 Tabsdata Inc.
#
"""KNOWN DIVERGENCES — a catalog of TableFrame behaviours that do NOT match polars.

Everywhere else in the suite these cases get special/restricted handling to keep
their file green (IGNORE'd, excluded, or given an expected-override). Here they are
asserted STRAIGHT against polars, so this sub-suite is EXPECTED TO FAIL: it
documents and tracks the divergences and goes green only if/when they are fixed in
tabsdatak. Run it on its own with ``tdx-xp oneshot --suite tableframe_api/failing``.

The divergences (all but the last are rooted in TableFrame carrying hidden ``$TD.*``
system columns through a whole-frame operation):

  * ``rename(<callable>)`` — the callable is applied to the system columns too,
    which then leak past ``drop_system_columns``.                (offline + live)
  * ``unique()`` / ``unique(keep="none")`` with no subset — dedup runs over the
    system columns, so no visible duplicate is ever removed.     (offline + live)
  * ``group_by(...).sum()`` — reduces the system columns; summing the string one
    raises.                                                      (offline + live)
  * ``group_by(...).min()/max()/mean()/median()`` — reduce the system columns;
    through storage one is ``list[binary]``, which those reductions can't handle,
    so the write raises. (LIVE only — offline ``from_polars`` builds reducible
    system columns, so these happen to match there.)            (live only)
  * ``t[[cols]]`` column subscription — the lazy TableFrame supports slicing only,
    so column subscription raises (polars DataFrame returns a frame). (offline + live)

Deliberately NOT cataloged here: frame ``first()`` / ``last()`` (IGNORE'd only
because eager polars ``DataFrame`` has no such method — the RESULT matches polars,
so it is not a divergence), and ``concat``'s None/empty contract (kept in tf_concat
as intended-behaviour spec-tests)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"k": ["x", "x", "y"], "v": [1, 1, 3]})
CASE = TFCase(
    inputs={"fx_in": _INPUT},
    checks=[
        Check("fx_rename_callable", lambda f, t: t.rename(lambda c: c.upper()), unordered_equal),
        Check("fx_unique_all", lambda f, t: t.unique(), unordered_equal),
        Check("fx_unique_keep_none", lambda f, t: t.unique(keep="none"), unordered_equal),
        Check("fx_gb_sum", lambda f, t: t.group_by("k").sum(), unordered_equal),
        Check("fx_gb_min", lambda f, t: t.group_by("k").min(), unordered_equal),
        Check("fx_gb_max", lambda f, t: t.group_by("k").max(), unordered_equal),
        Check("fx_gb_mean", lambda f, t: t.group_by("k").mean(), unordered_equal),
        Check("fx_gb_median", lambda f, t: t.group_by("k").median(), unordered_equal),
        Check("fx_getitem_cols", lambda f, t: t[["k", "v"]], unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["fx_in"])
def fx_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/fx_in@NEW"], output_tables=CASE.output_names)
def fx_tfr(
    t: TableFrameSpec,
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
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def fx_sub(
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
