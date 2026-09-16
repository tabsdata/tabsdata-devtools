#
# Copyright 2026 Tabsdata Inc.
#
"""_harness — reusable scaffolding for the ``dataquality`` suite.

PURPOSE
    The ``dataquality`` suite exercises Tabsdata's **data-quality** feature end to
    end. A data-quality check is declared on a function decorator as
    ``on_tables=[DataQuality(...)]`` (a set of CLASSIFIERS that label each row of a
    target table and OPERATORS that act on those labels — enrich, summarise,
    filter, select, fail). The server runs the action against the function's
    OUTPUT tables and, besides rewriting a table in place, REGISTERS additional
    derived tables in the same collection. This suite confirms that a full run
    (register -> trigger -> storage round-trip -> derived-table registration)
    produces exactly the data the data-quality engine is specified to produce.

    Each test file is a three-function chain over the suite's three collections,
    modelled on the ``tableframe_api`` suite:

        pub  (@publisher , collection ``dq_src`` , DataGenSrc)
            emits the fixed raw input table(s) from in-process polars frames.
        tfr  (@transformer, collection ``dq_ops`` , connection-less)
            reads the raw table(s), returns them UNCHANGED as its output
            table(s), and carries the DATA-QUALITY ACTION under test in
            ``on_tables``. The transform itself is a pass-through; the action is
            what is being tested — the server applies it to the output tables,
            rewriting them in place and/or emitting derived tables.
        sub  (@subscriber , collection ``dq_sink``, TrashDest)
            reads the resulting tables (the rewritten output table(s) and the
            derived tables), asserts each equals its expected frame, and discards
            them. A failed assertion raises, failing the transaction — the
            red/green signal.

THE ORACLE
    Unlike ``tableframe_api`` (where polars is an independent oracle), a
    data-quality result has no external reference implementation, so each test
    states its EXPECTED frames directly, computed from a small input of KNOWN
    composition (how many positives / negatives / nulls / nans / ...). Authored
    expectations are the independent oracle: they catch engine regressions, not
    only integration ones.

    :meth:`DQCase.selfcheck` cross-checks those expectations OFFLINE (no server)
    by running the real :class:`DataQualityProcessor` — the very code the worker
    runs — over the inputs and comparing its output to the authored frames. So a
    green ``validate.py`` means "the authored expectations match the engine"; a
    green live run then additionally means "the full register/trigger/storage
    path preserves that result".

DERIVED-TABLE NAMES
    An operator that produces a new table names it:
      * ``Enrich(to_table=X)`` / ``Filter(to_table=X)`` / ``Select(to_table=X)``
        -> a table named exactly ``X``.
      * ``Enrich()`` / ``Filter()`` with no ``to_table`` -> rewrites the target
        output table IN PLACE (no new table).
      * ``Summary()`` -> ``<target>_dq_summary`` (or a custom ``Summary(table=X)``
        -> ``X``).
    List every table the subscriber must read in ``DQCase.expects`` (the target
    table AND each derived table), in the order the subscriber's params take them.
    :meth:`DQCase.selfcheck` verifies the names you listed are exactly the ones
    the engine produces.

VERDICT COLUMN NAMES
    The engine names the verdict column a classifier produces for a column
    ``<prefix><column>_<classifier>``: ``value_is_positive`` for
    ``IsPositive(["value"])``, ``value_category`` for a ``ScaleCategorizer``,
    under its default prefix (``@td.dq.`` today; a classifier's ``prefix``
    argument can change it, this suite tests the default). That prefixed name is
    also what a summary row's ``dq.classifier`` holds and what a category criteria
    (``InBins`` / ``NotInBins``) must be given as ``column_name``. Test files,
    their docstrings and comments spell the BARE ``<column>_<classifier>`` name,
    the part that says what the column is, and pass it through :func:`verdict`
    wherever code states the real column name. The prefix is imported from the
    engine rather than spelled here, so the next rename fails every test at
    import, in one place, instead of one expectation at a time.

ENRICH SENTINELS
    An enrich/classifier column is a ``UInt8`` whose values are the classifier's
    verdict per row: ``1`` true, ``0`` false, and the reserved sentinels
    ``252`` underflow, ``253`` overflow, ``254`` nan, ``255`` null (see
    :class:`Sentinel`). A summary row's ``dq.type`` is ``boolean`` for a
    predicate classifier or ``category`` for a categorizer; boolean summaries fill
    ``dq.true`` / ``dq.false`` / ``dq.nan`` / ``dq.none`` and leave the ``dq.pNNN``
    bin columns null.

ADDING A TEST
    Copy an existing file. Define the input frame(s) of known composition, build
    the ``DataQuality`` action, author the expected output frames (every verdict
    column named through :func:`verdict`), and assemble one
    module-level ``CASE = DQCase(inputs=..., action=..., main_tables=...,
    expects=...)``. Wire the thin pub/tfr/sub triple (the transformer just returns
    its input and carries ``on_tables=[CASE.action]``); spell out the subscriber
    signature with one param per entry in ``CASE.output_names``. Then:
      * ``python ../validate.py dq_<name>`` — imports the file (runs the decorator
        signature checks) and runs ``CASE.selfcheck()``. Fast, no server.
      * add the stem to the right category in ``../gen_suites.py`` and run
        ``python ../gen_suites.py`` — regenerates every ``<category>.json`` (no
        hand-editing of JSON).
    Then ``tdx-xp oneshot --suite dataquality/<category>`` runs one category, or
    ``tdx-xp oneshot --suite dataquality`` runs the whole suite (a bare
    ``--suite <dir>`` unions every ``*.json`` in the dir).

    Name each file ``dq_<name>.py``: the worker imports a function's file by its
    bare stem with the bundle dir on ``sys.path``, so the ``dq_`` prefix keeps
    every stem clear of stdlib module names.

Import this module from a test file with the relative-then-absolute fallback::

    try:
        from ._harness import OPS, SRC, DQCase, Expect, subset_equal, verdict
    except ImportError:
        from _harness import OPS, SRC, DQCase, Expect, subset_equal, verdict

At registration the CLI loads the function file as a submodule of a synthetic
package (the RELATIVE import resolves); on the worker the file is imported
top-level with the bundle directory on ``sys.path`` (the ABSOLUTE import
resolves). The try/except makes one file work in both.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import TypeAlias, Union

import polars as pl
from polars.testing import assert_frame_equal

from tabsdatak.conn.dev import Data
from tabsdatak.dataquality import DataQuality

# The engine's verdict-column prefix (see VERDICT COLUMN NAMES): not re-exported
# by the public package, hence the private module. Imported rather than spelled
# so the next rename fails every test at import, in this one place.
from tabsdatak.dataquality._typing import DEFAULT_VERDICT_COLUMN_PREFIX
from tabsdatak.tableframe import TableFrame

# A DQCase ``name`` must be a table-safe identifier; capped so ``<name>__<relative>``
# stays within the connector's 64-char table-name limit.
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,40}$")

# Collection names, shared so every test file's cross-collection table refs
# (transformer input ``<SRC>/<table>@NEW``, subscriber input ``<OPS>/<table>``)
# stay in lockstep with the collections declared in the suite JSON.
SRC = "dq_src"      # sources        — DataGenSrc publishers (raw input)
OPS = "dq_ops"      # data quality   — @transformer carrying on_tables=[DataQuality]
SINK = "dq_sink"    # destinations   — TrashDest subscribers (assert + discard)


class Sentinel(IntEnum):
    """The reserved UInt8 values an enrich/classifier column can take.

    A classifier column holds ``TRUE``/``FALSE`` for a plain verdict and one of
    the reserved sentinels when the row could not be classified as either.
    Mirrors ``tabsdatak...dataquality.engine.ByteSentinel``.
    """

    FALSE = 0
    TRUE = 1
    UNDERFLOW = 252
    OVERFLOW = 253
    NAN = 254
    NULL = 255


def verdict(name: str) -> str:
    """The real column name for the bare verdict name ``name``.

    ``name`` is ``<column>_<classifier>`` (``value_is_positive``,
    ``value_category``); the engine prepends its default prefix (see VERDICT
    COLUMN NAMES in the module docstring). Use it wherever a test states a verdict
    column in code: an expected frame's column, a summary frame's
    ``dq.classifier`` value, a category criteria's ``column_name``.
    """
    return f"{DEFAULT_VERDICT_COLUMN_PREFIX}{name}"


# --- type aliases: the harness's vocabulary ---------------------------------
# A verifier compares the received result (first arg) against the expected result
# (second arg) — both eager polars DataFrames — raising AssertionError on any
# mismatch. Built-ins below; an Expect may carry its own for a bespoke test.
Verifier: TypeAlias = Callable[[pl.DataFrame, pl.DataFrame], None]
# The DQCase inputs: publisher table name -> eager polars DataFrame.
Inputs: TypeAlias = Mapping[str, pl.DataFrame]


class _Ignore:
    """The type of :data:`IGNORE` — a distinct type so ``TableVerifier`` reads clearly."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "IGNORE"


