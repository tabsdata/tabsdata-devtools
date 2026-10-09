#
# Copyright 2026 Tabsdata Inc.
#

"""dq_scale_samples — ``scale_samples_spec.md``'s columns, a hundred triggers of them,
with boolean classifiers and scale categorizers, for data-quality summaries and
their trends.

``scales_tick`` emits one row per trigger (a ``DataGenSrc`` with ``chunk_size=1``
over 100 rows); every other function is a ``DataGenSrc`` publisher triggered by
the tick, five tables each, every table a ``Data`` of 100 x 1000 rows with
``chunk_size=1000``: a trigger, the next 1000 rows. What the rows hold, which
table carries what and why is ``scale_plan``'s docstring.

A table's data-quality action rides on its publisher (``on_tables``):

- ``bool`` and ``all``: per column ``IsNotNull``, ``IsBetween`` over the column's
  range and, for a float, ``IsNotNan`` -- each failing the defects its trigger
  made, a share the profile moves every run -- and ``Summary(trend=SummaryTrend())``,
  whose trend folds them run by run.
- ``scale`` and ``all``: per column the ``ScaleCategorizer`` its relation calls for
  (``scale_plan.scale``) -- ``IdentityScale``, ``LinearScale``, ``MonomialScale``,
  ``LogarithmicScale``, ``ExponentialScale`` -- and a ``Summary(trend=None)``: a
  trend folds boolean classifiers only, and is on unless opted out of.

A scale's range is its column's, computed here by the same expression that makes the
values, so an end value lands in an end bin rather than a bin past it.
"""

from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TablesTrigger, publisher
from tabsdatak.conn.dev import Data, DataGenSrc
from tabsdatak.dataquality import (
    DataQuality,
    ExponentialScale,
    IdentityScale,
    IsBetween,
    IsNotNan,
    IsNotNull,
    LinearScale,
    LogarithmicScale,
    MonomialScale,
    ScaleCategorizer,
    Summary,
    SummaryTrend,
)

try:
    from . import scale_plan as plan
except ImportError:
    import scale_plan as plan

# What a five-table publisher returns.
_FIVE = tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]

_DTYPES = {"int32": pl.Int32, "int64": pl.Int64, "float64": pl.Float64}
_TRIGGERED = TablesTrigger(tables=[f"{plan.COLLECTION}/{plan.TICK}"])


def _points(col: plan.Column, k: pl.Expr) -> pl.Expr:
    """The column's value at point `k`, the doc's formula."""
    kf = k.cast(pl.Float64)
    match col.relation:
        case "identity":
            v = kf + col.start
        case "linear":
            v = kf * col.step + col.start
        case "monomial":
            v = (kf * ((col.x1 - col.x0) / (col.n - 1)) + col.x0).pow(col.power)
        case "logarithmic":
            low, high = col.base**col.start, col.base**col.end
            v = (kf * ((high - low) / (col.n - 1)) + low).log(col.base)
        case _:
            v = pl.lit(col.base, pl.Float64).pow(kf) * col.start
    return v if col.floating else v.round(0).cast(_DTYPES[col.dtype])


def _range(col: plan.Column) -> tuple:
    """The column's min and max, as the values are made."""
    every = pl.DataFrame({"k": list(range(col.n))}).select(_points(col, pl.col("k")).alias("v"))
    return every["v"].min(), every["v"].max()


_RANGES = {name: _range(col) for name, col in plan.COLUMNS.items()}


def _per_trigger(values: list) -> pl.Expr:
    """A value per trigger, looked up by the row's trigger."""
    return pl.lit(pl.Series(values)).gather(pl.col("trigger"))


