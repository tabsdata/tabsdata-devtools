#
# Copyright 2026 Tabsdata Inc.
#
"""_harness — reusable scaffolding for the ``tableframe_api`` suite.

PURPOSE
    The ``tableframe_api`` suite exercises the Tabsdata **TableFrame API**
    exhaustively: for every operation it confirms that (a) the call runs through
    a real flow without an internal error and (b) it produces the SAME result the
    equivalent polars expression does. The TableFrame API is a thin
    ``wrap(pl_method(unwrap(...)))`` passthrough over polars, so "matches polars"
    is the whole specification — a divergence is either a bug or a deliberate
    restriction (marked :data:`IGNORE`).

    Each test file is a three-function chain over the suite's three collections:

        pub  (@publisher , collection ``tf_src`` , DataGenSrc)
            emits one or more fixed input tables from in-process polars frames.
        tfr  (@transformer, collection ``tf_ops`` , connection-less)
            reads the published table(s) and applies the OPERATIONS UNDER TEST
            with the TableFrame API, emitting one result table per check.
        sub  (@subscriber , collection ``tf_sink``, TrashDest)
            reads the transformer's result tables, re-applies the SAME operations
            to the original polars inputs, and asserts each received table equals
            its expected frame. TrashDest then discards them; the test's only job
            is the assertion. A failed assertion raises, failing the transaction —
            that is the red/green signal.

THE ``f`` NAMESPACE
    An operation is written ONCE and invoked twice: with TableFrame(s) in the
    transformer and with polars DataFrame(s) in the subscriber's re-computation.
    Anything reached through a frame method (``select`` / ``filter`` / ``sort`` /
    ``col(...).str`` / ``col(...).dt`` / ...) has the same name on both surfaces,
    so it "just works". The one asymmetry is the free functions ``col`` / ``lit``
    / ``concat``: on the TableFrame path they must come from
    ``tabsdatak.tableframe.functions``; on the polars path from ``polars``. So
    every op takes a leading ``f`` parameter — the functions namespace — and uses
    ``f.col(...)`` / ``f.lit(...)`` / ``f.concat(...)``. Datatypes are shared
    (tabsdatak aliases ``pl`` dtypes and passes them through unchanged), so casts
    always use ``pl.<Type>`` directly on both paths.

ORDER
    Neither the storage round-trip nor most operations promise a stable row
    order, so the default verifier is :data:`unordered_equal`. An operation whose
    result IS order-dependent (``sort`` / ``head`` / ``tail`` / ``slice`` /
    ``diff`` / ``rank`` / ...) must first make itself deterministic — sort by a
    unique key inside the op — and then use :data:`ordered_equal`.

ADDING A TEST
    Copy an existing file. Define the input frame(s), a list of :class:`Check`
    (each a name + an ``op(f, *frames)`` + its verifier), build one module-level
    ``CASE = TFCase(inputs=..., checks=...)``, and wire the pub/tfr/sub triple
    (thin stubs that delegate to the case). The transformer's ``output_tables``
    and the subscriber's ``input_tables`` come from ``CASE.output_names``; only
    the function signatures must be spelled out with the right arity (one param
    per check, and a return tuple of that many ``TableFrameSpec``). Reference
    shapes: ``tf_select.py`` (one input, one check), ``tf_split.py`` (one input,
    several checks), ``tf_join.py`` (two inputs).

    Then check it and register it — two dev tools live in the suite root:
      * ``python ../validate.py tf_<op>``  — imports the file (runs the decorator
        signature checks) and runs ``CASE.selfcheck()`` (a ``from_polars``
        round-trip + compare vs polars). Fast, no server.
      * add the stem to the right category in ``../gen_suites.py`` and run
        ``python ../gen_suites.py`` — regenerates every ``<category>.json`` from
        the files (no hand-editing of JSON).
    Then ``tdx-xp speedy --suite tableframe_api/<category>`` runs one category,
    or ``tdx-xp speedy --suite tableframe_api`` runs the whole suite (a bare
    ``--suite <dir>`` unions every ``*.json`` in the dir).

    Name each file ``tf_<op>.py``: the worker imports a function's file by its
    bare stem with the bundle dir on ``sys.path``, so a stem that collides with a
    top-level module (``select``, ``array``, ``queue``, ...) would shadow it and
    break the import — the ``tf_`` prefix keeps every stem clear.

    Every file exposes its ``CASE`` at module level so the offline validator can
    run ``CASE.selfcheck()`` (a ``from_polars`` round-trip + verify) without the
    server.

Import this module from a test file with the relative-then-absolute fallback::

    try:
        from ._harness import Check, TFCase, OPS, SRC, unordered_equal
    except ImportError:
        from _harness import Check, TFCase, OPS, SRC, unordered_equal

At registration the CLI loads the function file as a submodule of a synthetic
package (the RELATIVE import resolves); on the worker the file is imported
top-level with the bundle directory on ``sys.path`` (the ABSOLUTE import
resolves). The try/except makes one file work in both.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, Union

import polars as pl
from polars.testing import assert_frame_equal

import tabsdatak.tableframe.functions as _TDK_FN
from tabsdatak.conn.dev import Data
from tabsdatak.tableframe import TableFrame

# Collection names, shared so every test file's cross-collection table refs
# (transformer input ``<SRC>/<table>@NEW``, subscriber input ``<OPS>/<table>``)
# stay in lockstep with the collections declared in the suite JSON.
SRC = "tf_src"     # sources        — DataGenSrc publishers
OPS = "tf_ops"     # transform      — TableFrame operations under test
SINK = "tf_sink"   # destinations   — TrashDest subscribers (assert + discard)

# --- type aliases: the harness's vocabulary ---------------------------------
# A frame an op accepts/returns: a TableFrame in the transformer, an eager polars
# DataFrame in the subscriber's re-computation — so an op may use only methods
# common to both surfaces.
Frame: TypeAlias = Union[TableFrame, pl.DataFrame]
# The functions namespace passed to an op as its first argument: the tabsdatak
# ``functions`` module on the TableFrame path, the ``polars`` module on the
# verify path. Both expose ``col`` / ``lit`` / ``concat``.
Funcs: TypeAlias = object
# A single operation under test: ``op(f, *frames) -> frame``. ``f`` is the
# namespace above; ``frames`` are the case's input frames (TableFrames when run
# by the transformer, polars DataFrames when re-run by verify).
CheckOp: TypeAlias = Callable[..., Frame]

# A verifier compares the received result (first arg) against the expected result
# (second arg) — both eager polars DataFrames — raising AssertionError on any
# mismatch. Two are built in below; a check may carry its own for a bespoke test.
Verifier: TypeAlias = Callable[[pl.DataFrame, pl.DataFrame], None]


class _Ignore:
    """The type of :data:`IGNORE` — a distinct type so ``TableVerifier`` reads clearly."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "IGNORE"


