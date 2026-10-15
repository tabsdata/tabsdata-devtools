#
# Copyright 2026 Tabsdata Inc.
#
"""Datatype coverage — cast to the narrow / parametric / nested dtypes that the
rest of the suite never exercises (UInt8 / Int16 / Int32 / Float32 / Boolean /
Decimal / Categorical / Map) and carry Struct / List columns through a select.

Uses SPECIAL verifiers instead of the default frame-equal: ``dtype_check`` asserts
the RESULT column's dtype is exactly the intended one (the datatype IS the thing
under test) and then compares values dtype-insensitively; ``nested_is`` asserts a
column is a Struct / List / Map and compares values. (Value-insensitivity to dtype means
these still report a clean pass/fail on the intended dtype even where a storage
round-trip would promote a narrow type.)"""
from __future__ import annotations

import polars as pl
from polars.testing import assert_frame_equal
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase
except ImportError:
    from _harness import OPS, SRC, Check, TFCase


def dtype_check(**expect):
    """Verifier factory: assert each named RESULT column has exactly the intended
    dtype, then compare values (order- and dtype-insensitive)."""

    def verify(received: pl.DataFrame, expected: pl.DataFrame) -> None:
        for col, dt in expect.items():
            got = received.schema[col]
            assert got == dt, f"column {col!r}: dtype {got!r}, expected {dt!r}"
        assert_frame_equal(received, expected, check_row_order=False, check_dtypes=False)

    return verify


def nested_is(**expect):
    """Verifier factory: assert each named column is an instance of the given
    nested dtype (Struct / List / Map), then compare values (order/dtype-insensitive)."""

    def verify(received: pl.DataFrame, expected: pl.DataFrame) -> None:
        for col, base in expect.items():
            got = received.schema[col]
            assert isinstance(got, base), f"column {col!r}: {got!r} is not a {base!r}"
        assert_frame_equal(received, expected, check_row_order=False, check_dtypes=False)

    return verify


_INPUT = pl.DataFrame(
    {
        "a": [0, 1, 2, 3],
        "s": ["x", "y", "x", "z"],
        "st": [{"p": 1, "q": 2}, {"p": 3, "q": 4}, {"p": 5, "q": 6}, {"p": 7, "q": 8}],
        "li": [[1, 2], [3], [4, 5], [6]],
        "kv": [
            [{"key": "a", "value": 1}],
            [{"key": "b", "value": 2}, {"key": "c", "value": 3}],
            [],
            [{"key": "d", "value": 4}],
        ],
    }
)
CASE = TFCase(
    inputs={"dtc_in": _INPUT},
    checks=[
        Check("dtc_uint8", lambda f, t: t.select(f.col("a").cast(pl.UInt8).alias("r")), dtype_check(r=pl.UInt8)),
        Check("dtc_int16", lambda f, t: t.select(f.col("a").cast(pl.Int16).alias("r")), dtype_check(r=pl.Int16)),
        Check("dtc_int32", lambda f, t: t.select(f.col("a").cast(pl.Int32).alias("r")), dtype_check(r=pl.Int32)),
        Check("dtc_float32", lambda f, t: t.select(f.col("a").cast(pl.Float32).alias("r")), dtype_check(r=pl.Float32)),
        Check("dtc_boolean", lambda f, t: t.select(f.col("a").cast(pl.Boolean).alias("r")), dtype_check(r=pl.Boolean)),
        Check("dtc_decimal", lambda f, t: t.select(f.col("a").cast(pl.Decimal(scale=2)).alias("r")), dtype_check(r=pl.Decimal(38, 2))),
        Check("dtc_categorical", lambda f, t: t.select(f.col("s").cast(pl.Categorical).alias("r")), dtype_check(r=pl.Categorical)),
        Check("dtc_struct", lambda f, t: t.select("st"), nested_is(st=pl.Struct)),
        Check("dtc_list", lambda f, t: t.select("li"), nested_is(li=pl.List)),
        Check("dtc_map", lambda f, t: t.select(f.col("kv").cast(pl.Map(pl.String, pl.Int64)).alias("r")), nested_is(r=pl.Map)),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dtc_in"])
def dtc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dtc_in@NEW"], output_tables=CASE.output_names)
def dtc_tfr(
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
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dtc_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
    c8: TableFrameSpec,
    c9: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7, c8, c9])
    return TableFrame.empty()