def _column(table: plan.Table, col: plan.Column) -> pl.Expr:
    triggers = range(plan.TRIGGERS)
    gammas = [plan.gamma(table.name, t) if table.profile else 1.0 for t in triggers]
    k = (
        (pl.col("row").cast(pl.Float64) / plan.ROWS).pow(_per_trigger(gammas)) * col.n
    ).floor().cast(pl.Int64).clip(0, col.n - 1)
    value = _points(col, k)
    if table.profile is None:
        return value.alias(col.name)
    # A bijection of the rows, its offset moving every trigger: the first `null`
    # ranks are null, the next `out_of_range` past the range (the first half below),
    # then `nan` NaN -- exactly the counts the plan says.
    stride = 1 + 2 * (plan.seed(table.name, col.name) % 250)  # odd, so a unit mod 1000
    stride += 2 if stride % 5 == 0 else 0
    offsets = [plan.seed(table.name, col.name, t) % plan.ROWS for t in triggers]
    rank = (pl.col("row") * stride + _per_trigger(offsets)) % plan.ROWS
    cuts = [plan.defects(table.profile, col, t) for t in triggers]
    nulls = _per_trigger([d.null for d in cuts])
    oor = _per_trigger([d.out_of_range for d in cuts])
    nans = _per_trigger([d.nan for d in cuts])
    below, above = col.out_of_range()
    dtype = _DTYPES[col.dtype]
    out = (
        pl.when(rank < nulls)
        .then(pl.lit(None, dtype))
        .when(rank < nulls + oor // 2)
        .then(pl.lit(below, dtype))
        .when(rank < nulls + oor)
        .then(pl.lit(above, dtype))
    )
    if col.floating:
        out = out.when(rank < nulls + oor + nans).then(pl.lit(float("nan"), dtype))
    return out.otherwise(value).alias(col.name)


def frame(table: plan.Table) -> pl.DataFrame:
    """Every trigger's rows of `table`, in trigger order."""
    rows = pl.DataFrame(
        {
            "trigger": pl.Series([t for t in range(plan.TRIGGERS) for _ in range(plan.ROWS)], dtype=pl.Int32),
            "row": pl.Series(list(range(plan.ROWS)) * plan.TRIGGERS, dtype=pl.Int32),
        }
    )
    return rows.with_columns(_column(table, plan.COLUMNS[c]) for c in table.columns)


def _scale(spec: plan.ScaleSpec):
    match spec.kind:
        case "IdentityScale":
            return IdentityScale(int(spec.min_val), int(spec.max_val), use_bin_zero=spec.use_bin_zero)
        case "LinearScale":
            return LinearScale(spec.min_val, spec.max_val, bins=spec.bins)
        case "MonomialScale":
            return MonomialScale(spec.min_val, spec.max_val, power=spec.power, bins=spec.bins)
        case "LogarithmicScale":
            return LogarithmicScale(spec.min_val, spec.max_val, base=spec.base, bins=spec.bins)
        case "ExponentialScale":
            return ExponentialScale(spec.min_val, spec.max_val, base=spec.base, bins=spec.bins)
    raise ValueError(spec.kind)


def quality(table: plan.Table) -> DataQuality | None:
    if table.dq == "plain":
        return None
    classifiers = []
    if table.booleans:
        classifiers.append(IsNotNull(list(table.columns)))
        for name in table.columns:
            lo, hi = _RANGES[name]
            classifiers.append(IsBetween([name], min_val=lo, max_val=hi))
        floats = [c for c in table.columns if plan.COLUMNS[c].floating]
        if floats:
            classifiers.append(IsNotNan(floats))
    if table.categorizers:
        for name in table.columns:
            lo, hi = _RANGES[name]
            spec = plan.scale(plan.COLUMNS[name], table.bins, lo, hi)
            classifiers.append(ScaleCategorizer([name], scale=_scale(spec)))
    # Summary's trend is on by default; it folds booleans only, so a scale table opts out.
    summary = Summary(trend=SummaryTrend() if table.booleans else None)
    return DataQuality(table=table.name, classifiers=classifiers, operators=[summary])


def _source(function: str) -> DataGenSrc:
    return DataGenSrc(data=[Data(frame(t), chunk_size=plan.ROWS) for t in plan.FUNCTIONS[function]])


def _outputs(function: str) -> list[str]:
    return [t.name for t in plan.FUNCTIONS[function]]


def _actions(function: str) -> list[DataQuality] | None:
    found = [q for t in plan.FUNCTIONS[function] if (q := quality(t)) is not None]
    return found or None


def _args(function: str) -> dict:
    return {
        "source": _source(function),
        "output_tables": _outputs(function),
        "trigger_by": _TRIGGERED,
        "on_tables": _actions(function),
    }


@publisher(
    source=DataGenSrc(
        data=[Data(pl.DataFrame({"trigger": pl.Series(range(plan.TRIGGERS), dtype=pl.Int32)}), chunk_size=1)]
    ),
    output_tables=[plan.TICK],
)
def scales_tick(tick: TableFrameSpec) -> TableFrameSpec:
    # One row a trigger: its number. After the hundredth the slot is None.
    return tick


# Five tables each; the bodies pass them through -- the data is the source's.


@publisher(**_args("scales_identity"))
def scales_identity(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("scales_linear"))
def scales_linear(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("scales_monomial"))
def scales_monomial(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("scales_logarithmic"))
def scales_logarithmic(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("scales_exponential"))
def scales_exponential(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("scales_mixed"))
def scales_mixed(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    # One column per relation family a table: every table carries all five scale types.
    return a, b, c, d, e


@publisher(**_args("scales_samples"))
def scales_samples(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("trend_improving"))
def trend_improving(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("trend_degrading"))
def trend_degrading(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e


@publisher(**_args("trend_seasonal"))
def trend_seasonal(a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, d: TableFrameSpec, e: TableFrameSpec) -> _FIVE:
    return a, b, c, d, e