IGNORE: _Ignore = _Ignore()
"""Verifier sentinel: read the table through the flow but do NOT compare it.

Use it for a derived table whose content is not the point of a given test (it
still has to be produced without error), leaving its data unchecked.
"""

TableVerifier: TypeAlias = Union[Verifier, _Ignore]

# Built-in verifiers. ``unordered_equal`` (the default) ignores row order — the
# storage round-trip does not promise a stable order — but is otherwise strict:
# it compares schema, column order, dtypes and values. ``ordered_equal`` also
# pins row order (use it for a table produced by a deterministic sort).
unordered_equal: Verifier = lambda received, expected: assert_frame_equal(
    received, expected, check_row_order=False
)
ordered_equal: Verifier = lambda received, expected: assert_frame_equal(
    received, expected, check_row_order=True
)


def subset_equal(*columns: str) -> Verifier:
    """A verifier that compares only ``columns`` (order-insensitive, dtype-lax).

    Handy for the wide summary table (112 columns, many null for a given
    classifier): author an expected frame of just the meaningful columns and
    compare that projection. Row order is ignored; dtypes are NOT checked (the
    exact integer width of a count is an engine detail), so the comparison is
    about VALUES in the named columns.
    """

    cols = list(columns)

    def _verify(received: pl.DataFrame, expected: pl.DataFrame) -> None:
        assert_frame_equal(
            received.select(cols),
            expected.select(cols),
            check_row_order=False,
            check_dtypes=False,
        )

    return _verify


