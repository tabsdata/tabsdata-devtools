#
# Copyright 2026 Tabsdata Inc.
#

"""scale_plan — the plan of the ``datagen_scale_samples`` suite, standard library only:
the functions build their frames and data-quality actions from it, and the check
reads what to expect from it.

The columns are ``scale_samples_spec.md``'s 22: five relation families -- identity,
linear, monomial, logarithmic, exponential -- each column a function of its own point
index ``k = 0 .. N-1``, with the doc's min, max, N and power or base (``COLUMNS``).

Each of the 100 triggers emits ``ROWS`` rows per table. Row ``i`` of trigger ``t``
takes point ``k = floor(N * (i / ROWS) ** gamma)``: at ``gamma == 1`` that is the doc's
table, every point ``ROWS / N`` times, and a table's ``gamma`` sways between 1/2 and 2
over the triggers (``gamma``), so which points a trigger holds, and every histogram,
moves. Then, per classified column, a count of rows the table's profile sets for the
trigger (``defects``) is made null, NaN (a float column) or out of range -- half below
the column's minimum, half above its maximum, by a tenth of its span. A table's profile
is smooth -- improving, degrading, seasonal -- and some columns in every family follow
a jumpy one of their own -- volatile, up and down by 57 rows or more a run, or spiky,
low with a spike every ninth run (``COLUMN_PROFILES``). Every count changes by at
least one row from one trigger to the next, so every pass rate and every histogram
moves on every run, and a scale over the column's range always sees both ends.

Ten functions emit five tables each (``TABLES``): one per relation family, each table
its family's columns; ``scales_mixed``, five tables of one column per family, so each
carries categorizers of all five scale types; ``scales_samples``, the doc's whole
table five times; and one per profile, a table per family. A table's ``dq`` is
``plain`` (no data quality), ``bool`` (boolean classifiers), ``scale``
(``ScaleCategorizer``) or ``all`` (both); its ``bins`` is ``fine`` or ``coarse``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TRIGGERS = 100
ROWS = 1000
COLLECTION = "dq_scales"
TICK = "tick"


@dataclass(frozen=True)
class Column:
    """A column of the doc: ``relation`` and its parameters, ``n`` points.

    identity     ``start + k``
    linear       ``start + step * k``
    monomial     ``x ** power``, ``x`` evenly from ``x0`` to ``x1``
    logarithmic  ``log_base(x)``, ``x`` evenly from ``base ** start`` to ``base ** end``
    exponential  ``start * base ** k``
    """

    name: str
    relation: str
    n: int
    dtype: str  # "int32", "int64" or "float64", the doc's DDL
    start: float = 0.0
    step: float = 0.0
    end: float = 0.0
    x0: float = 0.0
    x1: float = 0.0
    power: float = 1.0
    base: float = math.e

    def value(self, k: int) -> float:
        match self.relation:
            case "identity":
                return self.start + k
            case "linear":
                return self.start + self.step * k
            case "monomial":
                x = self.x0 + (self.x1 - self.x0) * k / (self.n - 1)
                return x**self.power
            case "logarithmic":
                low, high = self.base**self.start, self.base**self.end
                return math.log(low + (high - low) * k / (self.n - 1)) / math.log(self.base)
            case "exponential":
                return self.start * self.base**k
        raise ValueError(self.relation)

    def typed(self, v: float) -> float | int:
        return v if self.dtype == "float64" else int(round(v))

    @property
    def low(self) -> float | int:
        return self.typed(min(self.value(0), self.value(self.n - 1)))

    @property
    def high(self) -> float | int:
        return self.typed(max(self.value(0), self.value(self.n - 1)))

    @property
    def floating(self) -> bool:
        return self.dtype == "float64"

    def out_of_range(self) -> tuple[float | int, float | int]:
        """A value below the range and one above it, a tenth of the span past."""
        past = (self.high - self.low) / 10
        return self.typed(self.low - past), self.typed(self.high + past)


E = math.e
_COLUMNS = [
    Column("id_seq", "identity", 1000, "int32", start=1),
    Column("id_zero", "identity", 250, "int32", start=0),
    Column("id_neg", "identity", 40, "int32", start=-20),
    Column("lin_tenths", "linear", 1000, "float64", start=0, step=0.1),
    Column("lin_halves", "linear", 200, "float64", start=-50, step=0.5),
    Column("lin_desc", "linear", 100, "int32", start=1000, step=-10),
    Column("lin_fahr", "linear", 125, "float64", start=32, step=1.8),
    Column("lin_coarse", "linear", 5, "int32", start=100, step=100),
    Column("pow_sq", "monomial", 100, "int32", x0=0, x1=99, power=2),
    Column("pow_cube", "monomial", 25, "float64", x0=-10, x1=10, power=3),
    Column("pow_sqrt", "monomial", 200, "float64", x0=0, x1=10000, power=0.5),
    Column("pow_inv", "monomial", 125, "float64", x0=100, x1=1, power=-1),
    Column("pow_kepler", "monomial", 40, "float64", x0=1, x1=100, power=1.5),
    Column("log_10", "logarithmic", 100, "float64", start=0, end=6, base=10),
    Column("log_2", "logarithmic", 1000, "float64", start=0, end=10, base=2),
    Column("log_e", "logarithmic", 50, "float64", start=1, end=5, base=E),
    Column("log_1_5", "logarithmic", 25, "float64", start=-2, end=3, base=1.5),
    Column("exp_double", "exponential", 40, "int64", start=1, base=2),
    Column("exp_interest", "exponential", 50, "float64", start=1000, base=1.07),
    Column("exp_halflife", "exponential", 20, "float64", start=1_000_000, base=0.5),
    Column("exp_e", "exponential", 25, "float64", start=0.001, base=E),
    Column("exp_decade", "exponential", 8, "int64", start=1, base=10),
]
COLUMNS: dict[str, Column] = {c.name: c for c in _COLUMNS}
FAMILIES = ["identity", "linear", "monomial", "logarithmic", "exponential"]
FAMILY_COLUMNS = {f: [c.name for c in _COLUMNS if c.relation == f] for f in FAMILIES}


# --- profiles: the defects per column, per trigger ------------------------------


def _triangle(t: int) -> int:
    """20 at 0, 0 at 20, 20 at 40, ...: one step a trigger, turning on a trigger."""
    return abs(t % 40 - 20)


_GOLDEN = (5**0.5 - 1) / 2

PROFILES = {
    # Better every run, worse every run, and better then worse twice and a half.
    "improving": lambda t: 100 - t,
    "degrading": lambda t: 1 + t,
    "seasonal": lambda t: 10 + 3 * _triangle(t),
    # Up and down every run: a golden-ratio step around 5-155, so one run is 57 rows
    # or more from the last, the other way about as often.
    "volatile": lambda t: 5 + int(150 * ((0.137 + t * _GOLDEN) % 1.0)),
    # Low and jittering, 10 or 13, with a spike of 120 more every ninth run.
    "spiky": lambda t: 10 + 3 * (t % 2) + (120 if t % 9 == 4 else 0),
}
# Columns whose defects follow a profile of their own, whatever table they are in
# (one with a profile: the reference stays clean) -- some in every family, so tables
# have smooth and jumpy pass rates side by side.
COLUMN_PROFILES = {
    "id_neg": "spiky",
    "lin_halves": "volatile",
    "lin_fahr": "spiky",
    "pow_sqrt": "volatile",
    "pow_kepler": "spiky",
    "log_2": "spiky",
    "log_e": "volatile",
    "exp_interest": "volatile",
    "exp_e": "spiky",
}


@dataclass(frozen=True)
class Defects:
    null: int
    out_of_range: int
    nan: int  # 0 for a column with no NaN


def defects(profile: str | None, column: Column, t: int) -> Defects:
    """The rows of a column trigger `t` makes null, out of range and NaN: the
    profile's count -- the column's own, else the table's `profile` -- plus 5 and 10,
    so each changes when the profile does."""
    if profile is None:
        return Defects(0, 0, 0)
    p = PROFILES[COLUMN_PROFILES.get(column.name, profile)](t)
    return Defects(p, p + 5, p + 10 if column.floating else 0)


def gamma(table: str, t: int) -> float:
    """The exponent trigger `t` draws `table`'s points with: 1 at trigger 0 (the
    doc's table), swaying between 1/2 and 2 over a period of the table's own."""
    period = 25 + _stable(table) % 26
    return 2 ** math.sin(2 * math.pi * t / period)


def _stable(text: str) -> int:
    # A hash that is the same in every process, unlike hash().
    h = 0
    for ch in text.encode():
        h = (h * 131 + ch) % 2**31
    return h


def seed(*parts: object) -> int:
    return _stable("/".join(map(str, parts)))


# --- scales ---------------------------------------------------------------------


@dataclass(frozen=True)
class ScaleSpec:
    """A ``ScaleCategorizer``'s scale: ``kind`` is the tabsdatak class name."""

    kind: str
    min_val: float | int
    max_val: float | int
    bins: int | None = None
    power: float | None = None
    base: float | None = None
    use_bin_zero: bool = False