IGNORE: _Ignore = _Ignore()
"""Verifier sentinel: run the check through the flow but do NOT compare it.

Use it for an operation whose TableFrame result is expected to diverge from
polars (or is not yet comparable) — the op still has to run without an internal
error, but its output is left unchecked.
"""

# A per-check verifier: a real Verifier, or IGNORE to skip the comparison.
TableVerifier: TypeAlias = Union[Verifier, _Ignore]
# An explicit expectation: given the polars inputs, return the expected frame — or
# None. Use it for a tabsdata-specific behaviour that polars CANNOT reproduce (so
# ``op`` can't just be re-run on the polars surface), e.g. ``concat`` skipping a
# None element or returning None for empty/None input.
ExpectedFn: TypeAlias = Callable[..., Union[Frame, None]]
# The transformer output handed to verify(): one TableFrame or a sequence of them.
Received: TypeAlias = Union[TableFrame, Sequence[TableFrame]]
# The TFCase inputs: publisher table name -> eager polars DataFrame.
Inputs: TypeAlias = Mapping[str, pl.DataFrame]

# Built-in verifiers. ``unordered_equal`` ignores row order — neither the storage
# round-trip nor most operations promise a stable order; use ``ordered_equal``
# for an op that ends in an explicit, deterministic ``sort``. Both always compare
# schema, column order and dtypes.
unordered_equal: Verifier = lambda received, expected: assert_frame_equal(
    received, expected, check_row_order=False
)
ordered_equal: Verifier = lambda received, expected: assert_frame_equal(
    received, expected, check_row_order=True
)


@dataclass(frozen=True)
class Check:
    """One operation under test plus how to verify it.

    ``name``   : the result table name this check emits (a valid table
                 identifier: alphanumerics / underscores, leading letter). Unique
                 within its file.
    ``op``     : ``op(f, *frames) -> frame`` — the operation, using ``f.col`` /
                 ``f.lit`` / ``f.concat`` for free functions and ``pl.<Type>`` for
                 datatypes so it runs on both the TableFrame and polars surfaces.
    ``verify`` : how to compare the received result to the expected —
                 :data:`unordered_equal` (default), :data:`ordered_equal`, a
                 custom :data:`Verifier`, or :data:`IGNORE` to run-but-not-compare.
    ``expected``: optional :data:`ExpectedFn` — override how the expectation is
                 computed. By default it is ``op`` re-run on the polars inputs;
                 supply this when the TableFrame behaviour diverges from polars in
                 a way polars can't reproduce (e.g. ``concat`` of a None element,
                 or a result of ``None``). Receives the polars inputs, returns the
                 expected frame or ``None``.
    """

    name: str
    op: CheckOp
    verify: TableVerifier = unordered_equal
    expected: Union[ExpectedFn, None] = None


def _tuplify(value) -> tuple:
    # A lone frame -> a 1-tuple; a tuple/list -> a tuple. Lets single- and
    # multi-check cases share one code path.
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def _as_pl_df(frame: Frame) -> pl.DataFrame:
    # The polars-path result of an op. Frame ops return an eager DataFrame; a
    # LazyFrame (should not happen for these ops) is collected defensively.
    if isinstance(frame, pl.LazyFrame):
        return frame.collect()
    return frame