@dataclass(frozen=True)
class Expect:
    """The expected content of one table the data-quality action yields.

    ``table``  : the table name (in ``dq_ops``) — the action's target table
                 (rewritten in place) or a derived table (see DERIVED-TABLE NAMES
                 in the module docstring). The subscriber reads these in the order
                 they are listed on the case.
    ``frame``  : the expected eager polars DataFrame.
    ``verify`` : how to compare — :data:`unordered_equal` (default),
                 :data:`ordered_equal`, a :func:`subset_equal` projection, a
                 custom :data:`Verifier`, or :data:`IGNORE` to read-but-not-check.
    """

    table: str
    frame: pl.DataFrame
    verify: TableVerifier = unordered_equal


def _tuplify(value) -> tuple:
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def _materialize(got):
    # A received result -> eager polars DataFrame (system columns dropped), or None
    # when the slot is empty (no version was produced for it).
    return got._to_polars_lf().collect() if got is not None else None


def _compare(name: str, got_df, want_df, verifier: Verifier) -> None:
    if got_df is None or want_df is None:
        assert got_df is None and want_df is None, (
            f"table {name!r}: expected {'None' if want_df is None else 'a frame'}, "
            f"received {'None' if got_df is None else 'a frame'}"
        )
        return
    verifier(got_df, want_df)