def scale(column: Column, bins: str = "fine", lo=None, hi=None) -> ScaleSpec:
    """The scale a column's relation calls for, over the column's range (`lo`,
    `hi`: as the values were made; the formula's, else).

    - identity: ``IdentityScale`` with ``use_bin_zero`` (the engine gives every
      integer from min to max inclusive a bin of its own only with it); a span over
      100 does not fit 100 bins, so ``id_zero`` is binned 0-99 and overflows above,
      and ``id_seq`` takes a ``LinearScale``. Coarse: the first 4 integers.
    - monomial: ``MonomialScale`` with the column's power, its bins equally wide in
      ``x``; ``pow_inv``'s power, -1, is not one it takes (power > 0), so it is binned
      geometrically, an ``ExponentialScale``.
    - logarithmic: ``LogarithmicScale`` with the column's base, its bins equally wide
      in ``x``.
    - exponential: ``ExponentialScale``, its bins geometric between min and max.
    """
    fine = bins == "fine"
    n = 10 if fine else 4
    lo = column.low if lo is None else lo
    hi = column.high if hi is None else hi
    if column.relation == "identity":
        if column.name == "id_seq":
            return ScaleSpec("LinearScale", lo, hi, bins=100 if fine else 4)
        top = min(hi, lo + 99) if fine else lo + 3
        return ScaleSpec("IdentityScale", lo, top, use_bin_zero=True)
    if column.relation == "linear":
        if column.name == "lin_coarse":
            n = 5 if fine else 2
        return ScaleSpec("LinearScale", lo, hi, bins=n)
    if column.relation == "monomial":
        if column.power <= 0:
            return ScaleSpec("ExponentialScale", float(lo), float(hi), bins=n, base=10.0)
        return ScaleSpec("MonomialScale", float(lo), float(hi), bins=n, power=float(column.power))
    if column.relation == "logarithmic":
        return ScaleSpec("LogarithmicScale", float(lo), float(hi), bins=n, base=float(column.base))
    if column.name == "exp_decade" and fine:
        n = 7  # a bin per decade
    return ScaleSpec("ExponentialScale", float(lo), float(hi), bins=n, base=float(column.base))