def _materialize(got):
    # A received result -> eager polars DataFrame (system columns dropped), or None
    # when the slot is empty (the transformer emitted no version for it).
    return got._to_polars_lf().collect() if got is not None else None


def _expected(check: "Check", pl_inputs: tuple) -> Union[pl.DataFrame, None]:
    # The expected result: the check's ``expected`` override if set, otherwise the
    # op re-run on the polars inputs. Returns an eager DataFrame or None.
    raw = check.expected(*pl_inputs) if check.expected is not None else check.op(pl, *pl_inputs)
    return _as_pl_df(raw) if raw is not None else None


def _compare(name: str, got_df, want_df, verifier: Verifier) -> None:
    # Compare a received frame (or None) to an expected frame (or None). None is a
    # first-class result — both None passes; exactly one None fails.
    if got_df is None or want_df is None:
        assert got_df is None and want_df is None, (
            f"check {name!r}: expected {'None' if want_df is None else 'a frame'}, "
            f"received {'None' if got_df is None else 'a frame'}"
        )
        return
    verifier(got_df, want_df)


class TFCase:
    """One TableFrame-API test case: the fixed inputs and the checks over them.

    A test file builds a single ``TFCase`` and threads it through the pub/tfr/sub
    triple — the publisher emits :attr:`data`, the transformer calls
    :meth:`transform`, the subscriber calls :meth:`verify`. :meth:`selfcheck`
    runs the whole comparison offline (no server) for fast iteration.
    """

    def __init__(self, inputs: Inputs, checks: Sequence[Check]) -> None:
        # ``inputs`` : publisher table name -> eager polars DataFrame. DataGen's
        #              ``Data`` requires an EAGER frame; insertion order fixes the
        #              positional order the frames are passed to each op.
        # ``checks`` : the operations under test, one result table each.
        self.inputs = dict(inputs)
        self.checks = tuple(checks)
        assert self.checks, "a TFCase needs at least one Check"

    @property
    def data(self) -> list[Data]:
        """The ``DataGenSrc(data=...)`` payload: one ``Data`` per input table."""
        return [Data(df) for df in self.inputs.values()]

    @property
    def output_names(self) -> list[str]:
        """The result table names, in check order — the transformer's
        ``output_tables`` and (bare) the subscriber's ``input_tables``."""
        return [c.name for c in self.checks]

    def transform(self, *frames: TableFrame) -> tuple:
        """Apply every check's op to the published TableFrame(s).

        Returns one TableFrame per check, in order — the transformer's output
        tables (its ``output_tables`` must match :attr:`output_names`). Ops run on
        the tabsdatak functions namespace here.
        """
        return tuple(c.op(_TDK_FN, *frames) for c in self.checks)

    def verify(self, received: Received) -> None:
        """Re-derive each expected result in polars and compare to ``received``.

        ``received`` is the transformer's output: the result TableFrames, one per
        check, in order (a slot may be ``None`` when the op produced no version).
        Each is materialised with ``to_polars_lf().collect()`` (system columns
        dropped, made eager); the expectation is the check's :data:`ExpectedFn`
        override, else the same op applied to the original polars inputs. Each
        check's own verifier compares — :data:`IGNORE` skips it, and ``None`` is a
        first-class result (both-None passes). Raises ``AssertionError`` on any
        mismatch.
        """
        actual = _tuplify(received)
        assert len(actual) == len(self.checks), (
            f"output-arity mismatch: {len(self.checks)} check(s) but "
            f"{len(actual)} table(s) received"
        )
        pl_inputs = tuple(self.inputs.values())
        for got, check in zip(actual, self.checks):
            if check.verify is IGNORE:
                continue
            _compare(check.name, _materialize(got), _expected(check, pl_inputs), check.verify)

    def selfcheck(self) -> None:
        """Run every check offline via ``TableFrame.from_polars`` (no server; does
        NOT test the storage round-trip — that is what ``speedy`` / ``bench`` do).

        Each check runs independently: an op that raises or mismatches is recorded
        against that check and the others still run, so the validator reports the
        precise set of failing checks. Raises ``AssertionError`` listing them.
        """
        frames = tuple(TableFrame.from_polars(df) for df in self.inputs.values())
        pl_inputs = tuple(self.inputs.values())
        failures: list[str] = []
        for check in self.checks:
            if check.verify is IGNORE:
                continue
            try:
                _compare(
                    check.name,
                    _materialize(check.op(_TDK_FN, *frames)),
                    _expected(check, pl_inputs),
                    check.verify,
                )
            except Exception as e:  # noqa: BLE001 -- record & continue to the next check
                first = str(e).splitlines()[0] if str(e) else ""
                failures.append(f"{check.name}: {type(e).__name__}: {first[:140]}")
        if failures:
            raise AssertionError("; ".join(failures))