class DQCase:
    """One data-quality test case: fixed inputs, one action, expected outputs.

    A test file builds a single ``DQCase`` and threads it through the pub/tfr/sub
    triple — the publisher emits :attr:`data`, the transformer returns its input
    and carries :attr:`action` in ``on_tables``, the subscriber calls
    :meth:`verify`. :meth:`selfcheck` reproduces the whole comparison offline (no
    server) by running the real data-quality processor.
    """

    def __init__(
        self,
        inputs: Inputs,
        action: DataQuality,
        main_tables: Sequence[str],
        expects: Sequence[Expect],
        *,
        name: str | None = None,
    ) -> None:
        # ``inputs``      : publisher table name -> eager polars DataFrame. DataGen's
        #                   ``Data`` requires an EAGER frame; insertion order fixes
        #                   the positional order the frames flow to the transformer.
        # ``action``      : the DataQuality action under test; its ``table`` must be
        #                   one of ``main_tables``.
        # ``main_tables`` : the transformer's declared ``output_tables`` — the
        #                   pass-through outputs the action acts on.
        # ``expects``     : one Expect per table the subscriber reads, in order.
        # ``name``        : the per-file NAMESPACE key. Every table name in a test
        #                   file is written RELATIVE (unprefixed) — inputs, main
        #                   tables, the action's target, each operator to_table/table,
        #                   and each Expect — and DQCase namespaces them all as
        #                   ``<name>__<relative>``, so many tests coexist in the shared
        #                   dq_src / dq_ops collections without table-name collisions
        #                   (which `tdk fn register` rejects; `validate.py` can't see
        #                   them because it runs each file in isolation). Defaults to
        #                   the caller module's stem — stable across the worker's
        #                   bare-stem import and the CLI's synthetic-package import
        #                   (the last dotted component is the file stem in both).
        if name is None:
            frame = inspect.currentframe()
            caller = frame.f_back if frame is not None else None
            modname = (
                caller.f_globals.get("__name__", "dq") if caller is not None else "dq"
            )
            name = modname.rsplit(".", 1)[-1]
        assert _NAME_RE.fullmatch(name), (
            f"DQCase name {name!r} must be a table-safe identifier "
            f"(a letter, then up to 40 alphanumerics/underscores)"
        )
        self.name = name
        # inputs keys stay RELATIVE (the values, in order, are the DataGen payload);
        # ``input_names`` exposes the namespaced publisher table names.
        self.inputs = dict(inputs)
        self.main_tables = [self._pfx(t) for t in main_tables]
        self.action = self._prefix_action(action)
        self.expects = tuple(
            Expect(self._pfx(e.table), e.frame, e.verify) for e in expects
        )
        assert self.expects, "a DQCase needs at least one Expect"
        assert self.main_tables, "a DQCase needs at least one main (output) table"

    def _pfx(self, table: str) -> str:
        """Namespace a relative table name as ``<name>__<table>``. A pure prepend, so
        the engine's derived ``<target>_dq_summary`` stays consistent with a prefixed
        ``Expect("<target>_dq_summary")`` — both resolve to the same string."""
        return f"{self.name}__{table}"

    def _prefix_action(self, action: DataQuality) -> DataQuality:
        """Rebuild the action with its target table and every operator's explicit
        derived-table name namespaced. DataQuality/operators are FROZEN pydantic
        dataclasses, so ``dataclasses.replace`` returns validated copies rather than
        mutating in place."""
        new_ops = [self._prefix_operator(op) for op in action.operators]
        return replace(action, table=self._pfx(action.table), operators=new_ops)

    def _prefix_operator(self, op):
        # Enrich/Filter/Select carry ``to_table``; Summary carries ``table``; Fail has
        # neither (it emits no table). Rewrite whichever explicit rename is set; a
        # default in-place Enrich()/Summary() is left untouched and follows the
        # prefixed target automatically.
        if getattr(op, "to_table", None) is not None:
            return replace(op, to_table=self._pfx(op.to_table))
        if getattr(op, "table", None) is not None:
            return replace(op, table=self._pfx(op.table))
        return op

    @property
    def data(self) -> list[Data]:
        """The ``DataGenSrc(data=...)`` payload: one ``Data`` per input table."""
        return [Data(df) for df in self.inputs.values()]

    @property
    def input_names(self) -> list[str]:
        """The publisher's ``output_tables`` — the namespaced raw input table names."""
        return [self._pfx(k) for k in self.inputs]

    @property
    def output_names(self) -> list[str]:
        """The tables the subscriber reads, in order — bare names in ``dq_ops``."""
        return [e.table for e in self.expects]

    def transform(self, *frames: TableFrame) -> tuple:
        """Pass the raw input frame(s) straight through as the output table(s).

        The data-quality action (carried in the transformer's ``on_tables``) is
        what is under test; the transform itself is the identity. Returns one
        frame per entry in :attr:`main_tables`, in order.
        """
        assert len(frames) == len(self.main_tables), (
            f"transform arity: {len(self.main_tables)} main table(s) but "
            f"{len(frames)} input frame(s)"
        )
        return frames if len(frames) > 1 else frames[0]

    def verify(self, received) -> None:
        """Compare each received table to its :class:`Expect`, in listed order.

        ``received`` is the subscriber's inputs: the rewritten target table(s) and
        the derived tables, one per :attr:`expects` entry, in order. Each is
        materialised with ``to_polars_lf().collect()`` (system columns dropped,
        made eager) and compared by that entry's verifier. Raises
        ``AssertionError`` on any mismatch.
        """
        actual = _tuplify(received)
        assert len(actual) == len(self.expects), (
            f"output-arity mismatch: {len(self.expects)} expected table(s) but "
            f"{len(actual)} received"
        )
        for got, expect in zip(actual, self.expects):
            if expect.verify is IGNORE:
                continue
            _compare(expect.table, _materialize(got), expect.frame, expect.verify)

    def selfcheck(self) -> None:
        """Run the data-quality engine OFFLINE and compare to the authored frames.

        Reproduces what the worker does — builds the input TableFrame(s), runs the
        real :class:`DataQualityProcessor` over the action, and collects every
        table it yields (the rewritten target table(s) positionally, plus each
        derived table by the name the engine assigns). Then, for each
        :class:`Expect`, looks up the produced table by name and compares. Also
        asserts the set of produced table names matches the names the case lists,
        so a mis-named or missing derived table is caught offline.

        Each expectation is checked independently: a mismatch is recorded against
        its table and the others still run, so the validator reports the precise
        set of failing tables. Raises ``AssertionError`` listing them.
        """
        # Imported lazily: only validate.py / gen_suites.py need the engine, and
        # only in the EE build; the worker path never calls selfcheck.
        from tabsdatak.common._actions.dataquality.processor import (
            DataQualityProcessor,
        )

        input_frames = [TableFrame.from_polars(df) for df in self.inputs.values()]
        processor = DataQualityProcessor.from_actions(
            collection=OPS,
            output_tables=self.main_tables,
            actions=[self.action],
        )
        _, derived_infos = processor.table_names()

        main_frames = list(input_frames)
        derived_records: list = []
        processor.tables_data([], main_frames, derived_records)

        produced: dict[str, pl.DataFrame] = {}
        for name, frame in zip(self.main_tables, main_frames):
            produced[name] = _to_pl(frame)
        for info, record in zip(derived_infos, derived_records):
            produced[info.table] = _to_pl(record.derived_tf)

        failures: list[str] = []
        expected_names = set(self.output_names)
        produced_names = set(produced)
        if expected_names != produced_names:
            failures.append(
                f"table names: case lists {sorted(expected_names)} but engine "
                f"produced {sorted(produced_names)}"
            )
        for expect in self.expects:
            if expect.verify is IGNORE:
                continue
            got = produced.get(expect.table)
            if got is None:
                failures.append(f"{expect.table}: not produced by the engine")
                continue
            try:
                _compare(expect.table, got, expect.frame, expect.verify)
            except Exception as e:  # noqa: BLE001 -- record & continue to the next
                first = str(e).splitlines()[0] if str(e) else ""
                failures.append(f"{expect.table}: {type(e).__name__}: {first[:160]}")
        if failures:
            raise AssertionError("; ".join(failures))


def _to_pl(frame) -> pl.DataFrame:
    """A TableFrame (or already-eager frame) -> eager polars DataFrame, system
    columns dropped — the same shape the subscriber sees over the wire."""
    if isinstance(frame, TableFrame):
        return frame._to_polars_lf().collect()
    if isinstance(frame, pl.LazyFrame):
        return frame.collect()
    return frame