# --- tables and functions -------------------------------------------------------


@dataclass(frozen=True)
class Table:
    name: str
    function: str
    columns: tuple[str, ...]
    dq: str  # plain, bool, scale, all
    profile: str | None  # None: no defects (and gamma 1: the doc's table)
    bins: str = "fine"

    @property
    def booleans(self) -> bool:
        return self.dq in ("bool", "all")

    @property
    def categorizers(self) -> bool:
        return self.dq in ("scale", "all")

    def classifiers(self) -> list[str]:
        """The summary's ``dq.classifier`` names this table's action makes."""
        out = []
        for name in self.columns:
            if self.booleans:
                out += [f"@td.dq.{name}_is_not_null", f"@td.dq.{name}_is_between"]
                if COLUMNS[name].floating:
                    out.append(f"@td.dq.{name}_is_not_nan")
            if self.categorizers:
                out.append(f"@td.dq.{name}_category")
        return out


_ROTATION = list(PROFILES)


def _family_tables() -> list[Table]:
    out = []
    for i, family in enumerate(FAMILIES):
        cols = tuple(FAMILY_COLUMNS[family])
        fn = f"scales_{family}"
        variants = [("plain", "fine"), ("bool", "fine"), ("scale", "fine"), ("all", "fine"), ("all", "coarse")]
        for j, (dq, bins) in enumerate(variants):
            name = f"{family}_{dq}" + ("_coarse" if bins == "coarse" else "")
            out.append(Table(name, fn, cols, dq, _ROTATION[(i + j) % 3], bins))
    return out


_MIXED = [
    ("id_neg", "lin_tenths", "pow_sq", "log_10", "exp_double"),
    ("id_zero", "lin_halves", "pow_sqrt", "log_2", "exp_interest"),
    ("id_neg", "lin_desc", "pow_kepler", "log_e", "exp_halflife"),
    ("id_zero", "lin_fahr", "pow_cube", "log_1_5", "exp_e"),
    ("id_neg", "lin_coarse", "pow_kepler", "log_10", "exp_decade"),
]


def _mixed_tables() -> list[Table]:
    dqs = ["scale", "scale", "scale", "all", "all"]
    return [
        Table(f"mixed_{dq}_{i + 1}", "scales_mixed", cols, dq, _ROTATION[i % 3])
        for i, (cols, dq) in enumerate(zip(_MIXED, dqs))
    ]


def _sample_tables() -> list[Table]:
    every = tuple(COLUMNS)
    return [
        Table("samples_reference", "scales_samples", every, "plain", None),
        Table("samples_bool", "scales_samples", every, "bool", "improving"),
        Table("samples_scale", "scales_samples", every, "scale", "seasonal"),
        Table("samples_all", "scales_samples", every, "all", "degrading"),
        Table("samples_all_coarse", "scales_samples", every, "all", "seasonal", "coarse"),
    ]


def _profile_tables() -> list[Table]:
    rotations = {
        "improving": ["plain", "bool", "scale", "all", "all"],
        "degrading": ["bool", "scale", "all", "plain", "all"],
        "seasonal": ["scale", "all", "plain", "bool", "all"],
    }
    return [
        Table(f"{profile}_{family}", f"trend_{profile}", tuple(FAMILY_COLUMNS[family]), dq, profile)
        for profile, dqs in rotations.items()
        for family, dq in zip(FAMILIES, dqs)
    ]


TABLES: list[Table] = _family_tables() + _mixed_tables() + _sample_tables() + _profile_tables()
FUNCTIONS: dict[str, list[Table]] = {}
for _t in TABLES:
    FUNCTIONS.setdefault(_t.function, []).append(_t)
assert len(TABLES) == 50 and len(FUNCTIONS) == 10
assert all(len(ts) == 5 for ts in FUNCTIONS.values())
assert len({t.name for t in TABLES}) == 50


# --- what a boolean classifier's summary holds ----------------------------------


def expected_booleans(table: Table, t: int) -> dict[str, dict[str, int]]:
    """{classifier: {dq.true, dq.false, dq.none, dq.nan}} for trigger `t`. A null
    row is a null verdict and a NaN a nan verdict, except to the classifier asking
    about them: IsNotNull fails a null (and leaves a NaN nan), IsNotNan fails a NaN
    (and leaves a null null)."""
    out = {}
    for name in table.columns:
        col = COLUMNS[name]
        d = defects(table.profile, col, t)
        out[f"@td.dq.{name}_is_not_null"] = {
            "dq.true": ROWS - d.null - d.nan, "dq.false": d.null, "dq.none": 0, "dq.nan": d.nan,
        }
        out[f"@td.dq.{name}_is_between"] = {
            "dq.true": ROWS - d.null - d.nan - d.out_of_range,
            "dq.false": d.out_of_range,
            "dq.none": d.null,
            "dq.nan": d.nan,
        }
        if col.floating:
            out[f"@td.dq.{name}_is_not_nan"] = {
                "dq.true": ROWS - d.null - d.nan, "dq.false": d.nan, "dq.none": d.null, "dq.nan": 0,
            }
    return out
